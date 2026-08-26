"""
Schémas Pydantic pour l'application FastAPI.

Ce module définit les modèles de validation des données pour les requêtes
entrantes (Inputs) et les réponses sortantes (Outputs). FastAPI utilise ces
schémas pour valider automatiquement les données et générer la documentation
Swagger.
"""

from pydantic import BaseModel

# ==============================================================================
# ENTITES DE BASE
# ==============================================================================


class LLMConfig(BaseModel):
    """
    Configuration standard pour un modèle LLM.
    """

    name: str = "llama3"
    temperature: float = 0.7


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

    dataset_name: str
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
