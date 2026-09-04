"""Test de contrat pour `berlue.rag.retriever.verify_claim` -> `RagVerdict`."""

import json
import threading
import time

import pytest

from berlue.core.schemas import Claim, Generation, RagJudgment, RagOutcome, RagVerdict
from berlue.llm.client import OllamaClient
from berlue.rag.retriever import RagRetriever, _premier_objet_json


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


# --- Extraction de l'objet JSON de la réponse du modèle ------------------------


@pytest.mark.parametrize(
    ("nom", "reponse", "attendu"),
    [
        (
            "objet seul",
            '{"verdict": "LIKELY_TRUE", "confidence": 0.8}',
            {"verdict": "LIKELY_TRUE", "confidence": 0.8},
        ),
        (
            # Le cas observé en production : llama3.1:8b enchaînait sur un second
            # exemple. La capture allant jusqu'au dernier `}` contenait alors deux
            # valeurs, et le verdict — pourtant bien formé — était perdu.
            "objet suivi d'un second",
            '{"verdict": "LIKELY_TRUE", "confidence": 0.8}\n\n{"verdict": "I_DONT_KNOW"}',
            {"verdict": "LIKELY_TRUE", "confidence": 0.8},
        ),
        (
            "objet suivi de bavardage",
            '{"verdict": "I_DONT_KNOW", "confidence": 0.0}\nNote: based on the excerpts.',
            {"verdict": "I_DONT_KNOW", "confidence": 0.0},
        ),
        (
            "objet imbriqué : ne doit pas être tronqué au premier `}`",
            '{"detail": {"k": 1}, "verdict": "FEVER_CONFIRMS"} trailing',
            {"detail": {"k": 1}, "verdict": "FEVER_CONFIRMS"},
        ),
        ("aucun objet", "I cannot answer that.", {}),
    ],
)
def test_premier_objet_json(nom, reponse, attendu):
    objet = _premier_objet_json(reponse)
    assert objet == attendu


# --- Récupération d'une réponse tronquée ---------------------------------------
# Une génération peut s'arrêter en cours : plafond de tokens, fenêtre de contexte
# saturée. Le verdict est alors complet mais l'objet n'est pas refermé. Tout jeter
# faisait conclure « pas assez d'infos » là où le modèle avait tranché — observé en
# conditions réelles sur trois affirmations d'affilée.


@pytest.mark.parametrize(
    ("nom", "reponse", "verdict_attendu"),
    [
        (
            "tronqué juste après la confiance",
            '{\n "reasoning": "x",\n "used_evidence_index": 2,\n "verdict": "FEVER_REFUTES",\n "confidence": 0.99',
            "FEVER_REFUTES",
        ),
        (
            "tronqué au milieu d'une clé",
            '{\n "reasoning": "x",\n "verdict": "LIKELY_FALSE",\n "confid',
            "LIKELY_FALSE",
        ),
        (
            "virgule finale laissée par la coupure",
            '{\n "verdict": "LIKELY_TRUE",\n "confidence": 0.8,',
            "LIKELY_TRUE",
        ),
    ],
)
def test_recupere_un_verdict_dans_une_reponse_tronquee(nom, reponse, verdict_attendu):
    assert _premier_objet_json(reponse).get("verdict") == verdict_attendu


def test_une_reponse_coupee_avant_le_verdict_ne_donne_pas_de_verdict():
    """On ne devine pas : coupée trop tôt, la réponse ne porte aucun verdict et le
    pipeline doit conclure à l'ignorance, pas inventer une classification."""
    assert _premier_objet_json('{\n "reasoning": "Excerpt 0 is about').get("verdict") is None


def test_la_recuperation_ne_change_rien_a_une_reponse_complete():
    complet = '{"verdict": "FEVER_CONFIRMS", "confidence": 1.0, "used_evidence_index": 0}'
    assert _premier_objet_json(complet) == {"verdict": "FEVER_CONFIRMS", "confidence": 1.0, "used_evidence_index": 0}


