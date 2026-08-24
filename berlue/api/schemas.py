"""
Pydantic schemas for the FastAPI application.

This module defines the data validation models for incoming requests (Inputs)
and outgoing responses (Outputs). FastAPI uses these schemas to automatically
validate data and generate the Swagger documentation.
"""

from typing import List

from pydantic import BaseModel

# ==============================================================================
# PREDICT ENDPOINT SCHEMAS
# ==============================================================================

class PredictInput(BaseModel):
    """
    Request payload for the prediction endpoint.
    """
    question: str
    llm_model: str = "llama3"


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
    llm_model_used: str
    full_llm_answer: str
    claims: List[ClaimResult]


# ==============================================================================
# EVALUATE ENDPOINT SCHEMAS
# ==============================================================================

class EvaluateInput(BaseModel):
    """
    Request payload to trigger an evaluation pipeline on a specific dataset.
    """
    dataset_name: str
    sample_size: int = 100
    llm_model_to_test: str


class Metrics(BaseModel):
    """
    Data structure holding the computed performance metrics.
    """
    berlue_accuracy: float
    baseline_nli_accuracy: float
    berlue_precision: float


class EvaluateOutput(BaseModel):
    """
    Response payload returning the final results of the evaluation pipeline.
    """
    dataset: str
    samples_evaluated: int
    metrics: Metrics
    status: str
