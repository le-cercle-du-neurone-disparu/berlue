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


class RagJudgment(StrEnum):
    FEVER_CONFIRMS = "proven_true"      # FEVER prouve que c'est vrai
    FEVER_REFUTES = "proven_false"    # FEVER prouve que c'est faux
    LIKELY_TRUE = "likely_true"      # rien dans FEVER, mais persuadé vrai
    LIKELY_FALSE = "likely_false"    # rien dans FEVER, mais persuadé faux
    I_DONT_KNOWN = "unknown"

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

    # --- 1. L'entrée et la base ---
    question: str
    raw_answer: str

    # --- 2. L'extraction ---
    claims: list[Claim] = field(default_factory=list)

    # --- 3. Branche A : SelfCheckGPT (Cohérence interne) ---
    samples: list[str] = field(default_factory=list)
    selfcheck_scores: list[SelfCheckScore] = field(default_factory=list)

    # --- 4. Branche B : RAG (Fidélité documentaire) ---
    rag_scores: list[RagVerdict] = field(default_factory=list)

    # --- 5. La Fusion Finale ---
    fused_verdicts: list[FusedVerdict] = field(default_factory=list)
