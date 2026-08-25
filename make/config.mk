# ==============================================================================
# ⚙️ CONFIGURATION FIXE DU PROJET
# ==============================================================================
# Mêmes valeurs pour tout le monde : chaque personne a son propre projet GCP
# (identité dans .env : GCP_PROJECT), mais les ressources à l'intérieur de ce
# projet portent toutes le même nom, peu importe qui les crée.
# À ne modifier qu'en connaissance de cause : ça change le nom des ressources
# GCP existantes.

# --- Python & environnement local ---
PYTHON_VERSION = 3.14.6
VENV_NAME = berlue-env

# --- Docker ---
DOCKER_BASE_IMAGE = python:$(PYTHON_VERSION)-slim

# --- Localisation GCP (une seule région/zone pour toute l'équipe) ---
GCP_REGION = europe-west1
ZONE = europe-west1-b
BQ_REGION = EU

# --- Noms de ressources GCP (fixes, scope = à l'intérieur du projet de chacun,
# donc pas de risque de collision globale contrairement à BUCKET_NAME) ---
INSTANCE = berlue
SA_NAME = berlue-vm-sa
ARTIFACTSREPO = berlue-repo
GAR_IMAGE = berlue-api

# --- VM (Compute Engine) ---
MACHINE_TYPE = e2-standard-2
IMAGE_FAMILY = ubuntu-2204-lts
IMAGE_PROJECT = ubuntu-os-cloud

# --- Cloud Run ---
GAR_MEMORY = 2Gi

# --- BigQuery ---
# ⚠️ Doit rester identique à BQ_DATASET dans berlue/params.py (utilisée des deux
# côtés : make/bigquery.mk en shell, berlue/ml_logic/data.py en Python).
BQ_DATASET = berlue

# --- Prefect ---
# ⚠️ Idem : doit rester identique à PREFECT_LOG_LEVEL dans berlue/params.py.
PREFECT_LOG_LEVEL = INFO
