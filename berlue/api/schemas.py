"""
Schémas Pydantic pour l'application FastAPI.

Ce module définit les modèles de validation des données pour les requêtes
entrantes (Inputs) et les réponses sortantes (Outputs). FastAPI utilise ces
schémas pour valider automatiquement les données et générer la documentation
Swagger.
"""

from pydantic import BaseModel

from berlue.params import BASE_TEMPERATURE, EVAL_DATASETS, OLLAMA_MODEL

# ==============================================================================
# ENTITES DE BASE
# ==============================================================================


class LLMConfig(BaseModel):
    """
    Configuration standard pour un modèle LLM.
    """

    name: str = OLLAMA_MODEL
    temperature: float = BASE_TEMPERATURE


# ==============================================================================
# SCHEMAS DES ENDPOINTS GENERAUX
# ==============================================================================


class LLMListOutput(BaseModel):
    """
    Payload de réponse contenant la liste des modèles LLM disponibles.
    """

    available_llms: list[str]


# ==============================================================================
# SCHEMAS DE L'ENDPOINT PREDICT
# ==============================================================================


class PredictInput(BaseModel):
    """
    Payload de requête pour l'endpoint de prédiction.
    """

    question: str
    answer: str | None = None
    llm: LLMConfig = LLMConfig()


class ClaimResult(BaseModel):
    """
    Représente l'évaluation d'une seule assertion extraite de la réponse du LLM.
    """

    claim_text: str
    status: str
    fusion_score: float
    evidence_source: str
    evidence_text: str


class PredictOutput(BaseModel):
    """
    Payload de réponse pour l'endpoint de prédiction, contenant la réponse du
    LLM et les assertions vérifiées.
    """

    question: str
    llm_used: LLMConfig
    full_llm_answer: str
    claims: list[ClaimResult]


# ==============================================================================
# SCHEMAS DE L'ENDPOINT EVALUATE
# ==============================================================================


class EvaluateInput(BaseModel):
    """
    Payload de requête pour déclencher un pipeline d'évaluation sur un dataset donné.
    """

    dataset_name: str = EVAL_DATASETS[0]
    sample_size: int = 100
    llm_to_test: LLMConfig = LLMConfig()


class ConfusionRow(BaseModel):
    """
    Une ligne de matrice de confusion : combien d'assertions d'une catégorie de
    vérité terrain donnée (vraie ou fausse) ont été prédites vraies / indécises
    / fausses par le système.
    """

    predicted_true: int
    predicted_undecided: int
    predicted_false: int


class ConfusionMatrix(BaseModel):
    """
    Matrice de confusion 2x3 (vérité terrain : assertion vraie/fausse) x
    (prédiction : vrai/indécis/faux) — sert à afficher une matrice de
    corrélation côté front.
    """

    ground_truth_true: ConfusionRow
    ground_truth_false: ConfusionRow


class Metrics(BaseModel):
    """
    Matrices de confusion comparant le système Berlue à la baseline (NLI seul),
    pour évaluer l'apport de la fusion Berlue par rapport à la baseline.
    """

    baseline: ConfusionMatrix
    berlue: ConfusionMatrix


class EvaluateOutput(BaseModel):
    """
    Payload de réponse retournant les résultats finaux du pipeline d'évaluation.
    """

    dataset: str
    samples_evaluated: int
    metrics: Metrics
    status: str


# ==============================================================================
# SCHEMAS DE L'ENDPOINT EVALUATIONS (lecture seule des résultats déjà en cache)
# ==============================================================================


class EvaluationResult(BaseModel):
    """
    Résultat d'une évaluation du pipeline Berlue pour un scope donné (un seul
    dataset, ratio, modèle, versions). `pipeline_version`/
    `generation_version` absents selon la table (cf.
    docs/evaluation/storage.md pour quel axe s'applique à quoi) ;
    `eval_version` toujours présent.

    `n_examples` couvre toujours tout ce qui a été fourni au calcul de la
    matrice, mais pas forcément le split de test officiel complet — comparer
    à `dataset_test_size` (taille réelle de ce split, `None` si inconnue) pour
    savoir si cette matrice est un run intégral ou un sous-ensemble partiel
    (ex. démo, développement).
    """

    dataset: str
    ratio: float
    model_id: str
    pipeline_version: str | None = None
    generation_version: str | None = None
    eval_version: str
    matrix: ConfusionMatrix
    n_examples: int
    dataset_test_size: int | None = None
    computed_at: str


class EvaluationListOutput(BaseModel):
    """
    Payload de réponse listant les résultats d'évaluation déjà en cache,
    optionnellement filtrés (dataset(s), ratio, modèle, version).
    """

    evaluations: list[EvaluationResult]
