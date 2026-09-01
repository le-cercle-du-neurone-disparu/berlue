"""Sérialisation des signaux du pipeline — tout ce que produit Berlue **avant** la
fusion : les affirmations extraites, les verdicts du RAG et les scores SelfCheck.

Ces signaux coûtent cher (un appel LLM par affirmation côté RAG, K échantillons côté
SelfCheck) alors que la fusion qui les consomme est une fonction pure et instantanée.
Les mettre en cache permet de rejouer la fusion avec d'autres `FUSION_*` sans
relancer le moindre modèle — cf. `docs/evaluation/storage.md`.

Le format est un dict JSON-sérialisable, stocké tel quel par les deux stores
(SQLite en local, Firestore sur GCP).
"""

from berlue.core.schemas import Claim, Evidence, PipelineResult, RagJudgment, RagVerdict, SelfCheckScore

# Incrémenter dès que la forme sérialisée change de façon incompatible : une entrée
# d'une autre version est ignorée (cache miss) plutôt que relue de travers.
SIGNALS_FORMAT_VERSION = 1


def _evidence_to_dict(evidence: Evidence | None) -> dict | None:
    if evidence is None:
        return None
    return {"text": evidence.text, "source": evidence.source, "similarity_score": evidence.similarity_score}


def _evidence_from_dict(data: dict | None) -> Evidence | None:
    if data is None:
        return None
    return Evidence(text=data["text"], source=data["source"], similarity_score=data["similarity_score"])


def signals_to_dict(result: PipelineResult) -> dict:
    """Extrait de `result` ce dont `do_fusion` a besoin, et rien d'autre.

    Les échantillons SelfCheck bruts ne sont volontairement pas stockés : la fusion
    ne lit que le `divergence_score`, et les conserver multiplierait la taille du
    cache par le nombre d'échantillons sans rien apporter au rejeu.
    """
    return {
        "format_version": SIGNALS_FORMAT_VERSION,
        "raw_answer": result.raw_answer,
        "panne": result.panne,
        "claims": [{"id": c.id, "text": c.text} for c in result.claims],
        "rag_scores": [
            {
                "claim_id": r.claim_id,
                "verdict": r.verdict.value,
                "confidence": r.confidence,
                "evidence": _evidence_to_dict(r.evidence),
            }
            for r in result.rag_scores
        ],
        "selfcheck_scores": [
            {"claim_id": s.claim_id, "divergence_score": s.divergence_score, "confidence": s.confidence}
            for s in result.selfcheck_scores
        ],
    }


def signals_from_dict(question: str, data: dict) -> PipelineResult:
    """Reconstruit un `PipelineResult` prêt à passer dans `do_fusion`.

    `source_answer` des affirmations est repris de `raw_answer` : le champ n'est lu
    par aucune étape en aval de l'extraction, mais le contrat de `Claim` l'exige.
    """
    raw_answer = data["raw_answer"]
    return PipelineResult(
        question=question,
        raw_answer=raw_answer,
        panne=data.get("panne"),
        claims=[Claim(id=c["id"], text=c["text"], source_answer=raw_answer) for c in data["claims"]],
        rag_scores=[
            RagVerdict(
                claim_id=r["claim_id"],
                verdict=RagJudgment(r["verdict"]),
                confidence=r["confidence"],
                evidence=_evidence_from_dict(r["evidence"]),
            )
            for r in data["rag_scores"]
        ],
        selfcheck_scores=[
            SelfCheckScore(
                claim_id=s["claim_id"],
                divergence_score=s["divergence_score"],
                confidence=s["confidence"],
            )
            for s in data["selfcheck_scores"]
        ],
    )
