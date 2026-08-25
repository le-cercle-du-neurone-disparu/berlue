"""Fusion du verdict RAG et du score SelfCheckGPT — hors de rag/ et selfcheck/ pour
ne pas les coupler l'un à l'autre."""

from berlue.core.schemas import Claim, FusedVerdict, RagVerdict, SelfCheckScore
from berlue.params import FUSION_WEIGHT_RAG, FUSION_WEIGHT_SELFCHECK


def fuse(
    claim: Claim,
    rag_verdict: RagVerdict | None,
    selfcheck_score: SelfCheckScore,
    weight_rag: float = FUSION_WEIGHT_RAG,
    weight_selfcheck: float = FUSION_WEIGHT_SELFCHECK,
) -> FusedVerdict:
    """Combine verdict RAG et score SelfCheckGPT en un verdict final. Doit gérer
    `rag_verdict=None`."""
    # TODO(fusion)
    raise NotImplementedError
