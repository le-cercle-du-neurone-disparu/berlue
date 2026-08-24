import os
import numpy as np

##################  VARIABLES  ##################
DATA_SIZE = os.environ.get("DATA_SIZE")
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE"))
MODEL_TARGET = os.environ.get("MODEL_TARGET")

# GCP Infrastructure
GCP_PROJECT = os.environ.get("GCP_PROJECT")
GCP_REGION = os.environ.get("GCP_REGION")
BQ_DATASET = os.environ.get("BQ_DATASET")
BQ_REGION = os.environ.get("BQ_REGION")
BUCKET_NAME = os.environ.get("BUCKET_NAME")
INSTANCE = os.environ.get("INSTANCE")

# MLflow & Prefect
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI")
MLFLOW_EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT")
MLFLOW_MODEL_NAME = os.environ.get("MLFLOW_MODEL_NAME")
PREFECT_FLOW_NAME = os.environ.get("PREFECT_FLOW_NAME")
PREFECT_LOG_LEVEL = os.environ.get("PREFECT_LOG_LEVEL")
EVALUATION_START_DATE = os.environ.get("EVALUATION_START_DATE")

# Docker & Artifact Registry
GAR_IMAGE = os.environ.get("GAR_IMAGE")
GAR_MEMORY = os.environ.get("GAR_MEMORY")

# Notifications (Webhook)
NOTIFY_BASE_URL = os.environ.get("NOTIFY_BASE_URL")
NOTIFY_CHANNEL = os.environ.get("NOTIFY_CHANNEL")
NOTIFY_AUTHOR = os.environ.get("NOTIFY_AUTHOR")

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

################## VALIDATIONS #################
env_valid_options = dict(
    # DATA_SIZE=["1k", "200k", "all"],
    MODEL_TARGET=["local", "gcs", "mlflow"],
)

def validate_env_value(env, valid_options):
    env_value = os.environ.get(env)
    if env_value not in valid_options:
        raise NameError(f"❌ Invalid value for {env} in `.env` file: '{env_value}' must be in {valid_options}")

for env, valid_options in env_valid_options.items():
    validate_env_value(env, valid_options)
