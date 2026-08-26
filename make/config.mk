# ==============================================================================
# ⚙️ CONFIGURATION FIXE DU PROJET
# ==============================================================================
# Mêmes valeurs pour tout le monde : chaque personne a son propre projet GCP
# (identité dans .env : GCP_PROJECT), mais les ressources à l'intérieur de ce
# projet portent toutes le même nom, peu importe qui les crée.
# À ne modifier qu'en connaissance de cause : ça change le nom des ressources
# GCP existantes.
#
# 3 projets GCP possibles, jusqu'à 3 identités distinctes :
#   - GCP_PROJECT      : projet personnel de chacun (VM, BigQuery, buckets
#     personnels, Cloud Run test/staging/prod...) — cf. .env.
#   - ARTIFACT_PROJECT : projet partagé qui héberge les images Docker
#     (Artifact Registry) — défaut GCP_PROJECT.
#   - BUCKET_PROJECT   : projet partagé qui héberge les buckets d'équipe —
#     défaut GCP_PROJECT.
# Par défaut les 3 valent GCP_PROJECT (comportement actuel, tout dans le projet
# personnel) — à surcharger dans .env une fois les projets partagés créés.

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

# Projet GCP qui héberge le dépôt Artifact Registry (images) — distinct de
# GCP_PROJECT (projet personnel de chacun, pour tester) si l'équipe centralise
# les images dans un seul projet partagé (et potentiellement des buckets aussi,
# même logique). Défaut : GCP_PROJECT, donc rien ne change tant que ce n'est pas
# explicitement surchargé. Une fois le projet partagé créé, chacun surcharge
# dans son .env : ARTIFACT_PROJECT=<id-du-projet-partagé>.
ARTIFACT_PROJECT ?= $(GCP_PROJECT)

# Idem pour les buckets d'équipe (partagés, pas les buckets personnels de
# chacun cf. BUCKET_NAME/BUCKET_SUFFIX dans le Makefile racine et .env). Défaut
# GCP_PROJECT, à surcharger dans .env : BUCKET_PROJECT=<id-du-projet-partagé>.
BUCKET_PROJECT ?= $(GCP_PROJECT)

# Tag de l'image locale (docker_build_local/docker_run_local) — surchargeable en
# ligne de commande (ex. `make docker_build_local DOCKER_TAG=test`) pour ne pas
# écraser l'image :dev en cours d'utilisation (cf. tests/api/test_server_lifecycle.py).
DOCKER_TAG = dev

# --- VM (Compute Engine) ---
MACHINE_TYPE = e2-standard-2
IMAGE_FAMILY = ubuntu-2204-lts
IMAGE_PROJECT = ubuntu-os-cloud

# --- Cloud Run ---
GAR_MEMORY = 2Gi

# 3 environnements (test/staging/prod), même projet GCP, 3 services Cloud Run
# nommés $(GAR_IMAGE)-<env> (cf. make/cloudrun.mk, CLOUDRUN_ENV=test|staging|prod).
# Accès public (--allow-unauthenticated) par environnement — repasser à false
# pour verrouiller un environnement derrière IAM plus tard (ex. prod une fois
# l'authentification prête). Volontairement pas dans .env : décision d'équipe,
# pas un réglage personnel.
CLOUDRUN_PUBLIC_test = true
CLOUDRUN_PUBLIC_staging = true
CLOUDRUN_PUBLIC_prod = true

# --- BigQuery ---
# ⚠️ Doit rester identique à BQ_DATASET dans berlue/params.py (utilisée des deux
# côtés : make/bigquery.mk en shell, berlue/ml_logic/data.py en Python).
BQ_DATASET = berlue

# --- Prefect ---
# ⚠️ Idem : doit rester identique à PREFECT_LOG_LEVEL dans berlue/params.py.
PREFECT_LOG_LEVEL = INFO
