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
# 1. INITIALISATION DE L'API
# ==========================================

app = FastAPI(
    title="BERLUE API",
    description="API du détecteur d'hallucinations LLM Berlue.",
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
# 2. CHARGEMENT DYNAMIQUE DU MODELE (MOCK VS REEL)
# ==========================================

if USE_MOCK:
    print("⚠️ DÉMARRAGE EN MODE MOCK : le vrai modèle ML n'est pas chargé.")
    from berlue.mocks.mock_pipeline import MockBerluePipeline

    app.state.model = MockBerluePipeline()
else:
    print("🚀 DÉMARRAGE EN MODE PRODUCTION : chargement du vrai modèle ML...")
    app.state.model = load_model()

# ==========================================
# 3. ENDPOINTS TECHNIQUES (template existant)
# ==========================================


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """
    Fait taire les erreurs 404 pour les requêtes favicon envoyées automatiquement par les navigateurs.
    """
    return Response(status_code=204)


@app.get("/")
def root():
    """
    Endpoint racine de health-check.
    """
    return {"greeting": "Hello from Berlue API"}


@app.put("/model")
def update_model(stage: str = "Production"):
    """
    Recharge ou remplace à la volée le modèle de machine learning actif dans l'état de l'application.
    """
    try:
        new_model = load_model(stage=stage)
        if new_model is None:
            raise HTTPException(
                status_code=404,
                detail=f"Le modèle pour le stage '{stage}' est introuvable ou n'a pas pu être chargé "
                "depuis le registry.",
            )

        # Remplace à la volée le modèle stocké dans l'état de l'application FastAPI
        app.state.model = new_model
        return {"status": "success", "message": f"Modèle mis à jour avec succès vers le stage '{stage}'."}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Erreur lors du chargement du modèle pour le stage '{stage}' : {str(e)}"
        ) from e


# ==========================================
# 4. ENDPOINTS METIER (Berlue)
# ==========================================


@app.get("/llms", response_model=LLMListOutput)
def get_llm_list():
    """
    Retourne la liste des modèles LLM disponibles pouvant être testés et comparés.
    """
    pipeline = app.state.model

    try:
        # Appelle la méthode qui récupère les modèles disponibles depuis le pipeline actif
        llms = pipeline.get_available_llms()
        return {"available_llms": llms}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impossible de récupérer la liste des LLM : {str(e)}") from e


@app.post("/predict", response_model=PredictOutput)
def predict(payload: PredictInput):
    """
    Prend une question et un modèle LLM, génère la réponse, et vérifie les hallucinations.
    """
    pipeline = app.state.model

    try:
        # On passe directement l'objet LLMConfig à la méthode predict
        result_dict = pipeline.predict(question=payload.question, llm_config=payload.llm)
        return result_dict
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de prédiction : {str(e)}") from e


@app.post("/evaluate", response_model=EvaluateOutput)
def evaluate(payload: EvaluateInput):
    """
    Lance une évaluation complète du système Berlue sur un dataset.
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
        raise HTTPException(status_code=500, detail=f"Erreur d'évaluation : {str(e)}") from e