# --- Panne du RAG contre ignorance du RAG --------------------------------------


def _fusion_depuis_le_rag(retriever, claims):
    """Assemble un `PipelineResult` à partir de la seule branche RAG, puis fusionne —
    la branche SelfCheck est absente, son signal est neutre par défaut."""
    from berlue.core.schemas import PipelineResult
    from berlue.pipeline.fusion import do_fusion

    outcome = retriever.verify_claims(claims)
    return do_fusion(
        PipelineResult(
            question="Q",
            raw_answer="A",
            claims=claims,
            rag_scores=outcome.verdicts,
            rag_traces=outcome.traces,
            panne=outcome.panne,
        )
    )


def test_une_reponse_illisible_est_une_panne_pas_une_ignorance():
    """Ne pas savoir est un jugement que la fusion combine avec SelfCheck ; ne pas
    comprendre la réponse du RAG est une défaillance, et le pipeline doit annoncer
    une erreur. Les confondre faisait conclure « incertain » sur une panne."""
    from berlue.core.schemas import Verdict

    class ClientEnEchec:
        """Ce que lève `OllamaClient.generate_detail` quand l'appel échoue."""

        def generate_detail(self, prompt, temperature=None, num_predict=None):
            raise RuntimeError("Erreur interne Ollama : modèle introuvable")

    claims = [Claim(id="c1", text="Une affirmation.", source_answer="A")]
    resultat = _fusion_depuis_le_rag(_retriever_sans_index(ClientEnEchec()), claims)

    assert resultat.panne is not None
    assert resultat.fused_verdicts[0].verdict == Verdict.PANNE


def test_un_rag_qui_ne_sait_pas_ne_declenche_pas_de_panne():
    from berlue.core.schemas import Verdict

    class ClientQuiNeSaitPas:
        def generate_detail(self, prompt, temperature=None, num_predict=None):
            return Generation(
                text=json.dumps({"verdict": "I_DONT_KNOW", "confidence": 0.0}), modele="stub", secondes=0.0
            )

    claims = [Claim(id="c1", text="Une affirmation.", source_answer="A")]
    resultat = _fusion_depuis_le_rag(_retriever_sans_index(ClientQuiNeSaitPas()), claims)

    assert resultat.panne is None
    assert resultat.fused_verdicts[0].verdict != Verdict.PANNE


def test_une_seule_affirmation_en_panne_invalide_la_question():
    """Les verdicts restants porteraient sur une analyse partielle sans que rien ne
    le signale à la lecture."""
    from berlue.core.schemas import Verdict

    class ClientEnEchecSurC2:
        def generate_detail(self, prompt, temperature=None, num_predict=None):
            if "Deux." in prompt:
                raise RuntimeError("Erreur interne Ollama")
            return Generation(
                text=json.dumps({"verdict": "LIKELY_TRUE", "confidence": 0.9}), modele="stub", secondes=0.0
            )

    claims = [
        Claim(id="c1", text="Une.", source_answer="A"),
        Claim(id="c2", text="Deux.", source_answer="A"),
    ]
    resultat = _fusion_depuis_le_rag(_retriever_sans_index(ClientEnEchecSurC2()), claims)

    assert [v.verdict for v in resultat.fused_verdicts] == [Verdict.PANNE, Verdict.PANNE]


# --- Vérification en parallèle -------------------------------------------------


def _retriever_sans_index(llm_client, evidences_par_claim=None):
    """`RagRetriever` sans son index FAISS ni son modèle d'embedding (coûteux à
    charger, et sans objet ici) : seule la logique de vérification est testée."""
    retriever = RagRetriever.__new__(RagRetriever)
    retriever.llm_client = llm_client
    retriever.retrieve = lambda claim, top_k=5: (evidences_par_claim or {}).get(
        claim.id, [{"text": "un extrait", "label": "SUPPORTS", "distance": 0.1, "evidence_url": []}]
    )
    return retriever


