"""Fusion du jugement RAG et du score SelfCheck en un verdict par affirmation.

Fonctionnel de référence : `claude-doc/specification-fusion-2026-09-02.md`. Chaque
ligne de son tableau comparatif correspond à un test de `tests/test_fusion.py`.

Deux idées portent le reste :

- Une preuve FEVER et une conviction ne se valent pas. Le verdict reste à trois
  valeurs pour que la matrice de confusion reste comparable à une vérité terrain, et
  c'est `FusedVerdict.fondement` qui porte la différence.
- SelfCheck mesure la stabilité du modèle, pas la vérité. Se contredire n'a qu'une
  lecture (le modèle ne sait pas) ; être cohérent en a deux (il sait, ou il se trompe
  avec constance) — une hallucination stable produit la même signature qu'une
  connaissance solide. D'où un poids asymétrique, et le fait que SelfCheck ne décide
  seul qu'aux extrêmes.
"""

import logging
from dataclasses import replace

from berlue.core.schemas import Fondement, FusedVerdict, PipelineResult, RagJudgment, RagVerdict, Verdict
from berlue.params import (
    FUSION_BANDE_RAG_MAX,
    FUSION_BANDE_RAG_MIN,
    FUSION_DECOTE_SIGNAL_SEUL,
    FUSION_DIVERGENCE_NEUTRE,
    FUSION_SELFCHECK_SEUIL_BAS,
    FUSION_SELFCHECK_SEUIL_HAUT,
    FUSION_SEUIL_FAUX,
    FUSION_SEUIL_VRAI,
    FUSION_WEIGHT_RAG,
    FUSION_WEIGHT_SELFCHECK_CHARGE,
    FUSION_WEIGHT_SELFCHECK_DECHARGE,
)

logger = logging.getLogger(__name__)

# Écart minimal à 0.5 pour qu'un signal soit considéré comme ayant une direction.
DEAD_ZONE = 0.10


def rag_belief(rag: RagVerdict | None) -> float:
    """Jugement RAG projeté sur l'axe faux <-> vrai : 0.0 franchement faux, 0.5 aucune
    idée, 1.0 franchement vrai."""
    if rag is None:
        return 0.5
    if rag.verdict == RagJudgment.LIKELY_TRUE:
        return 0.5 + (rag.confidence * 0.5)
    if rag.verdict == RagJudgment.LIKELY_FALSE:
        return 0.5 - (rag.confidence * 0.5)
    return 0.5


def selfcheck_belief(divergence: float) -> float:
    """Divergence SelfCheck projetée sur le même axe : deux droites qui se rejoignent
    à 0.5 au point neutre `FUSION_DIVERGENCE_NEUTRE`."""
    d0 = FUSION_DIVERGENCE_NEUTRE
    if divergence <= d0:
        return 0.5 + 0.5 * (d0 - divergence) / d0
    return 0.5 - 0.5 * (divergence - d0) / (1.0 - d0)


def _direction(belief: float) -> int:
    """+1 penche vers le vrai, -1 vers le faux, 0 trop proche du neutre pour dire."""
    if abs(belief - 0.5) < DEAD_ZONE:
        return 0
    return 1 if belief > 0.5 else -1


def _classify(score: float) -> Verdict:
    if score < FUSION_SEUIL_FAUX:
        return Verdict.CONTRADICTED
    if score > FUSION_SEUIL_VRAI:
        return Verdict.SUPPORTED
    return Verdict.NOT_ENOUGH_INFO


def _confidence(verdict: Verdict, score: float) -> float:
    """Confiance *dans le verdict rendu*. Un NOT_ENOUGH_INFO n'affirme rien : il n'y a
    rien dont être confiant."""
    if verdict == Verdict.SUPPORTED:
        return score
    if verdict == Verdict.CONTRADICTED:
        return 1.0 - score
    return 0.0


