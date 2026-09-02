"""Tests de la fusion RAG + SelfCheck.

Le tableau de référence de `claude-doc/specification-fusion-2026-09-02.md` est rejoué
ligne par ligne dans `test_tableau_de_reference` : chaque cas y est un couple
(signal RAG, divergence SelfCheck) attendu vers un (verdict, fondement, confiance).

Signaux synthétiques uniquement — aucun appel à Ollama ni à FAISS, donc ces tests
tournent dans la lane CI rapide.
"""

import pytest

from berlue import params
from berlue.core.schemas import (
    Claim,
    Evidence,
    Fondement,
    PipelineResult,
    RagJudgment,
    RagVerdict,
    SelfCheckScore,
    Verdict,
)
from berlue.pipeline.fusion import do_fusion, rag_belief, selfcheck_belief


def _result(rag: RagVerdict | None = None, divergence: float | None = None, panne: str | None = None):
    """Un PipelineResult à une seule affirmation, avec les signaux demandés."""
    claim = Claim(id="c1", text="Une affirmation.", source_answer="...")
    result = PipelineResult(question="q ?", raw_answer="r", claims=[claim], panne=panne)
    if rag is not None:
        result.rag_scores.append(rag)
    if divergence is not None:
        result.selfcheck_scores.append(
            SelfCheckScore(claim_id="c1", divergence_score=divergence, confidence=1.0 - divergence)
        )
    return result


def _rag(judgment: RagJudgment, confidence: float, evidence: Evidence | None = None) -> RagVerdict:
    return RagVerdict(claim_id="c1", verdict=judgment, confidence=confidence, evidence=evidence)


def _fuse(rag=None, divergence=None, panne=None):
    return do_fusion(_result(rag, divergence, panne)).fused_verdicts[0]


# --- Normalisation des deux signaux ------------------------------------------


def test_rag_belief_est_neutre_sans_verdict():
    assert rag_belief(None) == 0.5
    assert rag_belief(_rag(RagJudgment.I_DONT_KNOWN, 0.0)) == 0.5


def test_rag_belief_est_directionnel_et_proportionnel_a_la_confiance():
    assert rag_belief(_rag(RagJudgment.LIKELY_TRUE, 1.0)) == 1.0
    assert rag_belief(_rag(RagJudgment.LIKELY_TRUE, 0.5)) == 0.75
    assert rag_belief(_rag(RagJudgment.LIKELY_FALSE, 1.0)) == 0.0
    assert rag_belief(_rag(RagJudgment.LIKELY_FALSE, 0.5)) == 0.25


def test_selfcheck_belief_est_neutre_au_point_neutre():
    assert selfcheck_belief(0.5) == pytest.approx(0.5)


def test_selfcheck_belief_decroit_avec_la_divergence():
    assert selfcheck_belief(0.0) == pytest.approx(1.0)
    assert selfcheck_belief(1.0) == pytest.approx(0.0)
    valeurs = [selfcheck_belief(d / 10) for d in range(11)]
    assert valeurs == sorted(valeurs, reverse=True)


# --- R1 : panne ---------------------------------------------------------------


def test_panne_ne_rend_aucun_verdict_meme_avec_des_signaux_exploitables():
    """Un signal RAG franc ne doit pas sauver une réponse dont un composant a échoué :
    le résultat est incomplet, la question est à rejouer."""
    fused = _fuse(rag=_rag(RagJudgment.LIKELY_TRUE, 1.0), divergence=0.05, panne="Ollama injoignable")
    assert fused.verdict == Verdict.PANNE
    assert fused.confidence == 0.0
    assert fused.fondement == Fondement.AUCUN
    assert "Ollama injoignable" in fused.explanation


def test_panne_marque_toutes_les_affirmations_pas_seulement_la_fautive():
    claims = [Claim(id=f"c{i}", text=f"Affirmation {i}.", source_answer="...") for i in range(3)]
    result = PipelineResult(question="q ?", raw_answer="r", claims=claims, panne="RAG en échec")
    fused = do_fusion(result).fused_verdicts
    assert len(fused) == 3
    assert all(f.verdict == Verdict.PANNE for f in fused)


# --- R2 : FEVER prime ---------------------------------------------------------


def test_preuve_fever_ignore_selfcheck():
    """La confiance rendue est celle du RAG, quelle que soit la stabilité du modèle."""
    coherent = _fuse(rag=_rag(RagJudgment.FEVER_CONFIRMS, 0.95), divergence=0.05)
    incoherent = _fuse(rag=_rag(RagJudgment.FEVER_CONFIRMS, 0.95), divergence=0.85)
    assert coherent.verdict == incoherent.verdict == Verdict.SUPPORTED
    assert coherent.confidence == incoherent.confidence == pytest.approx(0.95)
    assert coherent.fondement == Fondement.PREUVE_FEVER