class ClientLentParClaim:
    """Client dont chaque réponse — et chaque métadonnée — porte l'identifiant de
    l'affirmation traitée, avec un délai variable pour forcer l'entrelacement."""

    def __init__(self, delais: dict[str, float]):
        self.delais = delais
        self.threads: set[str] = set()

    def generate_detail(self, prompt: str, temperature=None, num_predict=None) -> Generation:
        claim_id = next(cid for cid in self.delais if cid in prompt)
        self.threads.add(threading.current_thread().name)
        time.sleep(self.delais[claim_id])
        return Generation(
            text=json.dumps({"verdict": "LIKELY_TRUE", "confidence": 0.8, "reasoning": claim_id}),
            modele=f"modele-{claim_id}",
            secondes=self.delais[claim_id],
            tokens=42,
        )


def test_verify_claims_rend_verdicts_et_traces_dans_l_ordre_des_affirmations():
    """L'ordre est un contrat : la fusion apparie par identifiant, mais le champ
    `debug` de l'API et les journaux se lisent dans l'ordre des affirmations."""
    claims = [Claim(id=f"c{i}", text=f"Affirmation c{i}.", source_answer="...") for i in range(1, 4)]
    # Délais décroissants : l'ordre d'achèvement est l'inverse de l'ordre d'entrée.
    client = ClientLentParClaim({"c1": 0.15, "c2": 0.10, "c3": 0.01})
    retriever = _retriever_sans_index(client)

    outcome = retriever.verify_claims(claims, max_workers=3)

    assert [v.claim_id for v in outcome.verdicts] == ["c1", "c2", "c3"]
    assert [t["claim_id"] for t in outcome.traces] == ["c1", "c2", "c3"]
    assert len(client.threads) > 1, "les vérifications ne se sont pas réparties sur plusieurs threads"


def test_les_metadonnees_de_generation_ne_se_croisent_pas_entre_threads():
    """Chaque trace doit porter les métadonnées de SON appel.

    Tant qu'elles vivaient sur le client (`derniere_generation`), deux
    vérifications concurrentes sur un même client lisaient celles du dernier
    appel terminé — donc, la moitié du temps, celles d'une autre affirmation.
    """
    claims = [Claim(id=f"c{i}", text=f"Affirmation c{i}.", source_answer="...") for i in range(1, 5)]
    client = ClientLentParClaim({"c1": 0.12, "c2": 0.02, "c3": 0.08, "c4": 0.04})
    retriever = _retriever_sans_index(client)

    outcome = retriever.verify_claims(claims, max_workers=4)

    for trace in outcome.traces:
        assert trace["generation"]["modele"] == f"modele-{trace['claim_id']}"
        assert trace["reasoning"] == trace["claim_id"]


def test_une_panne_sur_une_seule_affirmation_invalide_toute_la_question():
    """Une réponse illisible sur une affirmation vide verdicts ET traces : les
    verdicts restants porteraient sur une analyse partielle sans le signaler."""

    class ClientEnEchecSurC2:
        def generate_detail(self, prompt: str, temperature=None, num_predict=None) -> Generation:
            if "c2" in prompt:
                raise RuntimeError("Erreur interne Ollama")
            return Generation(
                text=json.dumps({"verdict": "LIKELY_TRUE", "confidence": 0.8}), modele="stub", secondes=0.0
            )

    claims = [Claim(id=f"c{i}", text=f"Affirmation c{i}.", source_answer="...") for i in range(1, 4)]
    retriever = _retriever_sans_index(ClientEnEchecSurC2())

    outcome = retriever.verify_claims(claims, max_workers=3)

    assert outcome.panne is not None
    assert "c2" in outcome.panne
    assert outcome.verdicts == []
    assert outcome.traces == []


def test_verify_claims_sans_affirmation_ne_lance_aucun_appel():
    retriever = _retriever_sans_index(ClientLentParClaim({}))

    outcome = retriever.verify_claims([], max_workers=4)

    assert outcome == RagOutcome()
