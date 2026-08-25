from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from berlue.api.schemas import (
    EvaluateInput,
    EvaluateOutput,
    LLMListOutput,
    PredictInput,
    PredictOutput,
)
from berlue.ml_logic.registry import load_model
from berlue.params import USE_MOCK

# ==========================================
# 1. API INITIALIZATION
# ==========================================

app = FastAPI(
    title="BERLUE API",
    description="API for the Berlue LLM hallucination checker.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 2. DYNAMIC MODEL LOADING (MOCK VS REAL)
# ==========================================

if USE_MOCK:
    print("⚠️ STARTING IN MOCK MODE: The real ML model is not loaded.")
    from berlue.mocks.mock_pipeline import MockBerluePipeline

    app.state.model = MockBerluePipeline()
else:
    print("🚀 STARTING IN PRODUCTION MODE: Loading the real ML model...")
    app.state.model = load_model()

# ==========================================
# 3. TECHNICAL ENDPOINTS (Existing template)
# ==========================================


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """
    Silence 404 errors for favicon requests automatically sent by web browsers.
    """
    return Response(status_code=204)


@app.get("/")
def root():
    """
    Root health-check endpoint.
    """
    return {"greeting": "Hello from Berlue API"}


@app.put("/model")
def update_model(stage: str = "Production"):
    """
    Reload or swap the active machine learning model in application state on-the-fly.
    """
    try:
        new_model = load_model(stage=stage)
        if new_model is None:
            raise HTTPException(
                status_code=404, detail=f"Model for stage '{stage}' could not be found or loaded from registry."
            )

        # Hot-swap the loaded model stored in FastAPI application state
        app.state.model = new_model
        return {"status": "success", "message": f"Model successfully updated to stage '{stage}'."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading model for stage '{stage}': {str(e)}") from e


# ==========================================
# 4. BUSINESS ENDPOINTS (Berlue)
# ==========================================


@app.get("/llms", response_model=LLMListOutput)
def get_llm_list():
    """
    Returns the list of available LLM models that can be tested and compared.
    """
    pipeline = app.state.model

    try:
        # Call the method that retrieves available models from the active pipeline
        llms = pipeline.get_available_llms()
        return {"available_llms": llms}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not retrieve LLM list: {str(e)}") from e


@app.post("/predict", response_model=PredictOutput)
def predict(payload: PredictInput):
    """
    Takes a question and an LLM model, generates the response, and checks for hallucinations.
    """
    pipeline = app.state.model

    try:
        # On passe directement l'objet LLMConfig à la méthode predict
        result_dict = pipeline.predict(question=payload.question, llm_config=payload.llm)
        return result_dict
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction error: {str(e)}") from e


@app.post("/evaluate", response_model=EvaluateOutput)
def evaluate(payload: EvaluateInput):
    """
    Runs a complete evaluation of the Berlue system on a dataset.
    """
    pipeline = app.state.model

    try:
        # On passe directement l'objet LLMConfig à la méthode evaluate
        metrics_dict = pipeline.evaluate_dataset(
            dataset_name=payload.dataset_name, n_samples=payload.sample_size, llm_config=payload.llm_to_test
        )

        return {
            "dataset": payload.dataset_name,
            "samples_evaluated": payload.sample_size,
            "metrics": metrics_dict,
            "status": "success",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evaluation error: {str(e)}") from e