def test_preuve_fever_porte_son_evidence():
    evidence = Evidence(text="Un extrait FEVER.", source="Wikipedia", similarity_score=0.9)
    fused = _fuse(rag=_rag(RagJudgment.FEVER_REFUTES, 0.99, evidence), divergence=0.5)
    assert fused.verdict == Verdict.CONTRADICTED
    assert fused.evidence is evidence


def test_une_conviction_ne_porte_jamais_d_evidence():
    """Seule une preuve FEVER est une preuve — cf. le champ `fondement`."""
    evidence = Evidence(text="Un extrait.", source="Wikipedia", similarity_score=0.9)
    fused = _fuse(rag=_rag(RagJudgment.LIKELY_TRUE, 1.0, evidence), divergence=0.05)
    assert fused.fondement == Fondement.CONVICTION
    assert fused.evidence is None


# --- R3 : le RAG ne conclut pas, SelfCheck décide seul aux extrêmes -----------


@pytest.mark.parametrize("divergence", [0.25, 0.5, 0.75])
def test_selfcheck_moyen_ne_tranche_pas(divergence):
    """Une divergence moyenne peut venir de la créativité, d'une omission ou des
    températures étalées du protocole : elle ne prouve rien."""
    fused = _fuse(rag=_rag(RagJudgment.I_DONT_KNOWN, 0.0), divergence=divergence)
    assert fused.verdict == Verdict.NOT_ENOUGH_INFO
    assert fused.confidence == 0.0
    assert fused.fondement == Fondement.AUCUN


def test_selfcheck_franchement_stable_valide_par_conviction():
    fused = _fuse(rag=_rag(RagJudgment.I_DONT_KNOWN, 0.0), divergence=0.05)
    assert fused.verdict == Verdict.SUPPORTED
    assert fused.fondement == Fondement.CONVICTION


def test_selfcheck_franchement_instable_contredit_par_conviction():
    fused = _fuse(rag=_rag(RagJudgment.I_DONT_KNOWN, 0.0), divergence=0.95)
    assert fused.verdict == Verdict.CONTRADICTED
    assert fused.fondement == Fondement.CONVICTION


def test_une_conviction_d_un_seul_signal_est_decotee():
    """Sans décote, une conviction SelfCheck seule ressortirait plus confiante qu'une
    conviction corroborée par le RAG."""
    seul = _fuse(rag=_rag(RagJudgment.I_DONT_KNOWN, 0.0), divergence=0.05)
    corrobore = _fuse(rag=_rag(RagJudgment.LIKELY_TRUE, 1.0), divergence=0.05)
    assert seul.confidence < corrobore.confidence


def test_conviction_rag_trop_faible_retombe_dans_la_bande_neutre():
    """Un LIKELY_TRUE à confiance 0.10 (rag_belief 0.55) n'est pas plus concluant qu'un
    « je ne sais pas » : c'est SelfCheck qui décide."""
    fused = _fuse(rag=_rag(RagJudgment.LIKELY_TRUE, 0.10), divergence=0.5)
    assert fused.verdict == Verdict.NOT_ENOUGH_INFO
    assert fused.fondement == Fondement.AUCUN


# --- R4 / R5 : accord et désaccord --------------------------------------------


def test_accord_tranche_sans_arbitrage():
    fused = _fuse(rag=_rag(RagJudgment.LIKELY_FALSE, 1.0), divergence=0.90)
    assert fused.verdict == Verdict.CONTRADICTED
    assert fused.confidence > 0.9


def test_hallucination_stable_est_contredite():
    """Le cas d'usage du projet : le RAG est catégorique sur la fausseté, le modèle est
    parfaitement stable. La stabilité ne doit pas annuler le jugement."""
    fused = _fuse(rag=_rag(RagJudgment.LIKELY_FALSE, 1.0), divergence=0.05)
    assert fused.verdict == Verdict.CONTRADICTED


def test_contredit_est_atteignable_a_coherence_elevee():
    """Régression de fond : l'ancienne formule symétrique rendait CONTRADICTED
    mathématiquement inatteignable dès que la cohérence dépassait 0.8."""
    verdicts = {_fuse(rag=_rag(RagJudgment.LIKELY_FALSE, 1.0), divergence=d / 100).verdict for d in range(0, 21)}
    assert Verdict.CONTRADICTED in verdicts


