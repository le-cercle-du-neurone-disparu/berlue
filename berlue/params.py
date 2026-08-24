import os

##################  VARIABLES (paramétrables via .env : diffèrent par personne/environnement)  ##################
DATA_SIZE = os.environ.get("DATA_SIZE")

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

##################  DATA SCHEMA (TODO)  #################
# TODO: Define the exact column names of the raw dataset (required for BigQuery schema or CSV parsing).
# COLUMN_NAMES_RAW = ['feature_1', 'feature_2', 'target_variable']

# TODO: Enforce raw data types to optimize memory usage (e.g., use float32 instead of float64).
# DTYPES_RAW = {
#     "feature_1": "float32",
#     "feature_2": "int8",
#     "target_variable": "int8"
# }

# TODO: Define the final data type for the matrices after preprocessing.
# DTYPES_PROCESSED = np.float32
