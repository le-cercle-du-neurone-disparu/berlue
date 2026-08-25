from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

# from berlue.ml_logic.preprocessor import preprocess_features
from berlue.ml_logic.registry import load_model

# from berlue.api.schemas import MyCustomSchemas

# Pydantic V2 TypeAdapter for efficient batch serialization
# my_custom_model_list_adapter = TypeAdapter(List[MyCustomSchemas])

app = FastAPI(title="MY CUSTOM API", description="API for XXX.", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load model at startup
model = load_model()
# assert model is not None
app.state.model = model


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
    return {"greeting": "Hello"}


@app.put("/model")
def update_model(stage: str = "Production"):
    """
    Reload or swap the active machine learning model in application state on-the-fly.

    This endpoint allows hot-swapping the model loaded in memory (e.g., switching
    between 'Production', 'Staging', or a specific model version) without requiring
    an API process restart or causing service downtime.

    Args:
        stage (str, optional): Target MLflow stage/tag of the model to fetch
                               from registry. Defaults to "Production".

    Returns:
        dict: Confirmation payload detailing update status and active model stage.

    Raises:
        HTTPException: 404 error if target model stage does not exist in registry,
                       or 500 error if model loading fails internally.
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


@app.get("/predict")
def predict(
    # p1: type-p1,
    # p2: type-p2,
):
    """
    Predict XXX.

    Args:
        p1 (type-p1): XXX.
        ...

    Returns:
        dict: Single estimation result, e.g. `{"XXX": XXX}`.
    """
    pass


@app.post("/predict_batch")
async def predict_batch(inputs: list[dict]):
    """
    Predict XXX for multiple XXX in a single batch request via JSON POST payload.

    Args:
        XXX

    Returns:
        dict: Dictionary containing the array of predicted XXX, e.g. `{"XXX": [XXX, XXX]}`.
    """
    pass