def test_incoherence_pese_plus_que_coherence():
    """Le poids de SelfCheck est asymétrique : se contredire n'a qu'une lecture, être
    cohérent en a deux."""
    conteste_par_incoherence = _fuse(rag=_rag(RagJudgment.LIKELY_TRUE, 1.0), divergence=0.90)
    conteste_par_coherence = _fuse(rag=_rag(RagJudgment.LIKELY_FALSE, 1.0), divergence=0.10)
    # Le RAG est catégorique des deux côtés, mais seule l'incohérence renverse le verdict.
    assert conteste_par_incoherence.verdict == Verdict.NOT_ENOUGH_INFO
    assert conteste_par_coherence.verdict == Verdict.CONTRADICTED


# --- Confiance ----------------------------------------------------------------


def test_un_indecis_n_affirme_rien_donc_ne_porte_aucune_confiance():
    """L'ancienne formule faisait ressortir « aucune information nulle part » à 1.00."""
    fused = _fuse(rag=_rag(RagJudgment.I_DONT_KNOWN, 0.0), divergence=0.5)
    assert fused.verdict == Verdict.NOT_ENOUGH_INFO
    assert fused.confidence == 0.0


@pytest.mark.parametrize(
    "judgment,confidence,divergence",
    [
        (RagJudgment.FEVER_CONFIRMS, 0.95, 0.05),
        (RagJudgment.LIKELY_TRUE, 1.0, 0.90),
        (RagJudgment.LIKELY_FALSE, 0.5, 0.05),
        (RagJudgment.I_DONT_KNOWN, 0.0, 0.95),
    ],
)
def test_la_confiance_reste_bornee(judgment, confidence, divergence):
    fused = _fuse(rag=_rag(judgment, confidence), divergence=divergence)
    assert 0.0 <= fused.confidence <= 1.0


# --- Idempotence --------------------------------------------------------------


def test_do_fusion_est_idempotente():
    """Un double appel ne doit pas dupliquer les verdicts."""
    result = _result(_rag(RagJudgment.LIKELY_TRUE, 1.0), 0.05)
    do_fusion(result)
    do_fusion(result)
    assert len(result.fused_verdicts) == 1


# --- Tableau de référence de la spécification ---------------------------------

# (judgment, confiance RAG, divergence, panne) -> (verdict, fondement, confiance)
TABLEAU = [
    (RagJudgment.FEVER_CONFIRMS, 0.95, 0.05, None, Verdict.SUPPORTED, Fondement.PREUVE_FEVER, 0.95),
    (RagJudgment.FEVER_CONFIRMS, 0.95, 0.85, None, Verdict.SUPPORTED, Fondement.PREUVE_FEVER, 0.95),
    (RagJudgment.FEVER_REFUTES, 0.99, 0.85, None, Verdict.CONTRADICTED, Fondement.PREUVE_FEVER, 0.99),
    (RagJudgment.I_DONT_KNOWN, 0.00, 0.05, None, Verdict.SUPPORTED, Fondement.CONVICTION, 0.77),
    (RagJudgment.I_DONT_KNOWN, 0.00, 0.15, None, Verdict.SUPPORTED, Fondement.CONVICTION, 0.71),
    (RagJudgment.I_DONT_KNOWN, 0.00, 0.25, None, Verdict.NOT_ENOUGH_INFO, Fondement.AUCUN, 0.00),
    (RagJudgment.I_DONT_KNOWN, 0.00, 0.50, None, Verdict.NOT_ENOUGH_INFO, Fondement.AUCUN, 0.00),
    (RagJudgment.I_DONT_KNOWN, 0.00, 0.75, None, Verdict.NOT_ENOUGH_INFO, Fondement.AUCUN, 0.00),
    (RagJudgment.I_DONT_KNOWN, 0.00, 0.85, None, Verdict.CONTRADICTED, Fondement.CONVICTION, 0.71),
    (RagJudgment.I_DONT_KNOWN, 0.00, 0.95, None, Verdict.CONTRADICTED, Fondement.CONVICTION, 0.77),
    (RagJudgment.LIKELY_TRUE, 0.10, 0.10, None, Verdict.SUPPORTED, Fondement.CONVICTION, 0.74),
    (RagJudgment.LIKELY_TRUE, 0.10, 0.50, None, Verdict.NOT_ENOUGH_INFO, Fondement.AUCUN, 0.00),
    (RagJudgment.LIKELY_FALSE, 0.10, 0.90, None, Verdict.CONTRADICTED, Fondement.CONVICTION, 0.74),
    (RagJudgment.LIKELY_TRUE, 1.00, 0.05, None, Verdict.SUPPORTED, Fondement.CONVICTION, 0.98),
    (RagJudgment.LIKELY_TRUE, 1.00, 0.50, None, Verdict.SUPPORTED, Fondement.CONVICTION, 0.79),
    (RagJudgment.LIKELY_TRUE, 1.00, 0.90, None, Verdict.NOT_ENOUGH_INFO, Fondement.CONVICTION, 0.00),
    (RagJudgment.LIKELY_TRUE, 0.60, 0.90, None, Verdict.NOT_ENOUGH_INFO, Fondement.CONVICTION, 0.00),
    (RagJudgment.LIKELY_FALSE, 1.00, 0.90, None, Verdict.CONTRADICTED, Fondement.CONVICTION, 0.94),
    (RagJudgment.LIKELY_FALSE, 1.00, 0.05, None, Verdict.CONTRADICTED, Fondement.CONVICTION, 0.61),
    (RagJudgment.LIKELY_FALSE, 0.50, 0.05, None, Verdict.NOT_ENOUGH_INFO, Fondement.CONVICTION, 0.00),
    (RagJudgment.LIKELY_TRUE, 1.00, None, "panne SelfCheck", Verdict.PANNE, Fondement.AUCUN, 0.00),
    (None, None, 0.90, "panne RAG", Verdict.PANNE, Fondement.AUCUN, 0.00),
]


