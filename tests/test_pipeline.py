"""Tests pour `berlue.pipeline.hurlu_berlu.HurluBerlu` — unitaires, un
`OllamaClient` stubé remplace le vrai (pas de serveur Ollama requis)."""

import dataclasses
import threading
import time

import pytest

from berlue.core.schemas import Claim, Generation, PipelineResult, RagOutcome, SelfCheckOutcome, SelfCheckScore
from berlue.pipeline import hurlu_berlu
from berlue.pipeline.hurlu_berlu import HurluBerlu


class StubOllamaClient:
    """Remplace `OllamaClient` : mêmes méthodes, réponses fixées à l'avance."""

    def __init__(self, response: str = "", responses: list[str] | None = None):
        self.response = response
        self.responses = responses or []

    def generate(self, prompt: str, temperature: float = 0.0, num_predict: int | None = None) -> str:
        return self.response

    def generate_detail(
        self, prompt: str, temperature: float | None = None, num_predict: int | None = None
    ) -> Generation:
        return Generation(text=self.response, modele="stub", secondes=0.0)

    def generate_many(
        self,
        prompt: str,
        k: int,
        temperature_min: float,
        temperature_max: float,
        num_predict: int | None = None,
        max_workers: int = 1,
    ) -> list[str]:
        return self.responses


class StubRetriever:
    """Remplace `RagRetriever` — seul `verify_claims` est appelé par le pipeline."""

    def __init__(self, outcome: RagOutcome | None = None, delai: float = 0.0):
        self.outcome = outcome or RagOutcome()
        self.delai = delai
        self.appels: list[list[Claim]] = []

    def verify_claims(self, claims: list[Claim], max_workers: int = 1) -> RagOutcome:
        self.appels.append(claims)
        time.sleep(self.delai)
        return self.outcome


# --- Étapes séquentielles -----------------------------------------------------


def test_generate_answer_rend_le_texte_du_modele():
    stub = StubOllamaClient(response="L'eau mouille car elle a une faible tension de surface.")
    pipeline = HurluBerlu(llm_client=stub)

    answer = pipeline.generate_answer("Pourquoi l'eau mouille ?")

    assert answer == "L'eau mouille car elle a une faible tension de surface."


def test_extract_claims_parses_json_array():
    stub = StubOllamaClient(response='["Affirmation A.", "Affirmation B.", "Affirmation C."]')
    pipeline = HurluBerlu(llm_client=stub)

    claims = pipeline.extract_claims("Q ?", "peu importe, le stub ignore le prompt")

    assert [claim.text for claim in claims] == ["Affirmation A.", "Affirmation B.", "Affirmation C."]
    assert all(isinstance(claim, Claim) for claim in claims)
    assert all(claim.source_answer == "peu importe, le stub ignore le prompt" for claim in claims)


def test_extract_claims_ignores_prose_around_the_json_array():
    """Le prompt exige un tableau JSON nu, les petits modèles l'encadrent souvent
    de texte — l'extraction doit le retrouver plutôt que de tout rejeter."""
    stub = StubOllamaClient(response='Voici les affirmations :\n["Affirmation A."]\nJ\'espère que ça convient.')
    pipeline = HurluBerlu(llm_client=stub)

    assert [claim.text for claim in pipeline.extract_claims("Q ?", "...")] == ["Affirmation A."]


def test_extract_claims_without_a_json_array_returns_no_claims():
    """Réponse sans tableau : aucune affirmation, et surtout pas d'exception — une
    seule levée non rattrapée interrompt un run d'évaluation entier."""
    stub = StubOllamaClient(response="Je ne peux pas répondre à cette demande.")

    assert HurluBerlu(llm_client=stub).extract_claims("Q ?", "...") == []


def test_extract_claims_on_malformed_json_returns_no_claims():
    """Tableau trouvé mais JSON invalide (virgule en trop) : même exigence."""
    stub = StubOllamaClient(response='["Affirmation A.", ]')

    assert HurluBerlu(llm_client=stub).extract_claims("Q ?", "...") == []


def test_extract_claims_on_empty_answer_returns_no_claims():
    stub = StubOllamaClient(response="- ne devrait jamais être appelé")

    assert HurluBerlu(llm_client=stub).extract_claims("Q ?", "   ") == []


# --- Assemblage des deux branches ---------------------------------------------


