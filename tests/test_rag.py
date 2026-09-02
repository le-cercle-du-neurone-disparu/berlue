"""Test de contrat pour `berlue.rag.retriever.verify_claim` -> `RagVerdict`."""

import pytest

from berlue.core.schemas import Claim, RagJudgment, RagVerdict
from berlue.llm.client import OllamaClient
from berlue.rag.retriever import RagRetriever


@pytest.mark.functional  # a besoin d'un index FAISS + embeddings réels (RagRetriever)
def test_verify_claim_returns_rag_verdict():
    """verify_claim() doit renvoyer un RagVerdict valide pour une affirmation proche du corpus."""
    retriever = RagRetriever(llm_client=OllamaClient())
    claim = Claim(id="c1", text="Paris est la capitale de la France.", source_answer="...")
    result = retriever.verify_claim(claim)
    assert isinstance(result, RagVerdict)
    assert result.claim_id == claim.id
    assert result.verdict in RagJudgment
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.functional  # a besoin d'un index FAISS + embeddings réels (RagRetriever)
@pytest.mark.xfail(
    strict=False,
    reason=(
        "Défaut connu, non corrigé : `retrieve()` n'applique aucun seuil de distance, donc "
        "des extraits hors sujet sont présentés au modèle comme la base FEVER. Reproduit : "
        "sur l'affirmation charabia, le retriever a cité « Alphabet works in different fields » "
        "(distance 1,21, contre ~0,2 pour un vrai appariement) comme preuve d'un FEVER_CONFIRMS "
        "à confiance 1,0. Non déterministe — le même appel a rendu LIKELY_FALSE sans preuve sur "
        "trois tirages consécutifs. Ce test doit REDEVENIR vert une fois le seuil posé "
        "(cf. tofix2.md, partie B) ; ne pas affaiblir l'assertion pour le faire passer."
    ),
)
def test_verify_claim_ne_fabrique_pas_de_preuve_sur_une_affirmation_hors_corpus():
    """Sur une affirmation sans aucun rapport avec le corpus, FAISS remonte quand même
    ses `top_k` voisins (aucun seuil de distance — cf. point 10 de tofix.md). Le
    retriever ne doit alors produire NI preuve citée, NI verdict prétendant que FEVER
    a tranché.

    Le modèle garde le droit d'avoir une conviction issue de sa connaissance interne
    (`LIKELY_TRUE` / `LIKELY_FALSE` / `I_DONT_KNOWN`) : c'est ce que le prompt lui
    demande, et l'écraser était le bug corrigé au point 2. Ce qui reste interdit, c'est
    de présenter cette conviction comme une preuve documentaire."""
    retriever = RagRetriever(llm_client=OllamaClient())
    claim = Claim(id="c2", text="Xyzzy qwerty plugh zzzz asdf dvd dfvdv dvdv dvdv.", source_answer="...")
    result = retriever.verify_claim(claim)
    assert isinstance(result, RagVerdict)
    assert result.verdict not in (RagJudgment.FEVER_CONFIRMS, RagJudgment.FEVER_REFUTES)
    assert result.evidence is None
