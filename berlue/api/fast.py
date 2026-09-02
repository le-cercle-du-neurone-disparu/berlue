import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from berlue.api.fast_eval import eval_router
from berlue.api.schemas import LLMListOutput, PredictInput, PredictOutput
from berlue.llm.client import OllamaClient
from berlue.logging_config import setup_logging
from berlue.params import (
    EXTRACT_MODEL,
    JUDGE_MODEL,
    NLI_MODEL,
    OLLAMA_MODEL,
    RAG_EMBEDDING_MODEL,
    RAG_MODEL,
    USE_MOCK,
)

setup_logging()

httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)
httpx_logger.propagate = False

httpcore_logger = logging.getLogger("httpcore")
httpcore_logger.setLevel(logging.WARNING)
httpcore_logger.propagate = False

logger = logging.getLogger(__name__)


# ==========================================
# 1. GESTION DU CYCLE DE VIE (DÉMARRAGE)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    if USE_MOCK:
        logger.warning("⚠️ DÉMARRAGE EN MODE MOCK : le vrai modèle n'est pas chargé.")
        from berlue.mocks.mock_pipeline import MockBerluePipeline

        app.state.service = MockBerluePipeline()
    else:
        logger.info("🚀 DÉMARRAGE EN MODE PRODUCTION : chargement des index et modèles ML...")
        from berlue.api.service import BerlueService
        from berlue.rag.retriever import RagRetriever

        app.state.retriever = RagRetriever(llm_client=OllamaClient(model=RAG_MODEL))
        app.state.extractor = OllamaClient(model=EXTRACT_MODEL, temperature=0.0)

        app.state.service = BerlueService()

    yield  # Le serveur tourne ici

    logger.info("🛑 Extinction du serveur...")


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

app.include_router(eval_router)

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

    Publie aussi le modèle attaché à chaque étage du pipeline. Ces valeurs
    viennent de l'environnement du conteneur : les lire ici est le seul moyen
    de savoir ce qu'une instance déployée utilise vraiment, sans quoi un
    verdict s'interprète sans savoir qui l'a produit.
    """
    return {
        "greeting": "Hello from Berlue API",
        "models": {
            # Le modèle évalué : il produit la réponse à vérifier et les
            # échantillons SelfCheck. Surchargeable par requête via le
            # `llm.name` de /predict — c'est ici le défaut du service.
            "generation": OLLAMA_MODEL,
            "extraction": EXTRACT_MODEL,
            "rag": RAG_MODEL,
            "judge": JUDGE_MODEL,
            "nli": NLI_MODEL,
            "embeddings": RAG_EMBEDDING_MODEL,
        },
        "mock": USE_MOCK,
    }


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
            logger.exception("❌ Erreur de prédiction")
            raise HTTPException(status_code=500, detail=f"Erreur de prédiction : {str(e)}") from e
