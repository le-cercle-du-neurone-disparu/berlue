from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from berlue.api.schemas import (
    EvaluateInput,
    EvaluateOutput,
    LLMListOutput,
    PredictInput,
    PredictOutput,
)
from berlue.llm.client import OllamaClient
from berlue.params import USE_MOCK


# ==========================================
# 1. GESTION DU CYCLE DE VIE (DÉMARRAGE)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    if USE_MOCK:
        print("⚠️ DÉMARRAGE EN MODE MOCK : le vrai modèle n'est pas chargé.")
        from berlue.mocks.mock_pipeline import MockBerluePipeline

        app.state.service = MockBerluePipeline()
    else:
        print("🚀 DÉMARRAGE EN MODE PRODUCTION : chargement des index et modèles ML...")
        from berlue.api.service import BerlueService
        from berlue.rag.retriever import RagRetriever

        app.state.retriever = RagRetriever()
        app.state.extractor = OllamaClient(model="ton_modele_extract")

        app.state.service = BerlueService()

    yield  # Le serveur tourne ici

    print("🛑 Extinction du serveur...")


# ==========================================
# 2. INITIALISATION DE L'API
# ==========================================
app = FastAPI(
    title="BERLUE API",
    description="API du détecteur d'hallucinations LLM Berlue.",
    version="1.0.0",
    lifespan=lifespan,  # 👈 On attache le cycle de vie ici !
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


# ==========================================
# 4. ENDPOINTS METIER (Berlue)
# ==========================================


@app.get("/llms", response_model=LLMListOutput)
def get_llm_list():
    """
    Retourne la liste des modèles LLM disponibles pouvant être testés et comparés.
    """
    service = app.state.service

    try:
        llms = service.get_available_llms()
        return {"available_llms": llms}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impossible de récupérer la liste : {str(e)}") from e


@app.post("/predict", response_model=PredictOutput)
def predict_endpoint(payload: PredictInput):
    """
    Évalue une question avec un LLM et détecte les hallucinations.
    """
    if USE_MOCK:
        return app.state.service.predict(payload)
    else:
        try:
            return app.state.service.predict(
                payload=payload, retriever=app.state.retriever, extractor=app.state.extractor
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur de prédiction : {str(e)}") from e


@app.post("/evaluate", response_model=EvaluateOutput)
def evaluate_endpoint(payload: EvaluateInput):
    """
    Lance une évaluation complète du système Berlue sur un dataset.
    """
    try:
        if USE_MOCK:
            metrics_dict = app.state.service.evaluate_dataset(
                dataset_name=payload.dataset_name, n_samples=payload.sample_size, llm_config=payload.llm_to_test
            )
        else:
            # Le vrai service a besoin de ses outils !
            metrics_dict = app.state.service.evaluate_dataset(
                dataset_name=payload.dataset_name,
                n_samples=payload.sample_size,
                llm_config=payload.llm_to_test,
                retriever=app.state.retriever,
                extractor=app.state.extractor,
            )

        return {
            "dataset": payload.dataset_name,
            "samples_evaluated": payload.sample_size,
            "metrics": metrics_dict,
            "status": "success",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'évaluation : {str(e)}") from e
