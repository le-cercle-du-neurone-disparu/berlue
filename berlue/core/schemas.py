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
    # Un composant du pipeline a échoué : aucun verdict n'est rendu et la question
    # est à rejouer. À exclure des matrices de confusion, jamais à compter comme une
    # prédiction (cf. berlue.evaluation.metrics.build_confusion_matrix).
    PANNE = "panne"


class Fondement(StrEnum):
    """Sur quoi repose un verdict. Une preuve et une conviction ne s'affichent pas de
    la même façon et ne se défendent pas de la même façon — le verdict reste à trois
    valeurs pour rester comparable à une vérité terrain, c'est ce champ qui porte la
    différence."""

    PREUVE_FEVER = "preuve_fever"  # la base contient de quoi trancher
    CONVICTION = "conviction"  # rien en base : opinion argumentée, faillible
    AUCUN = "aucun"  # rien à dire


class RagJudgment(StrEnum):
    FEVER_CONFIRMS = "proven_true"  # FEVER prouve que c'est vrai
    FEVER_REFUTES = "proven_false"  # FEVER prouve que c'est faux
    LIKELY_TRUE = "likely_true"  # rien dans FEVER, mais persuadé vrai
    LIKELY_FALSE = "likely_false"  # rien dans FEVER, mais persuadé faux
    I_DONT_KNOWN = "unknown"


@dataclass(frozen=True)
class Generation:
    """Ce qu'un appel au LLM a produit : le texte ET les métadonnées de l'appel. (llm/)

    Rendues ensemble parce qu'elles n'ont de sens qu'ensemble. Portées par
    l'appelant plutôt que par le client, elles restent celles de SON appel même
    quand plusieurs threads partagent le même client.
    """

    text: str
    modele: str
    secondes: float
    done_reason: str | None = None
    tokens: int | None = None

    @property
    def meta(self) -> dict:
        """Forme dictionnaire attendue par les traces RAG (`rag.retriever._trace`),
        qui sont sérialisées telles quelles dans le champ `debug` de l'API."""
        return {
            "modele": self.modele,
            "secondes": self.secondes,
            "done_reason": self.done_reason,
            "tokens": self.tokens,
            "caracteres": len(self.text),
        }


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
    verdict: RagJudgment
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
    fondement: Fondement = Fondement.AUCUN


@dataclass(frozen=True)
class RagCheck:
    """Vérification RAG d'UNE affirmation : le verdict et sa trace. (rag/)

    La trace est rendue avec le verdict au lieu d'être poussée dans une liste
    fournie par l'appelant : deux affirmations vérifiées en parallèle écriraient
    dans la même liste, et l'ordre des traces ne correspondrait plus à celui des
    affirmations.
    """

    verdict: RagVerdict
    trace: dict


@dataclass(frozen=True)
class RagOutcome:
    """Tout ce que produit la branche RAG pour une question. (rag/)"""

    verdicts: list[RagVerdict] = field(default_factory=list)
    traces: list[dict] = field(default_factory=list)
    panne: str | None = None


@dataclass(frozen=True)
class SelfCheckOutcome:
    """Tout ce que produit la branche SelfCheckGPT pour une question. (selfcheck/)"""

    samples: list[str] = field(default_factory=list)
    scores: list[SelfCheckScore] = field(default_factory=list)


@dataclass(frozen=True)
class PipelineResult:
    """Résultat complet pour une question posée par l'utilisateur.

    Figé : les deux branches de vérification tournent dans des threads distincts
    et n'ont donc plus d'objet commun à remplir au fil des étapes. Chacune rend
    son propre `RagOutcome` / `SelfCheckOutcome`, et l'assemblage se fait ici, en
    une seule construction, une fois les deux branches terminées. Ajouter un
    résultat à un objet partagé — ce que faisaient les étapes successives — est
    précisément ce qui interdisait de les paralléliser.

    Dériver une variante (la fusion, qui ajoute ses verdicts) se fait par
    `dataclasses.replace`, pas par affectation.
    """

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

    # Détail de chaque vérification RAG — extraits remontés avec leur distance,
    # réponse brute du modèle, métadonnées de génération. Toujours rempli : ce
    # sont les mêmes données que la trace journalisée, et les collecter coûte
    # quelques dictionnaires. C'est l'API qui décide de les exposer ou non.
    rag_traces: list[dict] = field(default_factory=list)

    # Renseigné quand un composant a échoué. La réponse entière est alors invalide,
    # pour TOUTES les affirmations et pas seulement celle qui a échoué, et la question
    # doit être rejouée. Distinct d'un RAG qui répond « je ne sais pas » : ça, c'est
    # une réponse légitime.
    panne: str | None = None
