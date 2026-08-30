# ==============================================================================
# COMMANDES CLOUD RUN
# ==============================================================================
# 3 environnements (test/staging/prod), même projet GCP, 3 services Cloud Run
# nommés $(GAR_IMAGE)-<env>, déployés depuis la même image :prod (build une
# fois via docker_build_prod/docker_push_prod, promotion progressive
# test -> staging -> prod). Sélection via CLOUDRUN_ENV=test|staging|prod
# (défaut test — jamais lu depuis .env, volontairement, pour ne pas risquer un
# déploiement accidentel vers le mauvais environnement).

CLOUDRUN_ENV ?= test

cloudrun_enable_api: gcp_check_cli_auth ## Active l'API Cloud Run pour le projet
	@echo "⚙️ Activation de l'API Cloud Run..."
	gcloud services enable run.googleapis.com --project=$(GCP_PROJECT)

# Compte de service attaché au déploiement — surchargeable (ex. revenir au SA
# par défaut du projet : `make cloudrun_deploy CLOUDRUN_SERVICE_ACCOUNT=`).
# Prérequis : make iam_setup_cloudrun_service_account (une fois, cf. gcp_setup).
CLOUDRUN_SERVICE_ACCOUNT ?= $(CLOUDRUN_SA_EMAIL)

cloudrun_deploy: gcp_check_cli_auth ## Déploie sur Cloud Run selon CLOUDRUN_ENV=test|staging|prod (défaut test)
	@echo "🚀 Déploiement de $(GAR_IMAGE)-$(CLOUDRUN_ENV) sur Cloud Run (accès public : $(CLOUDRUN_PUBLIC_$(CLOUDRUN_ENV)))..."
	gcloud run deploy $(GAR_IMAGE)-$(CLOUDRUN_ENV) \
		--image $(GCP_REGION)-docker.pkg.dev/$(GCP_PROJECT)/$(ARTIFACTSREPO)/$(GAR_IMAGE):prod \
		--memory $(GAR_MEMORY) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		$(if $(CLOUDRUN_SERVICE_ACCOUNT),--service-account=$(CLOUDRUN_SERVICE_ACCOUNT),) \
		$(if $(filter true,$(CLOUDRUN_PUBLIC_$(CLOUDRUN_ENV))),--allow-unauthenticated,--no-allow-unauthenticated)

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
# JOB CLOUD RUN — ÉVAL (image berlue-eval-mocked, cf. Dockerfile.eval)
# ==============================================================================
# Un seul Job (pas de notion test/staging/prod, c'est un batch exécuté à la
# demande) — build/push de l'image : make docker_build_eval docker_push_eval.

cloudrun_eval_deploy: gcp_check_cli_auth ## Crée ou met à jour le Job Cloud Run d'éval
	@echo "🚀 Déploiement du Job $(CLOUDRUN_EVAL_JOB)..."
	gcloud run jobs deploy $(CLOUDRUN_EVAL_JOB) \
		--image $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_EVAL_IMAGE):latest \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--service-account=$(CLOUDRUN_SA_EMAIL) \
		--set-env-vars=GCP_PROJECT=$(GCP_PROJECT),BERLUE_EVAL_STORE_TARGET=gcp,BERLUE_EVAL_RUN_TARGET=gcp

# Mêmes variables scope que evaluate_model/evaluate_model_generated
# (make/pipeline.mk) — MODE=dataset|generated remplace le choix de cible
# locale, MATRIX=true construit la matrice au lieu de remplir le cache.
MODE ?= dataset
MATRIX ?= false
WARMUP ?= false

cloudrun_eval_run: gcp_check_cli_auth ## Exécute le Job d'éval sur GCP (DATASET/RATIO/MODEL_ID/... comme evaluate_model, + MODE=dataset|generated, MATRIX=true|false, WARMUP=true|false)
	@ENV_VARS="BERLUE_JOB_DATASET=$(DATASET),BERLUE_JOB_RATIO=$(RATIO),BERLUE_JOB_MODEL_ID=$(MODEL_ID),BERLUE_JOB_PIPELINE_VERSION=$(PIPELINE_VERSION),BERLUE_JOB_GENERATION_VERSION=$(GENERATION_VERSION),BERLUE_JOB_EVAL_VERSION=$(EVAL_VERSION),BERLUE_JOB_MODE=$(MODE),BERLUE_JOB_START=$(START)"; \
	if [ -n "$(END)" ]; then ENV_VARS="$$ENV_VARS,BERLUE_JOB_END=$(END)"; fi; \
	if [ "$(MODE)" = "generated" ]; then \
		LLM_URL=$$(gcloud run services describe $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)"); \
		ENV_VARS="$$ENV_VARS,BERLUE_JOB_JUDGE_MODEL=$(JUDGE_MODEL),BERLUE_OLLAMA_HOST=$$LLM_URL"; \
		if [ "$(WARMUP)" = "true" ]; then ENV_VARS="$$ENV_VARS,BERLUE_JOB_WARMUP=true"; fi; \
	fi; \
	if [ "$(MATRIX)" = "true" ]; then ENV_VARS="$$ENV_VARS,BERLUE_JOB_MATRIX=true"; fi; \
	echo "🚀 Exécution de $(CLOUDRUN_EVAL_JOB) (dataset=$(DATASET), model_id=$(MODEL_ID), mode=$(MODE), matrix=$(MATRIX))..."; \
	gcloud run jobs execute $(CLOUDRUN_EVAL_JOB) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--wait \
		--update-env-vars="$$ENV_VARS"

