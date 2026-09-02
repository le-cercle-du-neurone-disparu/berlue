# ==============================================================================
# COMMANDES CLOUD RUN
# ==============================================================================
# 3 environnements (test/staging/prod), même projet GCP, 3 services Cloud Run
# nommés $(GAR_IMAGE)-<env>, déployés depuis la même image :prod (build une
# fois via docker_build_prod/docker_push_prod, promotion progressive
# test -> staging -> prod). Sélection via CLOUDRUN_ENV=test|staging|prod
# (défaut test). Absent de .env.sample volontairement : c'est une décision par
# commande, pas un réglage personnel. Ce n'est qu'une convention, pas un
# verrou — `?=` laisse gagner une valeur venue de .env ou d'un `export` du
# shell, vérifié. Passer CLOUDRUN_ENV explicitement en ligne de commande
# reste le seul usage sur lequel compter.

CLOUDRUN_ENV ?= test

# Règle commune aux 3 services : jamais plus d'une instance (le budget prime
# sur le débit), rien de garanti chaud au déploiement.
#
# Le plafond se règle à DEUX niveaux distincts dans Cloud Run, et il faut les
# deux : --max-instances porte sur la révision, --max sur le service (« across
# all revisions »). C'est --max que la console affiche dans « Scaling: Auto
# (Min, Max) » — sans lui elle annonce 3 alors que la révision est bien
# plafonnée à 1, ce qui rend le garde-fou budget illisible.
#
# Seuls gcp_up/gcp_eval_up montent min-instances à 1, le temps d'une session ;
# gcp_down supprime les services.

cloudrun_enable_api: gcp_check_cli_auth ## Active l'API Cloud Run pour le projet
	@echo "⚙️ Activation de l'API Cloud Run..."
	gcloud services enable run.googleapis.com --project=$(GCP_PROJECT) </dev/null

# Compte de service attaché au déploiement — surchargeable (ex. revenir au SA
# par défaut du projet : `make cloudrun_deploy CLOUDRUN_SERVICE_ACCOUNT=`).
# Prérequis : make iam_setup_cloudrun_service_account (une fois, cf. gcp_setup).
CLOUDRUN_SERVICE_ACCOUNT ?= $(CLOUDRUN_SA_EMAIL)

# Le volume GCS FUSE (--add-volume type=cloud-storage) peut exiger
# --execution-environment=gen2 selon la version de gcloud/Cloud Run au
# moment du premier vrai déploiement — jamais testé contre un projet réel,
# à ajouter ici si `gcloud run deploy` le réclame.
# Un service qui monte l'index RAG doit d'abord vérifier qu'il existe dans le
# bucket : sans lui le conteneur ne boote pas (API) ou casse au premier appel
# (service d'éval), avec l'erreur enfouie dans les logs Cloud Run après
# plusieurs minutes d'attente. Prérequis de cloudrun_deploy et
# cloudrun_eval_service_deploy, jamais appelé directement.
rag_index_check:
	@gcloud storage ls gs://$(RAG_BUCKET_NAME)/faiss/$(RAG_CORPUS_VERSION)/index.faiss >/dev/null 2>&1 </dev/null || { \
		echo "❌ Index RAG introuvable : gs://$(RAG_BUCKET_NAME)/faiss/$(RAG_CORPUS_VERSION)/index.faiss"; \
		echo "   Versions présentes dans le bucket :"; \
		gcloud storage ls gs://$(RAG_BUCKET_NAME)/faiss/ 2>/dev/null </dev/null | sed -e 's#.*/faiss/#     #' -e 's#/$$##' || echo "     (aucune)"; \
		echo "   👉 construire et publier le corpus attendu (chemin normal) :"; \
		echo "      make download_fever_data_full && make build_fever_index && make rag_index_upload"; \
		echo "   👉 ou, pour un test ponctuel sur un corpus déjà publié :"; \
		echo "      make <cible> RAG_CORPUS_VERSION=<version ci-dessus>"; \
		exit 1; \
	}

cloudrun_deploy: gcp_check_cli_auth rag_index_check ## Déploie sur Cloud Run selon CLOUDRUN_ENV=test|staging|prod (défaut test) — câble berlue-llm (BERLUE_OLLAMA_HOST) et l'index RAG (volume GCS FUSE, RAG_CORPUS_VERSION)
	@$(MAKE) --no-print-directory _code_version_check
	@$(MAKE) --no-print-directory _models_check
	@echo "🚀 Déploiement de $(GAR_IMAGE)-$(CLOUDRUN_ENV) sur Cloud Run (accès public : $(CLOUDRUN_PUBLIC_$(CLOUDRUN_ENV)))..."
	@LLM_URL=$$(gcloud run services describe $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)" 2>/dev/null </dev/null); \
	if [ -z "$$LLM_URL" ]; then \
		echo "❌ $(CLOUDRUN_LLM_SERVICE) introuvable — l'API partirait avec BERLUE_OLLAMA_HOST vide."; \
		echo "   👉 make cloudrun_llm_deploy (ou make gcp_deploy, qui respecte l'ordre)"; \
		exit 1; \
	fi; \
	gcloud run deploy $(GAR_IMAGE)-$(CLOUDRUN_ENV) \
		--image $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_RUNTIME_IMAGE):prod \
		--memory $(GAR_MEMORY) \
		--cpu $(GAR_CPU) \
		--timeout=$(GAR_TIMEOUT) \
		--min-instances=0 \
		--max-instances=1 \
		--max=1 \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		$(if $(CLOUDRUN_SERVICE_ACCOUNT),--service-account=$(CLOUDRUN_SERVICE_ACCOUNT),) \
		--add-volume=name=rag,type=cloud-storage,bucket=$(RAG_BUCKET_NAME) \
		--add-volume-mount=volume=rag,mount-path=/mnt/rag \
		--add-volume=name=code,type=cloud-storage,bucket=$(CODE_BUCKET_NAME) \
		--add-volume-mount=volume=code,mount-path=/mnt/code \
		--add-volume=name=models,type=cloud-storage,bucket=$(MODELS_BUCKET_NAME) \
		--add-volume-mount=volume=models,mount-path=/mnt/models \
		--update-env-vars=BERLUE_OLLAMA_HOST=$$LLM_URL,RAG_VECTOR_DB_PATH=/mnt/rag/faiss/$(RAG_CORPUS_VERSION),BERLUE_APP_MODULE=$(BERLUE_API_MODULE),BERLUE_CODE_DIR=/mnt/code/$(CODE_VERSION),HF_HOME=/mnt/models,HF_HUB_OFFLINE=1 \
		$(if $(filter true,$(CLOUDRUN_PUBLIC_$(CLOUDRUN_ENV))),--allow-unauthenticated,--no-allow-unauthenticated)

