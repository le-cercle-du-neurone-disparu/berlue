import os

##################  VARIABLES (paramétrables via .env : diffèrent par personne/environnement)  ##################
DATA_SIZE = os.environ.get("DATA_SIZE")

# USE_MOCK : sert la pipeline mockée (berlue/mocks/) plutôt que le vrai modèle sur
# l'API — pratique pour développer/tester le front sans dépendre d'un modèle
# entraîné. Défaut "0" (désactivé).
USE_MOCK = bool(int(os.environ.get("USE_MOCK", "0")))

# GCP : identité du projet de chacun + secrets/emplacements propres à la machine
GCP_PROJECT = os.environ.get("GCP_PROJECT")

# Bucket : unique GLOBALEMENT sur GCP, jamais un nom fixe littéral. Reconstruit à
# partir du projet de chacun + un nom commun + un suffixe (cf. .env.sample) —
# même formule que BUCKET_NAME dans le Makefile.
BUCKET_SUFFIX = os.environ.get("BUCKET_SUFFIX", "1")
BUCKET_NAME = f"{GCP_PROJECT}-berlue_{BUCKET_SUFFIX}"

# Notifications : secret (URL de webhook)
NOTIFY_BASE_URL = os.environ.get("NOTIFY_BASE_URL")

# RUN_ENV : quel environnement pour `make run_*` (local/docker/gcp) — pilote aussi
# MLFLOW_TRACKING_URI ci-dessous. Défaut "local".
RUN_ENV = os.environ.get("RUN_ENV", "local")

# MODEL_TARGET se règle en ligne de commande, pas dans .env — cf. make/pipeline.mk
# (ex: `make run_train MODEL_TARGET=gcs`). Défaut "local".
MODEL_TARGET = os.environ.get("MODEL_TARGET", "local")
assert MODEL_TARGET in ("local", "gcs", "mlflow"), (
    f"❌ MODEL_TARGET invalide : {MODEL_TARGET!r} (doit être local, gcs ou mlflow)"
)

# MLflow : le serveur de tracking dépend de RUN_ENV.
# TODO: pas encore de serveur MLflow partagé pour "gcp".
_MLFLOW_TRACKING_URIS = {
    "local": "http://localhost:5000",
    "docker": "http://localhost:5000",
    "gcp": None,
}
MLFLOW_TRACKING_URI = _MLFLOW_TRACKING_URIS.get(RUN_ENV, "http://localhost:5000")

##################  PIPELINE BERLUE (LLM local, RAG inversé, SelfCheckGPT)  ##################

# --- LLM (Ollama) ---
OLLAMA_HOST = os.environ.get("BERLUE_OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("BERLUE_OLLAMA_MODEL", "qwen2.5:0.5b")
SELFCHECK_K = int(os.environ.get("BERLUE_SELFCHECK_K", "5"))
SELFCHECK_TEMPERATURE_MIN = float(os.environ.get("BERLUE_SELFCHECK_TEMPERATURE_MIN", "0.7"))
SELFCHECK_TEMPERATURE_MAX = float(os.environ.get("BERLUE_SELFCHECK_TEMPERATURE_MAX", "1.3"))
BASE_TEMPERATURE = float(os.environ.get("BERLUE_BASE_TEMPERATURE", "0.0"))

# --- EXTRACTION ---
EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL", "qwen2.5:0.5b")

# --- Embeddings + RAG inversé ---
RAG_EMBEDDING_MODEL = "all-mpnet-base-v2"
RAG_INDEX_DIR = "data/fever/faiss"
RAG_VECTOR_DB_PATH = "data/fever/faiss"

# --- NLI léger ---
NLI_MODEL = os.environ.get("BERLUE_NLI_MODEL", "microsoft/deberta-v3-small")
NLI_BASELINE_PATH = os.environ.get("BERLUE_NLI_BASELINE_PATH", "./models/nli_tfidf_logreg.joblib")

# --- Données ---
FEVER_DATA_PATH = os.environ.get("BERLUE_FEVER_DATA_PATH", "./data/raw/fever")
HALUEVAL_DATA_PATH = os.environ.get(
    "BERLUE_HALUEVAL_DATA_PATH", "https://raw.githubusercontent.com/RUCAIBox/HaluEval/main/data/qa_data.json"
)
TRUTHFULQA_DATA_PATH = os.environ.get(
    "BERLUE_TRUTHFULQA_DATA_PATH", "https://raw.githubusercontent.com/sylinrl/TruthfulQA/main/TruthfulQA.csv"
)

# EVAL_DATASETS : quel(s) jeu(x) de données labellisés utiliser pour l'évaluation
# offline (entraînement du baseline NLI + jeu de test, cf. evaluation/data.py) —
# "halueval", "truthfulqa", ou les deux. Pratique pour itérer sur un seul dataset
# à la fois sans toucher au code. Défaut : les deux.
_EVAL_DATASETS_RAW = os.environ.get("BERLUE_EVAL_DATASETS", "halueval,truthfulqa")
EVAL_DATASETS = [d.strip() for d in _EVAL_DATASETS_RAW.split(",") if d.strip()]

# --- MLOps ---
MLOPS_DB_PATH = os.environ.get("BERLUE_MLOPS_DB_PATH", "./data/mlops/hallucination_tracker.db")

# --- Fusion des scores ---
FUSION_WEIGHT_RAG = float(os.environ.get("BERLUE_FUSION_WEIGHT_RAG", "0.6"))
FUSION_WEIGHT_SELFCHECK = float(os.environ.get("BERLUE_FUSION_WEIGHT_SELFCHECK", "0.4"))

##################  CONFIGURATION FIXE (décisions de mainteneur, pas des paramètres .env)  ##################
# Mêmes valeurs pour tout le monde — cf. make/config.mk pour l'équivalent côté Make
# (GCP_REGION, ZONE, BQ_REGION, INSTANCE, SA_NAME, ARTIFACTSREPO, GAR_IMAGE...).
CHUNK_SIZE = 100_000
BQ_DATASET = "berlue"

MLFLOW_EXPERIMENT = "berlue_experiment"
MLFLOW_MODEL_NAME = "berlue_model"
PREFECT_FLOW_NAME = "berlue_main_flow"
PREFECT_LOG_LEVEL = "INFO"
EVALUATION_START_DATE = "2024-01-01"

NOTIFY_CHANNEL = "#berlue-alerts"
NOTIFY_AUTHOR = "Berlue_Pipeline_Bot"

##################  CONSTANTS  #####################
# 💡 Cette ligne trouve dynamiquement la racine du projet
# (__file__ = params.py -> dirname = ton package -> dirname = racine du projet)
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))

# 💡 On pointe désormais vers les dossiers que nous avons créés dans ton architecture !
LOCAL_DATA_PATH = os.path.join(PROJECT_ROOT, "data")
LOCAL_REGISTRY_PATH = os.path.join(PROJECT_ROOT, "models")

##################  SCHEMA DES DONNEES (TODO)  #################
# TODO: Définir les noms exacts des colonnes du dataset brut (requis pour le schéma BigQuery ou le parsing CSV).
# COLUMN_NAMES_RAW = ['feature_1', 'feature_2', 'target_variable']

# TODO: Imposer les dtypes des données brutes pour optimiser l'usage mémoire (ex. float32 au lieu de float64).
# DTYPES_RAW = {
#     "feature_1": "float32",
#     "feature_2": "int8",
#     "target_variable": "int8"
# }

# TODO: Définir le type de données final pour les matrices après prétraitement.
# DTYPES_PROCESSED = np.float32
