"""
Pydantic schemas for the FastAPI application.

This module defines the data validation models for incoming requests (Inputs)
and outgoing responses (Outputs). FastAPI uses these schemas to automatically
validate data and generate the Swagger documentation.
"""

from pydantic import BaseModel

# ==============================================================================
# CORE ENTITIES
# ==============================================================================


class LLMConfig(BaseModel):
    """
    Standard configuration for an LLM model.
    """

    name: str = "llama3"
    temperature: float = 0.7


# ==============================================================================
# GENERAL ENDPOINT SCHEMAS
# ==============================================================================


class LLMListOutput(BaseModel):
    """
    Response payload containing the list of available LLM models.
    """

    available_llms: list[str]


# ==============================================================================
# PREDICT ENDPOINT SCHEMAS
# ==============================================================================


class PredictInput(BaseModel):
    """
    Request payload for the prediction endpoint.
    """

    question: str
    llm: LLMConfig = LLMConfig()


class ClaimResult(BaseModel):
    """
    Represents the evaluation of a single claim extracted from the LLM's answer.
    """

    claim_text: str
    status: str
    fusion_score: float
    evidence_source: str
    evidence_text: str


class PredictOutput(BaseModel):
    """
    Response payload for the prediction endpoint containing the LLM's answer
    and the fact-checked claims.
    """

    question: str
    llm_used: LLMConfig
    full_llm_answer: str
    claims: list[ClaimResult]


# ==============================================================================
# EVALUATE ENDPOINT SCHEMAS
# ==============================================================================


class EvaluateInput(BaseModel):
    """
    Request payload to trigger an evaluation pipeline on a specific dataset.
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
    Response payload returning the final results of the evaluation pipeline.
    """

    dataset: str
    samples_evaluated: int
    metrics: Metrics
    status: str