# Accès par personne sur les services Cloud Run du projet. CLOUDRUN_ROLE =
# viewer (consulter services, révisions et logs — défaut) ou operator
# (roles/run.developer : déployer ET supprimer, donc lancer gcp_deploy et
# gcp_down). Pas de rôle GCP prédéfini qui donnerait la suppression sans le
# déploiement — les deux vont ensemble.
CLOUDRUN_ROLE ?= viewer

cloudrun_grant: ## Donne l'accès à une personne sur les services Cloud Run (USER=email requis, CLOUDRUN_ROLE=viewer|operator, défaut viewer)
	@if [ -z "$(USER)" ]; then \
		echo "❌ ERREUR : USER manquant."; \
		echo "👉 Essayez : make cloudrun_grant USER=personne@example.com CLOUDRUN_ROLE=operator"; \
		exit 1; \
	fi
	@echo "🔐 Ajout de l'accès Cloud Run '$(CLOUDRUN_ROLE)' pour $(USER) sur $(GCP_PROJECT)..."
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
		--member="user:$(USER)" \
		--role="roles/run.$(if $(filter operator,$(CLOUDRUN_ROLE)),developer,viewer)" \
		--condition=None \
		--quiet </dev/null

cloudrun_revoke: ## Retire l'accès d'une personne sur les services Cloud Run (USER=email requis, CLOUDRUN_ROLE doit correspondre au rôle accordé)
	@if [ -z "$(USER)" ]; then \
		echo "❌ ERREUR : USER manquant."; \
		echo "👉 Essayez : make cloudrun_revoke USER=personne@example.com CLOUDRUN_ROLE=operator"; \
		exit 1; \
	fi
	@echo "🔓 Retrait de l'accès Cloud Run '$(CLOUDRUN_ROLE)' pour $(USER) sur $(GCP_PROJECT)..."
	gcloud projects remove-iam-policy-binding $(GCP_PROJECT) \
		--member="user:$(USER)" \
		--role="roles/run.$(if $(filter operator,$(CLOUDRUN_ROLE)),developer,viewer)" \
		--condition=None \
		--quiet </dev/null

cloudrun_list: ## Liste tous les services Cloud Run actifs du projet
	@echo "📋 Listing des services Cloud Run..."
	gcloud run services list --project $(GCP_PROJECT)

cloudrun_url: ## Récupère l'URL de l'environnement CLOUDRUN_ENV=test|staging|prod (défaut test)
	@echo "🌍 $(GAR_IMAGE)-$(CLOUDRUN_ENV) est en ligne à :"
	@gcloud run services describe $(GAR_IMAGE)-$(CLOUDRUN_ENV) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--format "value(status.url)"

cloudrun_logs: ## Suit les logs de l'environnement CLOUDRUN_ENV=test|staging|prod (défaut test)
	@echo "📜 Suivi des logs pour $(GAR_IMAGE)-$(CLOUDRUN_ENV)... (Ctrl+C pour arrêter)"
	gcloud run services logs read $(GAR_IMAGE)-$(CLOUDRUN_ENV) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--limit 50

cloudrun_delete: ## Supprime l'environnement CLOUDRUN_ENV=test|staging|prod (défaut test) et le met hors ligne
	@echo "🗑️ Suppression du service Cloud Run $(GAR_IMAGE)-$(CLOUDRUN_ENV)..."
	gcloud run services delete $(GAR_IMAGE)-$(CLOUDRUN_ENV) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--quiet

# ==============================================================================
# INDEX RAG (bucket GCS dédié — cf. RAG_BUCKET_NAME dans config.mk — monté en
# volume GCS FUSE par cloudrun_deploy)
# ==============================================================================
# Construit à part (make build_fever_index en local), jamais reconstruit au
# docker build : le ré-embedding du corpus complet est trop coûteux pour
# tourner à chaque déploiement de code, cf. claude-doc/plan-deploiement-api-gcp.md.
# RAG_CORPUS_VERSION identifie le sous-dossier actif du bucket
# (gs://$(RAG_BUCKET_NAME)/faiss/<version>/) — changer de corpus = changer
# cette valeur puis `make cloudrun_deploy`, sans toucher à l'image.
# Le corpus complet est le défaut parce que c'est ce qui tourne la plupart du
# temps ; un corpus réduit ne sert qu'à un test ponctuel, en surchargeant
# explicitement la variable.
RAG_CORPUS_VERSION ?= full-145k

rag_bucket_create: gcp_check_cli_auth ## Crée le bucket GCS dédié à l'index RAG s'il n'existe pas déjà (dans BUCKET_PROJECT) — appelé par gcp_setup, doit rester rejouable sans erreur
	@if gcloud storage buckets describe gs://$(RAG_BUCKET_NAME) --project=$(BUCKET_PROJECT) >/dev/null 2>&1 </dev/null; then \
		echo "✅ Bucket gs://$(RAG_BUCKET_NAME) déjà présent, création sautée."; \
	else \
		echo "🪣 Création du bucket gs://$(RAG_BUCKET_NAME)..."; \
		$(RETRY) "création du bucket gs://$(RAG_BUCKET_NAME)" \
			gcloud storage buckets create gs://$(RAG_BUCKET_NAME) \
				--location=$(GCP_REGION) \
				--project=$(BUCKET_PROJECT); \
	fi