def fuse_claim(rag: RagVerdict | None, divergence: float) -> tuple[Verdict, float, Fondement, str]:
    """Applique les règles R2 à R5 à une affirmation (R1, la panne, est traitée en
    amont par `do_fusion` : elle ne dépend pas de l'affirmation).

    Retourne `(verdict, confiance, fondement, explication)`.
    """
    rag_judgment = rag.verdict if rag else RagJudgment.I_DONT_KNOWN
    sc_belief = selfcheck_belief(divergence)

    # --- R2 : FEVER a tranché. La base prime, SelfCheck n'entre pas dans le calcul.
    if rag_judgment == RagJudgment.FEVER_CONFIRMS:
        return (
            Verdict.SUPPORTED,
            rag.confidence,
            Fondement.PREUVE_FEVER,
            "L'affirmation est prouvée par la base FEVER.",
        )
    if rag_judgment == RagJudgment.FEVER_REFUTES:
        return (
            Verdict.CONTRADICTED,
            rag.confidence,
            Fondement.PREUVE_FEVER,
            "L'affirmation est contredite par la base FEVER.",
        )

    belief = rag_belief(rag)

    # --- R3 : le RAG ne conclut pas — soit I_DONT_KNOWN, soit une conviction trop
    # faible pour sortir de la bande neutre. SelfCheck décide alors seul, mais
    # uniquement si son signal est franc.
    if FUSION_BANDE_RAG_MIN <= belief <= FUSION_BANDE_RAG_MAX:
        if sc_belief > FUSION_SELFCHECK_SEUIL_HAUT:
            verdict = Verdict.SUPPORTED
            explanation = "Aucune preuve en base, mais le modèle est remarquablement stable sur ce point."
        elif sc_belief < FUSION_SELFCHECK_SEUIL_BAS:
            verdict = Verdict.CONTRADICTED
            explanation = "Aucune preuve en base, et le modèle se contredit lui-même : hallucination probable."
        else:
            return (
                Verdict.NOT_ENOUGH_INFO,
                0.0,
                Fondement.AUCUN,
                "Ni preuve en base, ni jugement RAG tranché, ni signal de cohérence franc.",
            )
        # Décotée : cette conviction ne repose que sur un signal.
        confidence = 0.5 + abs(sc_belief - 0.5) * FUSION_DECOTE_SIGNAL_SEUL
        return verdict, confidence, Fondement.CONVICTION, explanation

    # --- R4 / R5 : le RAG a une conviction, SelfCheck la corrobore ou la conteste.
    weight_sc = FUSION_WEIGHT_SELFCHECK_CHARGE if sc_belief < 0.5 else FUSION_WEIGHT_SELFCHECK_DECHARGE
    score = (FUSION_WEIGHT_RAG * belief + weight_sc * sc_belief) / (FUSION_WEIGHT_RAG + weight_sc)

    direction_rag = _direction(belief)
    if direction_rag != 0 and direction_rag == _direction(sc_belief):
        # R4 : accord. Deux signaux indépendants qui concordent tranchent sans arbitrage.
        verdict = Verdict.SUPPORTED if direction_rag > 0 else Verdict.CONTRADICTED
        explanation = "Aucune preuve en base, mais le jugement du modèle et sa cohérence interne concordent."
    else:
        # R5 : désaccord, on arbitre aux poids.
        verdict = _classify(score)
        explanation = (
            f"Aucune preuve en base ; jugement du modèle et cohérence interne divergent (score arbitré {score:.2f})."
        )

    return verdict, _confidence(verdict, score), Fondement.CONVICTION, explanation


def do_fusion(result: PipelineResult) -> PipelineResult:
    """Dernière étape du pipeline : statue sur chaque affirmation à partir du jugement
    RAG et du score SelfCheck.

    Rend un nouveau `PipelineResult` plutôt que d'affecter celui reçu, qui est figé.
    Fonction pure : deux appels sur la même entrée rendent la même chose, et l'entrée
    reste rejouable avec d'autres `FUSION_*`.
    """
    logger.debug("🧬 [Fusion] Synthèse de %d affirmation(s)...", len(result.claims))

    # --- R1 : un composant est en panne. On ne devine pas : aucun verdict n'est rendu,
    # pour aucune affirmation, et la question devra être rejouée entièrement.
    if result.panne:
        logger.warning("⚠️ [Fusion] Aucun verdict rendu, panne en amont : %s", result.panne)
        return replace(
            result,
            fused_verdicts=[
                FusedVerdict(
                    claim_id=claim.id,
                    claim_text=claim.text,
                    verdict=Verdict.PANNE,
                    confidence=0.0,
                    explanation=f"Aucun verdict : {result.panne}.",
                    fondement=Fondement.AUCUN,
                )
                for claim in result.claims
            ],
        )

    rag_by_claim = {v.claim_id: v for v in result.rag_scores}
    sc_by_claim = {s.claim_id: s for s in result.selfcheck_scores}

    fused_verdicts = []
    for claim in result.claims:
        rag = rag_by_claim.get(claim.id)
        sc = sc_by_claim.get(claim.id)
        # Pas de score SelfCheck pour cette affirmation : signal neutre, il ne peut ni
        # corroborer ni contester. Une vraie panne SelfCheck passe par `result.panne`.
        divergence = sc.divergence_score if sc else FUSION_DIVERGENCE_NEUTRE

        verdict, confidence, fondement, explanation = fuse_claim(rag, divergence)

        fused_verdicts.append(
            FusedVerdict(
                claim_id=claim.id,
                claim_text=claim.text,
                verdict=verdict,
                confidence=min(max(confidence, 0.0), 1.0),
                # Seule une preuve FEVER citée est une preuve : une conviction n'en a pas.
                evidence=rag.evidence if (rag and fondement == Fondement.PREUVE_FEVER) else None,
                explanation=explanation,
                fondement=fondement,
            )
        )

    return replace(result, fused_verdicts=fused_verdicts)
