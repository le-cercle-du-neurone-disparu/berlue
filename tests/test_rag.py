"""Test de contrat pour `berlue.rag.retriever.verify_claim` -> `RagVerdict`."""

import pytest

from berlue.core.schemas import Claim, RagJudgment, RagVerdict
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


def test_une_reponse_illisible_est_une_panne_pas_une_ignorance():
    """Ne pas savoir est un jugement que la fusion combine avec SelfCheck ; ne pas
    comprendre la réponse du RAG est une défaillance, et le pipeline doit annoncer
    une erreur. Les confondre faisait conclure « incertain » sur une panne."""
    from unittest.mock import MagicMock

    from berlue.core.schemas import Claim, PipelineResult, Verdict
    from berlue.pipeline.fusion import do_fusion
    from berlue.pipeline.hurlu_berlu import HurluBerlu
    from berlue.rag.retriever import RagPanne

    retriever = MagicMock()
    retriever.verify_claim.side_effect = RagPanne("réponse inexploitable")
    pipeline = HurluBerlu(llm_client=MagicMock(), llm_extract=MagicMock(), retriever=retriever)

    resultat = PipelineResult(
        question="Q", raw_answer="A", claims=[Claim(id="c1", text="Une affirmation.", source_answer="A")]
    )
    resultat = do_fusion(pipeline.evaluate_rag(resultat))

    assert resultat.panne is not None
    assert resultat.fused_verdicts[0].verdict == Verdict.PANNE


def test_un_rag_qui_ne_sait_pas_ne_declenche_pas_de_panne():
    from unittest.mock import MagicMock

    from berlue.core.schemas import Claim, PipelineResult, Verdict
    from berlue.pipeline.fusion import do_fusion
    from berlue.pipeline.hurlu_berlu import HurluBerlu

    retriever = MagicMock()
    retriever.verify_claim.return_value = RagVerdict(
        claim_id="c1", verdict=RagJudgment.I_DONT_KNOWN, confidence=0.0, evidence=None
    )
    pipeline = HurluBerlu(llm_client=MagicMock(), llm_extract=MagicMock(), retriever=retriever)

    resultat = PipelineResult(
        question="Q", raw_answer="A", claims=[Claim(id="c1", text="Une affirmation.", source_answer="A")]
    )
    resultat = do_fusion(pipeline.evaluate_rag(resultat))

    assert resultat.panne is None
    assert resultat.fused_verdicts[0].verdict != Verdict.PANNE


def test_une_seule_affirmation_en_panne_invalide_la_question():
    """Les verdicts restants porteraient sur une analyse partielle sans que rien ne
    le signale à la lecture."""
    from unittest.mock import MagicMock

    from berlue.core.schemas import Claim, PipelineResult, Verdict
    from berlue.pipeline.fusion import do_fusion
    from berlue.pipeline.hurlu_berlu import HurluBerlu
    from berlue.rag.retriever import RagPanne

    retriever = MagicMock()
    retriever.verify_claim.side_effect = [
        RagVerdict(claim_id="c1", verdict=RagJudgment.LIKELY_TRUE, confidence=0.9, evidence=None),
        RagPanne("réponse inexploitable"),
    ]
    pipeline = HurluBerlu(llm_client=MagicMock(), llm_extract=MagicMock(), retriever=retriever)

    resultat = PipelineResult(
        question="Q",
        raw_answer="A",
        claims=[Claim(id="c1", text="Une.", source_answer="A"), Claim(id="c2", text="Deux.", source_answer="A")],
    )
    resultat = do_fusion(pipeline.evaluate_rag(resultat))

    assert [v.verdict for v in resultat.fused_verdicts] == [Verdict.PANNE, Verdict.PANNE]
