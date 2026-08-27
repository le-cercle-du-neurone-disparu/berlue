"""Contrat interne entre les modules du pipeline (llm/, rag/, selfcheck/, fusion.py) —
distinct des schémas Pydantic HTTP de `berlue.api.schemas`.

Ne pas dupliquer ces classes ailleurs ; discuter en équipe avant d'y ajouter un champ.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Verdict(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    NOT_ENOUGH_INFO = "not_enough_info"


@dataclass
class Claim:
    """Une affirmation atomique extraite de la réponse du LLM. (llm/)"""

    id: str
    text: str
    source_answer: str  # la réponse brute du LLM dont l'affirmation est issue


@dataclass
class Evidence:
    """Une preuve récupérée dans le corpus FEVER pour une affirmation donnée. (rag/)"""

    text: str
    source: str  # ex. titre de la page Wikipedia FEVER
    similarity_score: float


@dataclass
class RagVerdict:
    """Sortie du module RAG inversé pour une affirmation. (rag/)"""

    claim_id: str
    verdict: Verdict
    confidence: float  # 0.0 - 1.0
    evidence: Evidence | None = None


@dataclass
class SelfCheckScore:
    """Sortie du module SelfCheckGPT pour une affirmation. (selfcheck/)"""

    claim_id: str
    divergence_score: float  # 0.0 (stable/cohérent) - 1.0 (très divergent)
    confidence: float  # 0.0 - 1.0, dérivé du divergence_score


@dataclass
class FusedVerdict:
    """Résultat final après fusion RAG + SelfCheckGPT, ce que l'UI affiche. (fusion.py -> app)"""

    claim_id: str
    claim_text: str
    verdict: Verdict
    confidence: float
    evidence: Evidence | None = None
    explanation: str = ""


@dataclass
class PipelineResult:
    """Résultat complet pour une question posée par l'utilisateur."""

    question: str
    raw_answer: str
    claims: list[Claim] = field(default_factory=list)
    fused_verdicts: list[FusedVerdict] = field(default_factory=list)