rag_bucket_grant_sa: gcp_check_cli_auth ## Autorise sa-berlue à lire le bucket RAG — requis par le volume GCS FUSE de cloudrun_deploy
	@echo "🔐 Lecture pour $(CLOUDRUN_SA_EMAIL) sur gs://$(RAG_BUCKET_NAME)..."
	@$(RETRY) "autorisation de $(CLOUDRUN_SA_EMAIL) sur gs://$(RAG_BUCKET_NAME)" \
		gcloud storage buckets add-iam-policy-binding gs://$(RAG_BUCKET_NAME) \
			--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
			--role="roles/storage.objectViewer"

rag_bucket_delete: ## Supprime le bucket RAG et tout son contenu (appelé par gcp_destroy)
	@echo "💣 Suppression du bucket gs://$(RAG_BUCKET_NAME)..."
	gcloud storage rm --recursive gs://$(RAG_BUCKET_NAME)

rag_index_upload: gcp_check_cli_auth ## Upload l'index FAISS local (data/fever/faiss, cf. make build_fever_index) vers gs://RAG_BUCKET_NAME/faiss/RAG_CORPUS_VERSION
	@if [ ! -f data/fever/faiss/index.faiss ]; then \
		echo "❌ data/fever/faiss/index.faiss introuvable — lance d'abord make build_fever_index."; \
		exit 1; \
	fi
	@echo "☁️  Upload vers gs://$(RAG_BUCKET_NAME)/faiss/$(RAG_CORPUS_VERSION)..."
	gcloud storage cp -r data/fever/faiss/* gs://$(RAG_BUCKET_NAME)/faiss/$(RAG_CORPUS_VERSION)/
	@echo "✅ Index disponible sur gs://$(RAG_BUCKET_NAME)/faiss/$(RAG_CORPUS_VERSION)/ — assure-toi que RAG_CORPUS_VERSION=$(RAG_CORPUS_VERSION) au prochain cloudrun_deploy pour le brancher."

# ==============================================================================
# SERVICE CLOUD RUN — ÉVAL (image $(GAR_RUNTIME_IMAGE), commune avec l'API)
# ==============================================================================
# Service qui reste en vie entre deux appels (min-instances basculé par
# gcp_eval_up/gcp_down) plutôt qu'un conteneur neuf par exécution : le
# scheduling Cloud Run et les imports Python tiers sont ainsi payés une fois
# par instance et non à chaque run — mesures dans
# docs/evaluation/execution-benchmark.md. Un seul endpoint `/invoke` —
# `berlue/api/eval_service.py`, mêmes flags que la CLI en JSON.

# Mêmes variables scope que evaluate_model/evaluate_model_generated
# (make/pipeline.mk) — MODE=dataset|generated remplace le choix de cible
# locale, MATRIX=true construit la matrice au lieu de remplir le cache.
MODE ?= dataset
MATRIX ?= false
WARMUP ?= false
BASELINE ?= false
COVERAGE ?= false

# Ressources et modèles du service d'éval. Depuis que `run_eval` construit un
# vrai `BerluePipeline` (et non plus le mock), ce service charge en mémoire
# l'index FAISS, le NLI de SelfCheckGPT et le modèle d'embedding : les défauts
# Cloud Run (512 Mio / 1 vCPU) ne suffisent pas.
# Le service d'éval n'a pas de GPU : SelfCheckNLI (DeBERTa-large, 435M
# paramètres, K passages par affirmation), l'embedding des affirmations et la
# recherche FAISS exhaustive tournent tous sur ces vCPU. Le GPU de berlue-llm
# étant facturé pendant tout ce temps, un vCPU d'éval supplémentaire (~0,024
# $/h) est très vite rentable face au L4 (~0,67 $/h) qui attend.
EVAL_MEMORY ?= 8Gi
EVAL_CPU ?= 8
# Le mode dataset est séquentiel (pas de --concurrency côté éval) : une tranche
# de quelques centaines de lignes dépasse les 900s par défaut. Maximum Cloud
# Run : 3600.
EVAL_TIMEOUT ?= 3600
# Modèles réellement appelés par le pipeline sur le service — à ne pas
# confondre avec MODEL_ID, qui n'est qu'une étiquette de scope en mode dataset.
# Vides = les défauts de berlue/params.py s'appliquent (pas de valeur dupliquée
# ici, qui dériverait).
EVAL_SELFCHECK_MODEL ?=
EVAL_EXTRACT_MODEL ?=
EVAL_RAG_MODEL ?=

# Partage désormais l'image applicative de l'API : les deux ne diffèrent que par
# BERLUE_APP_MODULE, servi par le même entrypoint.
cloudrun_eval_service_deploy: gcp_check_cli_auth rag_index_check ## Crée ou met à jour le service Cloud Run d'éval (même image que l'API, cf. BERLUE_APP_MODULE) — monte l'index RAG (RAG_CORPUS_VERSION) ; EVAL_SELFCHECK_MODEL/EVAL_EXTRACT_MODEL/EVAL_RAG_MODEL pour choisir les modèles du pipeline
	@$(MAKE) --no-print-directory _code_version_check
	@$(MAKE) --no-print-directory _models_check
	@echo "🚀 Déploiement du service $(CLOUDRUN_EVAL_SERVICE) ($(EVAL_CPU) vCPU/$(EVAL_MEMORY), corpus $(RAG_CORPUS_VERSION))..."
	gcloud run deploy $(CLOUDRUN_EVAL_SERVICE) \
		--image $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_RUNTIME_IMAGE):prod \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--service-account=$(CLOUDRUN_SA_EMAIL) \
		--cpu=$(EVAL_CPU) \
		--memory=$(EVAL_MEMORY) \
		--min-instances=0 \
		--max-instances=1 \
		--max=1 \
		--concurrency=1 \
		--timeout=$(EVAL_TIMEOUT) \
		--add-volume=name=rag,type=cloud-storage,bucket=$(RAG_BUCKET_NAME) \
		--add-volume-mount=volume=rag,mount-path=/mnt/rag \
		--add-volume=name=code,type=cloud-storage,bucket=$(CODE_BUCKET_NAME) \
		--add-volume-mount=volume=code,mount-path=/mnt/code \
		--add-volume=name=models,type=cloud-storage,bucket=$(MODELS_BUCKET_NAME) \
		--add-volume-mount=volume=models,mount-path=/mnt/models \
		--update-env-vars=HF_HOME=/mnt/models,HF_HUB_OFFLINE=1,GCP_PROJECT=$(GCP_PROJECT),BERLUE_EVAL_STORE_TARGET=gcp,BERLUE_EVAL_RUN_TARGET=gcp,BERLUE_APP_MODULE=$(BERLUE_EVAL_MODULE),BERLUE_CODE_DIR=/mnt/code/$(CODE_VERSION),RAG_VECTOR_DB_PATH=/mnt/rag/faiss/$(RAG_CORPUS_VERSION)$(if $(EVAL_SELFCHECK_MODEL),$(comma)BERLUE_OLLAMA_MODEL=$(EVAL_SELFCHECK_MODEL),)$(if $(EVAL_EXTRACT_MODEL),$(comma)EXTRACT_MODEL=$(EVAL_EXTRACT_MODEL),)$(if $(EVAL_RAG_MODEL),$(comma)RAG_MODEL=$(EVAL_RAG_MODEL),) \
		--no-allow-unauthenticated
	@echo "🔐 Autorise sa-berlue à appeler ce service (run.invoker)..."
	gcloud run services add-iam-policy-binding $(CLOUDRUN_EVAL_SERVICE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
		--role="roles/run.invoker" \
		--condition=None

cloudrun_eval_service_delete: ## Supprime le service Cloud Run d'éval (appelé par gcp_destroy)
	@echo "🗑️ Suppression de $(CLOUDRUN_EVAL_SERVICE)..."
	gcloud run services delete $(CLOUDRUN_EVAL_SERVICE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--quiet

cloudrun_eval_service_url: ## Affiche l'URL du service Cloud Run d'éval
	@gcloud run services describe $(CLOUDRUN_EVAL_SERVICE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--format "value(status.url)"

cloudrun_eval_service_logs: ## Logs du service Cloud Run d'éval
	@echo "📜 Logs de $(CLOUDRUN_EVAL_SERVICE)..."
	gcloud run services logs read $(CLOUDRUN_EVAL_SERVICE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--limit 100

cloudrun_eval_service_invoke: gcp_check_cli_auth ## Appelle /invoke sur le service d'éval (mêmes variables que evaluate_model/evaluate_model_generated, dont PIPELINE_VERSION/GENERATION_VERSION/EVAL_VERSION) — nécessite gcp_eval_up au préalable
	@URL=$$(gcloud run services describe $(CLOUDRUN_EVAL_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)"); \
	TOKEN=$$(gcloud auth print-identity-token --impersonate-service-account=$(CLOUDRUN_SA_EMAIL) --audiences=$$URL); \
	BODY=$$(python3 -c "import json,os; print(json.dumps({k: v for k, v in {'dataset': os.environ.get('DATASET'), 'ratio': float(os.environ['RATIO']) if os.environ.get('RATIO') else None, 'model_id': os.environ.get('MODEL_ID'), 'pipeline_version': os.environ.get('PIPELINE_VERSION'), 'generation_version': os.environ.get('GENERATION_VERSION'), 'eval_version': os.environ.get('EVAL_VERSION'), 'start': int(os.environ['START']) if os.environ.get('START') else None, 'end': int(os.environ['END']) if os.environ.get('END') else None, 'mode': os.environ.get('MODE'), 'judge_model': os.environ.get('JUDGE_MODEL'), 'matrix': os.environ.get('MATRIX') == 'true', 'warmup': os.environ.get('WARMUP') == 'true', 'baseline': os.environ.get('BASELINE') == 'true', 'coverage': os.environ.get('COVERAGE') == 'true', 'concurrency': int(os.environ['CONCURRENCY']) if os.environ.get('CONCURRENCY') else None}.items() if v is not None}))" \
		DATASET="$(DATASET)" RATIO="$(RATIO)" MODEL_ID="$(MODEL_ID)" PIPELINE_VERSION="$(PIPELINE_VERSION)" GENERATION_VERSION="$(GENERATION_VERSION)" EVAL_VERSION="$(EVAL_VERSION)" START="$(START)" END="$(END)" MODE="$(MODE)" JUDGE_MODEL="$(JUDGE_MODEL)" MATRIX="$(MATRIX)" WARMUP="$(WARMUP)" BASELINE="$(BASELINE)" COVERAGE="$(COVERAGE)" CONCURRENCY="$(CONCURRENCY)"); \
	echo "🚀 POST $$URL/invoke : $$BODY"; \
	curl -sf -X POST "$$URL/invoke" -H "Authorization: Bearer $$TOKEN" -H "Content-Type: application/json" -d "$$BODY" \
	| python3 -m json.tool

# `eval_version` réservé, jamais utilisé pour un vrai run — c'est le seul des
# 3 axes de version qui filtre TOUTES les tables (mode 1 et mode 2, cf.
# docs/evaluation/storage.md), donc le seul sur lequel une purge peut
# s'appuyer sans risque de déborder sur une vraie donnée même si on ne
# précise pas les autres filtres.
WARMUP_CHECK_EVAL_VERSION = warmup-check

gcp_verify_warm: gcp_check_cli_auth ## Preuve qu'un MODEL_ID/JUDGE_MODEL tournent vraiment sur berlue-llm (pas juste un cache Firestore déjà rempli) — purge un tag réservé puis force 1 vrai appel généré+jugé. Nécessite gcp_eval_up (+ WARM_MODELS) au préalable.
	@echo "🧹 Purge du tag réservé eval_version=$(WARMUP_CHECK_EVAL_VERSION) (model_id=$(MODEL_ID))..."
	@BERLUE_EVAL_STORE_TARGET=gcp GCP_PROJECT=$(GCP_PROJECT) python -m berlue.evaluation.run_eval \
		--purge --purge-dataset $(DATASET) --purge-ratio $(RATIO) --purge-model-id $(MODEL_ID) \
		--purge-judge-model $(JUDGE_MODEL) --purge-eval-version $(WARMUP_CHECK_EVAL_VERSION) > /dev/null
	@URL=$$(gcloud run services describe $(CLOUDRUN_EVAL_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)"); \
	TOKEN=$$(gcloud auth print-identity-token --impersonate-service-account=$(CLOUDRUN_SA_EMAIL) --audiences=$$URL); \
	echo "🔍 1 appel garanti frais (dataset=$(DATASET), model_id=$(MODEL_ID), judge=$(JUDGE_MODEL))..."; \
	curl -sf -X POST "$$URL/invoke" -H "Authorization: Bearer $$TOKEN" -H "Content-Type: application/json" \
		-d "{\"dataset\":\"$(DATASET)\",\"ratio\":$(RATIO),\"model_id\":\"$(MODEL_ID)\",\"judge_model\":\"$(JUDGE_MODEL)\",\"eval_version\":\"$(WARMUP_CHECK_EVAL_VERSION)\",\"mode\":\"generated\",\"start\":0,\"end\":1}" \
	| python3 -m json.tool
	@echo "✅ Si tu vois ça sans erreur : $(MODEL_ID) (génération) et $(JUDGE_MODEL) (juge) ont bien tourné pour de vrai sur berlue-llm — le cache était garanti vide avant l'appel."

# ==============================================================================
# SERVICE CLOUD RUN — OLLAMA (GPU, cf. Dockerfile.llm)
# ==============================================================================
# ⚠️ Coûte dès le premier appel (~0,67 $/h, GPU L4 en europe-west1) — pas de
# min-instances par défaut (scale-to-zero), à ne changer qu'en connaissance
# de cause. Toujours redescendre à 0 instance (cloudrun_llm_scale_to_zero)
# ou supprimer (cloudrun_llm_delete) après un test.

# Défauts = config de prod actuelle (alignés, cf. infra-gpu.md) — surchargeables
# pour un test de parallélisme ponctuel, ex. `make cloudrun_llm_deploy
# LLM_NUM_PARALLEL=32 LLM_CONTEXT_LENGTH=1024`. Toujours revenir aux défauts
# après un test (redéployer sans les surcharger) pour ne pas laisser la prod
# sur une config expérimentale. LLM_CPU/LLM_MEMORY : 8 vCPU / 32 Gi est le
# **plafond dur** pour 1 GPU sur Cloud Run (`.08-1, 1, 2, 4, 6, 8` seules
# valeurs de CPU acceptées avec `--gpu=1` — vérifié, `gcloud` refuse tout
# le reste avec une erreur de validation explicite), pas juste une
# recommandation — inutile de tenter plus haut.
LLM_NUM_PARALLEL ?= 4
LLM_CONCURRENCY ?= 4
LLM_CONTEXT_LENGTH ?=
# 8, le plafond : le chargement d'un modèle de 14 B en profite, et c'est la config
# de référence documentée (8 vCPU / 32 Gi).
LLM_CPU ?= 8
# 32 Gi et non 16 : un modèle de 14 B occupe ~12 Go une fois chargé (constaté le
# 01/09 avec qwen2.5:14b, « model runner has unexpectedly stopped » à 16 Gi), et on
# en charge un second à côté. scripts/ollama_memory_check.sh vérifie après coup.
LLM_MEMORY ?= 32Gi
# Une virgule littérale dans un argument de $(if ...) serait lue comme le
# séparateur then/else de $(if) lui-même — passer par une variable l'évite.
comma := ,

cloudrun_llm_deploy: gcp_check_cli_auth ## Crée ou met à jour le service Ollama (GPU L4, privé — IAM requis pour l'appeler) ; LLM_NUM_PARALLEL/LLM_CONCURRENCY/LLM_CONTEXT_LENGTH/LLM_CPU/LLM_MEMORY pour un test de parallélisme
	@echo "🚀 Déploiement de $(CLOUDRUN_LLM_SERVICE) (GPU L4, NUM_PARALLEL=$(LLM_NUM_PARALLEL), $(LLM_CPU) vCPU/$(LLM_MEMORY))..."
	gcloud run deploy $(CLOUDRUN_LLM_SERVICE) \
		--image $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_LLM_IMAGE):latest \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--gpu=1 \
		--gpu-type=nvidia-l4 \
		--no-gpu-zonal-redundancy \
		--cpu=$(LLM_CPU) \
		--memory=$(LLM_MEMORY) \
		--concurrency=$(LLM_CONCURRENCY) \
		--set-env-vars=OLLAMA_NUM_PARALLEL=$(LLM_NUM_PARALLEL)$(if $(LLM_CONTEXT_LENGTH),$(comma)OLLAMA_CONTEXT_LENGTH=$(LLM_CONTEXT_LENGTH),) \
		--min-instances=0 \
		--max-instances=1 \
		--max=1 \
		--timeout=600 \
		--port=11434 \
		--no-allow-unauthenticated
	@echo "🔐 Autorise sa-berlue à appeler ce service (run.invoker)..."
	gcloud run services add-iam-policy-binding $(CLOUDRUN_LLM_SERVICE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
		--role="roles/run.invoker" \
		--condition=None

cloudrun_llm_url: ## Affiche l'URL du service Ollama
	@gcloud run services describe $(CLOUDRUN_LLM_SERVICE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--format "value(status.url)"

# Gestion explicite de ce qui occupe la VRAM de berlue-llm. `Dockerfile.llm`
# fixe OLLAMA_KEEP_ALIVE=-1 (un modèle chargé ne se décharge jamais tout seul)
# et OLLAMA_MAX_LOADED_MODELS vaut 3 sur un L4 unique : au-delà de 3 modèles,
# Ollama évince tout seul et paie un rechargement (11-35s mesuré) en pleine
# exécution — le déclencheur décrit dans docs/gcp/infra-gpu.md. Enchaîner
# plusieurs runs sur des tailles de modèle différentes demande donc de
# décharger explicitement, plutôt que de subir l'éviction.
llm_models_ps: gcp_check_cli_auth ## Liste les modèles actuellement chargés en VRAM sur berlue-llm (et leur échéance)
	@URL=$$(gcloud run services describe $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)"); \
	TOKEN=$$(gcloud auth print-identity-token --impersonate-service-account=$(CLOUDRUN_SA_EMAIL) --audiences=$$URL); \
	curl -sf "$$URL/api/ps" -H "Authorization: Bearer $$TOKEN" | python3 -m json.tool

llm_model_load: gcp_check_cli_auth ## Charge MODEL en VRAM sur berlue-llm et l'y épingle (req : MODEL=nom:tag)
	@if [ -z "$(MODEL)" ]; then echo "❌ MODEL manquant. 👉 make llm_model_load MODEL=qwen2.5:14b"; exit 1; fi
	@URL=$$(gcloud run services describe $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)"); \
	TOKEN=$$(gcloud auth print-identity-token --impersonate-service-account=$(CLOUDRUN_SA_EMAIL) --audiences=$$URL); \
	echo "⬇️  Pull de $(MODEL) si absent du disque..."; \
	curl -sf -X POST "$$URL/api/pull" -H "Authorization: Bearer $$TOKEN" -H "Content-Type: application/json" -d "{\"name\":\"$(MODEL)\",\"stream\":false}" > /dev/null; \
	echo "🔥 Chargement de $(MODEL) en VRAM (keep_alive=-1)..."; \
	curl -sf -X POST "$$URL/api/generate" -H "Authorization: Bearer $$TOKEN" -H "Content-Type: application/json" -d "{\"model\":\"$(MODEL)\",\"keep_alive\":-1}" > /dev/null; \
	echo "✅ $(MODEL) chargé et épinglé."; \
	bash scripts/ollama_memory_check.sh "$$URL" "$$TOKEN" "$(LLM_MEMORY)" "$(MODEL)"

llm_model_unload: gcp_check_cli_auth ## Décharge MODEL de la VRAM de berlue-llm sans le supprimer du disque (req : MODEL=nom:tag)
	@if [ -z "$(MODEL)" ]; then echo "❌ MODEL manquant. 👉 make llm_model_unload MODEL=qwen2.5:14b"; exit 1; fi
	@URL=$$(gcloud run services describe $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)"); \
	TOKEN=$$(gcloud auth print-identity-token --impersonate-service-account=$(CLOUDRUN_SA_EMAIL) --audiences=$$URL); \
	echo "🧯 Déchargement de $(MODEL) (keep_alive=0)..."; \
	curl -sf -X POST "$$URL/api/generate" -H "Authorization: Bearer $$TOKEN" -H "Content-Type: application/json" -d "{\"model\":\"$(MODEL)\",\"keep_alive\":0}" > /dev/null; \
	echo "✅ $(MODEL) déchargé (toujours sur disque, rechargement sans re-pull)."

ollama_load_test_gcp: gcp_check_cli_auth ## Stress-test de charge sur berlue-llm (cf. scripts/ollama_load_test.py) — nécessite le service déjà chaud (make gcp_up ou gcp_eval_up, WARM_MODELS="...")
	@URL=$$(gcloud run services describe $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)"); \
	TOKEN=$$(gcloud auth print-identity-token --impersonate-service-account=$(CLOUDRUN_SA_EMAIL) --audiences=$$URL); \
	OLLAMA_HOST=$$URL AUTH_TOKEN=$$TOKEN python scripts/ollama_load_test.py

cloudrun_llm_logs: ## Logs du service Ollama
	@echo "📜 Logs de $(CLOUDRUN_LLM_SERVICE)..."
	gcloud run services logs read $(CLOUDRUN_LLM_SERVICE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--limit 100

cloudrun_llm_scale_to_zero: ## Force 0 instance minimum sur le service Ollama (sécurité budget, idempotent)
	@echo "🧯 Passage de $(CLOUDRUN_LLM_SERVICE) à min-instances=0..."
	gcloud run services update $(CLOUDRUN_LLM_SERVICE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--min-instances=0

cloudrun_llm_delete: ## Supprime le service Ollama (arrête définitivement toute facturation GPU liée)
	@echo "🗑️ Suppression de $(CLOUDRUN_LLM_SERVICE)..."
	gcloud run services delete $(CLOUDRUN_LLM_SERVICE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--quiet

# ==============================================================================
# DÉPLOIEMENT GROUPÉ
# ==============================================================================
# Ordre imposé, pas un choix de présentation : cloudrun_deploy lit l'URL de
# $(CLOUDRUN_LLM_SERVICE) pour câbler BERLUE_OLLAMA_HOST sur l'API — le LLM
# doit donc exister avant. Le service d'éval est indépendant des deux.
#
# Seule l'API est déclinée par environnement ($(GAR_IMAGE)-<env>, CLOUDRUN_ENV) :
# le service d'éval et le service Ollama sont uniques pour le projet, partagés
# par les 3 environnements. `CLOUDRUN_ENV=staging` ne crée donc pas un second
# berlue-llm, il redéploie seulement l'API dans staging.

cloudrun_deploy_all: gcp_check_cli_auth ## Déploie les 3 services (Ollama, éval, API selon CLOUDRUN_ENV=test|staging|prod) depuis les images déjà poussées, dans l'ordre imposé
	@echo "🚀 Déploiement des services Cloud Run (CLOUDRUN_ENV=$(CLOUDRUN_ENV))..."
	@$(MAKE) --no-print-directory cloudrun_llm_deploy
	@$(MAKE) --no-print-directory cloudrun_eval_service_deploy
	@$(MAKE) --no-print-directory cloudrun_deploy
	@echo "✅ Services déployés — tous à min-instances=0 (aucun coût tant qu'on ne les allume pas)."
	@echo "   👉 make gcp_up (produit) ou make gcp_eval_up (éval) pour les monter et les préchauffer."

# ==============================================================================
# CYCLE DE VIE — gcp_up / gcp_eval_up / gcp_down
# ==============================================================================
# Deux usages, deux cibles d'allumage, un seul extincteur :
#
#   gcp_up       berlue-api-<env> + berlue-llm     (produit : Aletheia -> API -> LLM)
#   gcp_eval_up  berlue-eval      + berlue-llm     (évaluation : /invoke -> LLM)
#   gcp_down     les 3 à min-instances=0
#
# berlue-llm est commun aux deux (les deux chemins appellent le LLM) et il est
# monté dans les deux cas : c'est le GPU L4, ~0,67 $/h dès la première
# seconde. WARM_MODELS ne décide donc pas SI le GPU s'allume, seulement quels
# modèles y sont tirés et chargés en VRAM d'avance.
#
# Les trois cibles passent par scripts/cloudrun_set_min.sh : un service pas
# encore déployé est ignoré avec un avertissement, jamais une erreur qui
# empêcherait de traiter les suivants — côté gcp_down, un service non traité
# reste allumé, donc facturé.
# ⚠️ Coûte tant que c'est en l'air — ne pas oublier gcp_down.

WARM_MODELS ?=

cloudrun_llm_up: gcp_check_cli_auth ## Monte berlue-llm (GPU L4, coûteux) et charge WARM_MODELS en VRAM — brique commune à gcp_up et gcp_eval_up
	@# Vérifier l'existence AVANT d'annoncer la facturation : sinon la commande
	@# alarme sur un coût qu'elle n'a pas déclenché.
	@gcloud run services describe $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)" >/dev/null 2>&1 </dev/null || { \
		echo "❌ $(CLOUDRUN_LLM_SERVICE) n'est pas déployé. Lancez : make gcp_deploy"; \
		exit 1; \
	}
	@echo "🔥 $(CLOUDRUN_LLM_SERVICE) (GPU L4 — facturé dès maintenant)..."
	@$(CLOUDRUN_SET_MIN) $(CLOUDRUN_LLM_SERVICE) 1
	@LLM_URL=$$(gcloud run services describe $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)" 2>/dev/null </dev/null); \
	LLM_TOKEN=$$(gcloud auth print-identity-token --impersonate-service-account=$(CLOUDRUN_SA_EMAIL) --audiences=$$LLM_URL); \
	echo "⏳ Attente que $(CLOUDRUN_LLM_SERVICE) réponde..."; \
	for i in $$(seq 1 60); do \
		CODE=$$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $$LLM_TOKEN" "$$LLM_URL/api/tags"); \
		[ "$$CODE" = "200" ] && break; \
		sleep 2; \
	done; \
	echo "✅ $(CLOUDRUN_LLM_SERVICE) prêt ($$LLM_URL)."; \
	if [ -z "$(WARM_MODELS)" ]; then \
		echo "ℹ️  WARM_MODELS vide : aucun modèle préchargé — le premier appel généré paiera le chargement en VRAM."; \
	fi
	@$(MAKE) --no-print-directory llm_warm

# Préchauffe WARM_MODELS sur un berlue-llm DÉJÀ monté, sans toucher au
# min-instances : c'est le geste à part quand on change de modèles sans vouloir
# relancer un gcp_up complet. Appelé aussi par cloudrun_llm_up.
llm_warm: gcp_check_cli_auth ## Pull + charge WARM_MODELS="m1 m2" en VRAM sur berlue-llm (service déjà monté ; n'allume rien)
	@LLM_URL=$$(gcloud run services describe $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)" 2>/dev/null </dev/null); \
	if [ -z "$$LLM_URL" ]; then \
		echo "❌ $(CLOUDRUN_LLM_SERVICE) n'est pas déployé. Lancez : make gcp_deploy"; \
		exit 1; \
	fi; \
	if [ -z "$(WARM_MODELS)" ]; then \
		echo "ℹ️  WARM_MODELS vide — rien à préchauffer. Ex. : make llm_warm WARM_MODELS=\"phi3:14b llama3.2:3b\""; \
		exit 0; \
	fi; \
	LLM_TOKEN=$$(gcloud auth print-identity-token --impersonate-service-account=$(CLOUDRUN_SA_EMAIL) --audiences=$$LLM_URL); \
	for MODEL in $(WARM_MODELS); do \
		echo "⬇️  Pull + warmup de $$MODEL sur $(CLOUDRUN_LLM_SERVICE)..."; \
		curl -sf -X POST "$$LLM_URL/api/pull" -H "Authorization: Bearer $$LLM_TOKEN" -H "Content-Type: application/json" -d "{\"name\":\"$$MODEL\",\"stream\":false}" > /dev/null; \
		curl -sf -X POST "$$LLM_URL/api/generate" -H "Authorization: Bearer $$LLM_TOKEN" -H "Content-Type: application/json" -d "{\"model\":\"$$MODEL\",\"prompt\":\"hi\",\"stream\":false}" > /dev/null; \
		echo "✅ $$MODEL chaud."; \
		bash scripts/ollama_memory_check.sh "$$LLM_URL" "$$LLM_TOKEN" "$(LLM_MEMORY)" "$$MODEL" || exit 1; \
	done

gcp_up: cloudrun_llm_up ## Monte berlue-api-<env> ET berlue-llm à min-instances=1 (usage produit) ; WARM_MODELS="m1 m2" pour précharger des modèles
	@LLM_URL=$$(gcloud run services describe $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)" 2>/dev/null </dev/null); \
	echo "🔥 gcp_up : min-instances=1 + BERLUE_OLLAMA_HOST=$$LLM_URL sur $(GAR_IMAGE)-$(CLOUDRUN_ENV)..."; \
	$(CLOUDRUN_SET_MIN) $(GAR_IMAGE)-$(CLOUDRUN_ENV) 1 --update-env-vars=BERLUE_OLLAMA_HOST=$$LLM_URL
	@API_URL=$$(gcloud run services describe $(GAR_IMAGE)-$(CLOUDRUN_ENV) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)" 2>/dev/null </dev/null); \
	if [ -z "$$API_URL" ]; then \
		echo "⚠️  $(GAR_IMAGE)-$(CLOUDRUN_ENV) pas déployé — rien à préchauffer côté API."; \
	else \
		echo "⏳ Attente que $(GAR_IMAGE)-$(CLOUDRUN_ENV) réponde sur /..."; \
		for i in $$(seq 1 60); do \
			CODE=$$(curl -s -o /dev/null -w "%{http_code}" "$$API_URL/"); \
			[ "$$CODE" = "200" ] && break; \
			sleep 2; \
		done; \
		echo "✅ $(GAR_IMAGE)-$(CLOUDRUN_ENV) prêt ($$API_URL) — sentence-transformers chargé, plus de téléchargement HuggingFace au prochain /predict."; \
	fi
	@echo "✅ gcp_up terminé — /predict prêt à l'emploi."

gcp_eval_up: cloudrun_llm_up ## Monte berlue-eval ET berlue-llm à min-instances=1 (usage évaluation) et préchauffe le split DATASET/RATIO ; WARM_MODELS="m1 m2" pour précharger des modèles
	@LLM_URL=$$(gcloud run services describe $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)" 2>/dev/null </dev/null); \
	echo "🔥 gcp_eval_up : min-instances=1 + BERLUE_OLLAMA_HOST=$$LLM_URL sur $(CLOUDRUN_EVAL_SERVICE)..."; \
	$(CLOUDRUN_SET_MIN) $(CLOUDRUN_EVAL_SERVICE) 1 --update-env-vars=BERLUE_OLLAMA_HOST=$$LLM_URL
	@EVAL_URL=$$(gcloud run services describe $(CLOUDRUN_EVAL_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)" 2>/dev/null </dev/null); \
	if [ -z "$$EVAL_URL" ]; then \
		echo "⚠️  $(CLOUDRUN_EVAL_SERVICE) pas déployé — préchauffage du split sauté."; \
	else \
		EVAL_TOKEN=$$(gcloud auth print-identity-token --impersonate-service-account=$(CLOUDRUN_SA_EMAIL) --audiences=$$EVAL_URL); \
		echo "⏳ Attente que $(CLOUDRUN_EVAL_SERVICE) réponde sur /health..."; \
		for i in $$(seq 1 60); do \
			CODE=$$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $$EVAL_TOKEN" "$$EVAL_URL/health"); \
			[ "$$CODE" = "200" ] && break; \
			sleep 2; \
		done; \
		echo "✅ $(CLOUDRUN_EVAL_SERVICE) prêt ($$EVAL_URL)."; \
		echo "📦 Préchauffe le split dataset=$(DATASET) ratio=$(RATIO) (chargement + split, mis en cache par process — cf. run_eval._cached_split)..."; \
		curl -sf -X POST "$$EVAL_URL/invoke" -H "Authorization: Bearer $$EVAL_TOKEN" -H "Content-Type: application/json" \
			-d "{\"dataset\":\"$(DATASET)\",\"ratio\":$(RATIO),\"coverage\":true}" > /dev/null; \
		echo "✅ Split $(DATASET)/$(RATIO) chaud."; \
	fi
	@echo "✅ gcp_eval_up terminé — cloudrun_eval_service_invoke prêt à l'emploi."

# gcp_down supprime les trois services plutôt que de les redescendre à
# min-instances=0 : c'est le seul arrêt garanti de la facturation. Cloud Run
# ne tue pas une instance déjà démarrée quand min-instances repasse à 0 —
# elle passe idle et survit largement (mesuré : bien au-delà de 3 min), et
# sur berlue-llm une instance idle facture plein tarif (le GPU impose CPU
# toujours alloué).
#
# Ce que la suppression NE coûte pas, vérifié en conditions réelles :
#   - l'historique des métriques reste consultable dans la console Cloud Run
#     après recréation sous le même nom ;
#   - l'URL du service est identique après recréation (même nom, même projet,
#     même région) — rien à reconfigurer côté Aletheia.
# Recréer les services ne rebuilde aucune image : `make cloudrun_deploy_all`,
# ~3-4 min, les images restant dans Artifact Registry.

gcp_down: gcp_check_cli_auth ## Supprime les 3 services Cloud Run — seul arrêt garanti de la facturation ; les recréer ne rebuilde rien (make cloudrun_deploy_all)
	@echo "🧯 gcp_down : suppression de $(CLOUDRUN_EVAL_SERVICE), $(CLOUDRUN_LLM_SERVICE) et $(GAR_IMAGE)-$(CLOUDRUN_ENV)..."
	@$(CLOUDRUN_DELETE) $(CLOUDRUN_EVAL_SERVICE)
	@$(CLOUDRUN_DELETE) $(CLOUDRUN_LLM_SERVICE)
	@$(CLOUDRUN_DELETE) $(GAR_IMAGE)-$(CLOUDRUN_ENV)
	@echo "✅ gcp_down terminé — plus rien ne facture. Recréation : make cloudrun_deploy_all."

gcp_status: ## Affiche, pour chaque service, min-instances (configuration) ET le nombre d'instances réellement en vie (facturées) — les deux ne disent pas la même chose
	@echo "📊 État (CLOUDRUN_ENV=$(CLOUDRUN_ENV)) — min-instances = configuration, instances = réellement en vie :"
	@for SVC in $(CLOUDRUN_EVAL_SERVICE) $(CLOUDRUN_LLM_SERVICE) $(GAR_IMAGE)-$(CLOUDRUN_ENV); do \
		MIN=$$(gcloud run services describe $$SVC --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/minScale'])" 2>/dev/null </dev/null) \
			|| { echo "  $$SVC : non déployé"; continue; }; \
		LIVE=$$(bash scripts/cloudrun_instances.sh $$SVC); \
		echo "  $$SVC : min-instances=$${MIN:-0}, instances en vie=$$LIVE"; \
	done
