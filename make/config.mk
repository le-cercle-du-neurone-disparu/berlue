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

# --- Helpers partagés (scripts/) ---
# Relance une commande le temps que GCP propage une création — un compte de
# service ou une API tout juste créés ne sont pas visibles immédiatement :
#   $(RETRY) "<description>" <commande...>
RETRY = bash scripts/gcp_retry.sh
# Passe un service Cloud Run à min-instances=<n>, en ignorant (sans échouer)
# un service pas encore déployé :
#   $(CLOUDRUN_SET_MIN) <service> <n> [args gcloud...]
CLOUDRUN_SET_MIN = bash scripts/cloudrun_set_min.sh

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
# 2Gi puis 4Gi mesurés insuffisants en conditions réelles (31/08) : /predict
# charge en mémoire le modèle d'embedding RAG (all-mpnet-base-v2) ET le
# modèle NLI de SelfCheckGPT (potsawee/deberta-v3-large-mnli, ~1.7 Go de
# poids, plus l'overhead torch au chargement/inférence) — 2Gi a d'abord
# manqué de "disque" (adossé à la mémoire sur Cloud Run) pour le
# télécharger, 4Gi a fini tué par le kernel (Container terminated on
# signal 9 dans les logs Cloud Run — OOM, pas une erreur applicative).
# 8Gi = marge réelle pour les deux modèles + le runtime torch en pic.
GAR_MEMORY = 8Gi
# Cloud Run plafonne la mémoire selon le CPU alloué (1 vCPU -> 4Gi max,
# confirmé par erreur gcloud le 31/08) — 2 vCPU nécessaire pour débloquer
# GAR_MEMORY=8Gi, pas juste un choix de performance.
GAR_CPU = 2
# /predict enchaîne ~6 appels LLM séquentiels (génération, extraction, K
# échantillons SelfCheck, RAG, fusion) — 600s plutôt que le défaut Cloud Run
# (300s), à ajuster une fois mesuré en conditions réelles contre berlue-llm.
GAR_TIMEOUT = 600

# Bucket GCS dédié à l'index RAG (FAISS/FEVER), monté en volume GCS FUSE par
# cloudrun_deploy — jamais reconstruit au docker build, cf.
# claude-doc/plan-deploiement-api-gcp.md. Dédié plutôt que BUCKET_NAME (buckets
# personnels/MLOps) : un volume GCS FUSE monte tout le contenu d'un bucket,
# pas un sous-dossier — mélanger d'autres données les rendrait visibles dans
# le conteneur API. Dans BUCKET_PROJECT (projet partagé, défaut GCP_PROJECT),
# comme les autres buckets d'équipe.
RAG_BUCKET_NAME = $(GCP_PROJECT)-berlue-rag

# Compte de service attaché au service Cloud Run (distinct de SA_NAME, la VM
# d'entraînement) — droits Firestore/BigQuery nécessaires pour EVAL_STORE_TARGET=gcp
# en exécution GCP, cf. make/gcp.mk#iam_setup_cloudrun_service_account.
CLOUDRUN_SA_NAME = sa-berlue

# 3 environnements (test/staging/prod), même projet GCP, 3 services Cloud Run
# nommés $(GAR_IMAGE)-<env> (cf. make/cloudrun.mk, CLOUDRUN_ENV=test|staging|prod).
# Accès public (--allow-unauthenticated) par environnement — repasser à false
# pour verrouiller un environnement derrière IAM plus tard (ex. prod une fois
# l'authentification prête). Volontairement pas dans .env : décision d'équipe,
# pas un réglage personnel.
CLOUDRUN_PUBLIC_test = true
CLOUDRUN_PUBLIC_staging = true
CLOUDRUN_PUBLIC_prod = true

# Service Cloud Run d'éval (mode batch/CLI exécuté à la demande, tourne en
# continu avec min-instances=1 — cf. `make gcp_up`/`gcp_down`,
# docs/evaluation/execution-benchmark.md pour pourquoi). "-mocked" : rappel
# volontaire que le pipeline Berlue exécuté dedans est encore
# RandomBerluePipeline, pas HurluBerlu (cf. docs/evaluation/run.md).
# Renommer une fois le vrai pipeline branché.
GAR_EVAL_SERVICE_IMAGE = berlue-eval-mocked-service
CLOUDRUN_EVAL_SERVICE = berlue-eval-mocked-service

# Service Cloud Run Ollama, appelé par le service d'éval en mode
# généré, API) — cf. Dockerfile.llm, docs/gcp/infra-gpu.md.
# GPU L4, coûte dès le premier appel (~0,67 $/h) : jamais de min-instances
# permanent sans confirmation explicite, toujours redescendre à 0 ou
# supprimer après un test.
GAR_LLM_IMAGE = berlue-llm
CLOUDRUN_LLM_SERVICE = berlue-llm

# --- BigQuery ---
# ⚠️ Doit rester identique à BQ_DATASET dans berlue/params.py (utilisée des deux
# côtés : make/bigquery.mk en shell, berlue/ml_logic/data.py en Python).
BQ_DATASET = berlue

# --- Prefect ---
# ⚠️ Idem : doit rester identique à PREFECT_LOG_LEVEL dans berlue/params.py.
PREFECT_LOG_LEVEL = INFO