def _pipeline_avec_branches(monkeypatch, rag: RagOutcome, selfcheck: SelfCheckOutcome, delai_selfcheck: float = 0.0):
    """Pipeline dont les deux branches sont remplacées par des doubles."""

    def faux_selfcheck(question, claims, client, **kwargs):
        time.sleep(delai_selfcheck)
        return selfcheck

    monkeypatch.setattr(hurlu_berlu, "run_selfcheck", faux_selfcheck)
    return HurluBerlu(
        llm_client=StubOllamaClient(response='["Affirmation A."]'),
        retriever=StubRetriever(outcome=rag),
    )


def test_compute_signals_assemble_les_deux_branches(monkeypatch):
    """Le résultat final réunit ce que chaque branche a produit, sans qu'aucune
    n'ait écrit dans un objet commun."""
    scores = [SelfCheckScore(claim_id="c1", divergence_score=0.2, confidence=0.8)]
    pipeline = _pipeline_avec_branches(
        monkeypatch,
        rag=RagOutcome(verdicts=[], traces=[{"claim_id": "c1"}]),
        selfcheck=SelfCheckOutcome(samples=["éch. 1", "éch. 2"], scores=scores),
    )

    result = pipeline.compute_signals("Q ?", answer="Une réponse.")

    assert result.question == "Q ?"
    assert result.raw_answer == "Une réponse."
    assert [c.text for c in result.claims] == ["Affirmation A."]
    assert result.samples == ["éch. 1", "éch. 2"]
    assert result.selfcheck_scores == scores
    assert result.rag_traces == [{"claim_id": "c1"}]
    assert result.panne is None


def test_compute_signals_remonte_la_panne_du_rag(monkeypatch):
    """Une panne RAG voyage jusqu'au résultat assemblé — c'est elle qui déclenche
    la règle R1 de la fusion."""
    pipeline = _pipeline_avec_branches(
        monkeypatch,
        rag=RagOutcome(panne="RAG en panne (réponse inexploitable)"),
        selfcheck=SelfCheckOutcome(samples=["éch."]),
    )

    result = pipeline.compute_signals("Q ?", answer="Une réponse.")

    assert result.panne == "RAG en panne (réponse inexploitable)"
    assert result.rag_scores == []
    # La branche SelfCheck n'est pas perdue pour autant : elle tournait en
    # parallèle et a fini normalement.
    assert result.samples == ["éch."]


def test_les_deux_branches_tournent_bien_en_parallele(monkeypatch):
    """Le test qui justifie tout le refacto : les deux branches doivent se
    recouvrir dans le temps, pas s'enchaîner."""
    branches_en_vol = []
    maximum_simultane = [0]
    verrou = threading.Lock()

    def _entree(nom):
        with verrou:
            branches_en_vol.append(nom)
            maximum_simultane[0] = max(maximum_simultane[0], len(branches_en_vol))

    def _sortie(nom):
        with verrou:
            branches_en_vol.remove(nom)

    def faux_selfcheck(question, claims, client, **kwargs):
        _entree("selfcheck")
        time.sleep(0.2)
        _sortie("selfcheck")
        return SelfCheckOutcome(samples=["éch."])

    class RetrieverLent(StubRetriever):
        def verify_claims(self, claims, max_workers=1):
            _entree("rag")
            time.sleep(0.2)
            _sortie("rag")
            return RagOutcome()

    monkeypatch.setattr(hurlu_berlu, "run_selfcheck", faux_selfcheck)
    pipeline = HurluBerlu(llm_client=StubOllamaClient(response='["A."]'), retriever=RetrieverLent())

    debut = time.monotonic()
    pipeline.compute_signals("Q ?", answer="Une réponse.")
    duree = time.monotonic() - debut

    assert maximum_simultane[0] == 2, "les deux branches ne se sont jamais recouvertes"
    assert duree < 0.35, f"les branches se sont enchaînées au lieu de se recouvrir ({duree:.2f}s)"


def test_le_resultat_du_pipeline_est_fige():
    """`PipelineResult` interdit l'ajout d'attributs au fil de l'eau — c'est cette
    structure, remplie étape par étape, qui empêchait de paralléliser."""
    result = PipelineResult(question="Q ?", raw_answer="...")

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.selfcheck_scores = []
