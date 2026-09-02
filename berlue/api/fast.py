import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from berlue.api.fast_eval import eval_router, get_store
from berlue.api.schemas import LLMListOutput, PredictInput, PredictOutput
from berlue.llm.client import OllamaClient
from berlue.logging_config import setup_logging
from berlue.params import (
    EXTRACT_MODEL,
    JUDGE_MODEL,
    NLI_MODEL,
    OLLAMA_HOST,
    OLLAMA_MODEL,
    RAG_EMBEDDING_MODEL,
    RAG_MODEL,
    RAG_VECTOR_DB_PATH,
    SELFCHECK_NLI_MODEL,
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
    logger.info("🚀 DÉMARRAGE EN MODE PRODUCTION : chargement des index et modèles ML...")
    from berlue.api.service import BerlueService
    from berlue.rag.retriever import RagRetriever

    app.state.retriever = RagRetriever(llm_client=OllamaClient(model=RAG_MODEL))
    app.state.extractor = OllamaClient(model=EXTRACT_MODEL, temperature=0.0)

    app.state.service = BerlueService()

    # Le modèle NLI de SelfCheck se chargerait sinon à la première requête, et le
    # premier appelant paierait l'attente — mesuré à 16 s sur Cloud Run, sur un
    # service qui répondait pourtant déjà sur `/`. `make llm_warm` ne le couvre
    # pas : il ne préchauffe que les modèles Ollama, qui vivent ailleurs.
    from berlue.selfcheck.scorer import precharger_nli

    precharger_nli()

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
            # Deux modèles distincts, et les confondre a déjà induit en erreur :
            # selfcheck_nli juge la cohérence à chaque requête, nli_baseline ne
            # sert qu'à l'évaluation comparative.
            "selfcheck_nli": SELFCHECK_NLI_MODEL,
            "nli_baseline": NLI_MODEL,
            "embeddings": RAG_EMBEDDING_MODEL,
        },
        # Quel corpus FEVER est réellement monté. Le chemin porte la version
        # (RAG_CORPUS_VERSION), et le nombre de vecteurs la confirme : un index
        # réduit et l'index complet se déploient de la même façon, et rien ne
        # les distinguait de l'extérieur — un verdict « rien trouvé » n'a pas le
        # même sens selon qu'on cherche dans 1 475 ou 109 810 vecteurs.
        "rag_index": _etat_index(),
        # Ce que le serveur Ollama a sur disque, et ce qu'il tient en mémoire.
        # Les deux diffèrent : un modèle présent mais déchargé fera payer son
        # chargement à la première requête.
        "llm": _etat_ollama(),
    }


def _etat_index() -> dict:
    """Version et taille du corpus RAG monté, ou l'erreur qui l'en empêche."""
    retriever = getattr(app.state, "retriever", None)
    if retriever is None:
        return {"path": RAG_VECTOR_DB_PATH, "vectors": None, "erreur": "index non chargé"}
    return {
        "path": RAG_VECTOR_DB_PATH,
        "version": Path(RAG_VECTOR_DB_PATH).name,
        "vectors": int(retriever.index.ntotal),
    }


def _etat_ollama() -> dict:
    """Modèles présents sur le serveur Ollama, et ceux résidents en mémoire.

    Interrogé à chaud plutôt que déduit d'une configuration : c'est le seul
    moyen de savoir si un préchauffage a survécu. Toute erreur est rendue comme
    une donnée — cette route sert de sonde de santé, elle ne doit jamais échouer
    parce qu'un service tiers est indisponible.
    """
    etat: dict = {"host": OLLAMA_HOST}
    try:
        client = OllamaClient()
        etat["available"] = client.list_models()
        charges = client.client.ps()
        modeles = charges.get("models", []) if isinstance(charges, dict) else charges.models
        etat["loaded"] = [
            {
                "name": m.get("name") if isinstance(m, dict) else m.model,
                "size_gib": round((m.get("size") if isinstance(m, dict) else m.size) / 2**30, 1),
            }
            for m in modeles
        ]
    except Exception as e:
        etat["erreur"] = f"{type(e).__name__}: {e}"
    return etat


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
    try:
        return app.state.service.predict(
            payload=payload,
            retriever=app.state.retriever,
            extractor=app.state.extractor,
            store=get_store(),
        )
    except Exception as e:
        logger.exception("❌ Erreur de prédiction")
        raise HTTPException(status_code=500, detail=f"Erreur de prédiction : {str(e)}") from e