@pytest.mark.parametrize("ligne", TABLEAU, ids=[f"L{i}" for i in range(1, len(TABLEAU) + 1)])
def test_tableau_de_reference(ligne):
    judgment, rag_confidence, divergence, panne, verdict, fondement, confidence = ligne
    rag = _rag(judgment, rag_confidence) if judgment is not None else None
    fused = _fuse(rag=rag, divergence=divergence, panne=panne)
    assert fused.verdict == verdict
    assert fused.fondement == fondement
    assert fused.confidence == pytest.approx(confidence, abs=0.005)


# --- La contrainte qui borne le poids à décharge ------------------------------


def test_la_decharge_ne_peut_pas_annuler_un_jugement_categorique():
    """Garde la contrainte qui borne `FUSION_WEIGHT_SELFCHECK_DECHARGE`.

    L'arbitrage vise un 50/50 entre la conviction du RAG et SelfCheck. Côté
    décharge, un 50/50 strict est impossible : pour qu'un RAG catégorique
    « c'est faux » reste CONTREDIT face à un modèle parfaitement stable —
    l'hallucination stable, le cas d'usage du projet — il faut

        (0·RAG + décharge·0,95) / (RAG + décharge) < FUSION_SEUIL_FAUX
        soit  décharge < 0,727 · RAG.

    Ce test échouera si quelqu'un relève la décharge au-delà, et c'est son rôle :
    la limite est arithmétique, pas esthétique.
    """
    plafond = 0.727 * params.FUSION_WEIGHT_RAG
    assert params.FUSION_WEIGHT_SELFCHECK_DECHARGE < plafond, (
        f"décharge={params.FUSION_WEIGHT_SELFCHECK_DECHARGE} dépasse le plafond {plafond:.3f} "
        f"imposé par FUSION_WEIGHT_RAG={params.FUSION_WEIGHT_RAG}"
    )
    # Et la conséquence concrète, indépendamment de la formule ci-dessus.
    assert _fuse(rag=_rag(RagJudgment.LIKELY_FALSE, 1.0), divergence=0.05).verdict == Verdict.CONTRADICTED


def test_influence_globale_de_selfcheck_proche_de_la_moitie():
    """Le 50/50 visé est GLOBAL, pas direction par direction : SelfCheck étant bridé
    quand il disculpe (cf. test ci-dessus), son poids à charge compense au-dessus de
    50 % pour que la moyenne des deux revienne à ~50."""
    r = params.FUSION_WEIGHT_RAG
    part_charge = params.FUSION_WEIGHT_SELFCHECK_CHARGE / (r + params.FUSION_WEIGHT_SELFCHECK_CHARGE)
    part_decharge = params.FUSION_WEIGHT_SELFCHECK_DECHARGE / (r + params.FUSION_WEIGHT_SELFCHECK_DECHARGE)
    moyenne = (part_charge + part_decharge) / 2
    assert 0.45 <= moyenne <= 0.55, f"influence moyenne de SelfCheck : {moyenne:.1%}"
    assert part_charge > 0.5, "le poids à charge doit compenser le bridage à décharge"