cloudrun_eval_baseline: gcp_check_cli_auth ## Exécute la baseline NLI seule (mode dataset) sur GCP, sur DATASET/RATIO
	@echo "🚀 Exécution de $(CLOUDRUN_EVAL_JOB) (baseline, dataset=$(DATASET), ratio=$(RATIO))..."
	gcloud run jobs execute $(CLOUDRUN_EVAL_JOB) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--wait \
		--update-env-vars="BERLUE_JOB_DATASET=$(DATASET),BERLUE_JOB_RATIO=$(RATIO),BERLUE_JOB_BASELINE=true"

cloudrun_eval_baseline_generated: gcp_check_cli_auth ## Exécute la baseline NLI (mode généré) sur GCP, sur les réponses déjà générées [START:END]
	@ENV_VARS="BERLUE_JOB_DATASET=$(DATASET),BERLUE_JOB_RATIO=$(RATIO),BERLUE_JOB_MODEL_ID=$(MODEL_ID),BERLUE_JOB_GENERATION_VERSION=$(GENERATION_VERSION),BERLUE_JOB_EVAL_VERSION=$(EVAL_VERSION),BERLUE_JOB_MODE=generated,BERLUE_JOB_BASELINE_GENERATED=true,BERLUE_JOB_START=$(START)"; \
	if [ -n "$(END)" ]; then ENV_VARS="$$ENV_VARS,BERLUE_JOB_END=$(END)"; fi; \
	echo "🚀 Exécution de $(CLOUDRUN_EVAL_JOB) (baseline mode généré, dataset=$(DATASET), model_id=$(MODEL_ID))..."; \
	gcloud run jobs execute $(CLOUDRUN_EVAL_JOB) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--wait \
		--update-env-vars="$$ENV_VARS"

cloudrun_eval_baseline_generated_matrix: gcp_check_cli_auth ## Construit/stocke sur GCP la matrice baseline-vs-juge seule (ne dépend pas du verdict Berlue) — échoue si incomplet
	@echo "🚀 Exécution de $(CLOUDRUN_EVAL_JOB) (matrice baseline mode généré, dataset=$(DATASET), model_id=$(MODEL_ID))..."
	gcloud run jobs execute $(CLOUDRUN_EVAL_JOB) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--wait \
		--update-env-vars="BERLUE_JOB_DATASET=$(DATASET),BERLUE_JOB_RATIO=$(RATIO),BERLUE_JOB_MODEL_ID=$(MODEL_ID),BERLUE_JOB_GENERATION_VERSION=$(GENERATION_VERSION),BERLUE_JOB_EVAL_VERSION=$(EVAL_VERSION),BERLUE_JOB_MODE=generated,BERLUE_JOB_BASELINE_GENERATED=true,BERLUE_JOB_MATRIX=true,BERLUE_JOB_JUDGE_MODEL=$(JUDGE_MODEL)"

cloudrun_eval_list: ## Liste les Jobs Cloud Run actifs du projet
	@echo "📋 Listing des Jobs Cloud Run..."
	gcloud run jobs list --project $(GCP_PROJECT) --region $(GCP_REGION)

cloudrun_eval_logs: ## Logs des exécutions du Job d'éval (dernières en premier)
	@echo "📜 Logs de $(CLOUDRUN_EVAL_JOB)..."
	gcloud run jobs logs read $(CLOUDRUN_EVAL_JOB) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--limit 100

cloudrun_eval_delete: ## Supprime le Job Cloud Run d'éval
	@echo "🗑️ Suppression du Job $(CLOUDRUN_EVAL_JOB)..."
	gcloud run jobs delete $(CLOUDRUN_EVAL_JOB) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--quiet

# ==============================================================================
# SERVICE CLOUD RUN — OLLAMA (GPU, cf. Dockerfile.llm)
# ==============================================================================
# ⚠️ Coûte dès le premier appel (~0,67 $/h, GPU L4 en europe-west1) — pas de
# min-instances par défaut (scale-to-zero), à ne changer qu'en connaissance
# de cause. Toujours redescendre à 0 instance (cloudrun_llm_scale_to_zero)
# ou supprimer (cloudrun_llm_delete) après un test.

cloudrun_llm_deploy: gcp_check_cli_auth ## Crée ou met à jour le service Ollama (GPU L4, privé — IAM requis pour l'appeler)
	@echo "🚀 Déploiement de $(CLOUDRUN_LLM_SERVICE) (GPU L4)..."
	gcloud run deploy $(CLOUDRUN_LLM_SERVICE) \
		--image $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_LLM_IMAGE):latest \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--gpu=1 \
		--gpu-type=nvidia-l4 \
		--no-gpu-zonal-redundancy \
		--cpu=4 \
		--memory=16Gi \
		--concurrency=4 \
		--set-env-vars=OLLAMA_NUM_PARALLEL=4 \
		--max-instances=1 \
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
