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
# SERVICE CLOUD RUN — ÉVAL (image berlue-eval-mocked-service, cf. Dockerfile.eval-service)
# ==============================================================================
# Tourne en continu (min-instances flip via gcp_up/gcp_down) plutôt qu'un
# conteneur neuf par exécution — remplace l'ancien Job (`berlue-eval-mocked`,
# déprécié : cf. docs/evaluation/execution-benchmark.md pour la mesure qui a
# motivé ce choix — ~65% du temps d'un run Job était du scheduling Cloud Run
# Jobs pur, ~21% des imports Python tiers, les deux payés une seule fois par
# instance ici au lieu de à chaque exécution). Un seul endpoint `/invoke` —
# `berlue/api/eval_service.py`, mêmes flags que la CLI en JSON.

# Mêmes variables scope que evaluate_model/evaluate_model_generated
# (make/pipeline.mk) — MODE=dataset|generated remplace le choix de cible
# locale, MATRIX=true construit la matrice au lieu de remplir le cache.
MODE ?= dataset
MATRIX ?= false
WARMUP ?= false
BASELINE ?= false
COVERAGE ?= false

cloudrun_eval_service_deploy: gcp_check_cli_auth ## Crée ou met à jour le service Cloud Run d'éval
	@echo "🚀 Déploiement du service $(CLOUDRUN_EVAL_SERVICE)..."
	gcloud run deploy $(CLOUDRUN_EVAL_SERVICE) \
		--image $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_EVAL_SERVICE_IMAGE):latest \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--service-account=$(CLOUDRUN_SA_EMAIL) \
		--max-instances=1 \
		--concurrency=1 \
		--timeout=900 \
		--update-env-vars=GCP_PROJECT=$(GCP_PROJECT),BERLUE_EVAL_STORE_TARGET=gcp,BERLUE_EVAL_RUN_TARGET=gcp \
		--no-allow-unauthenticated
	@echo "🔐 Autorise sa-berlue à appeler ce service (run.invoker)..."
	gcloud run services add-iam-policy-binding $(CLOUDRUN_EVAL_SERVICE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
		--role="roles/run.invoker" \
		--condition=None

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

cloudrun_eval_service_invoke: gcp_check_cli_auth ## Appelle /invoke sur le service d'éval (mêmes variables que evaluate_model/evaluate_model_generated, dont PIPELINE_VERSION/GENERATION_VERSION/EVAL_VERSION) — nécessite gcp_up au préalable
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

gcp_verify_warm: gcp_check_cli_auth ## Preuve qu'un MODEL_ID/JUDGE_MODEL tournent vraiment sur berlue-llm (pas juste un cache Firestore déjà rempli) — purge un tag réservé puis force 1 vrai appel généré+jugé. Nécessite gcp_up (+ WARM_MODELS) au préalable.
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
# sur une config expérimentale.
LLM_NUM_PARALLEL ?= 4
LLM_CONCURRENCY ?= 4
LLM_CONTEXT_LENGTH ?=
# Une virgule littérale dans un argument de $(if ...) serait lue comme le
# séparateur then/else de $(if) lui-même — passer par une variable l'évite.
comma := ,

cloudrun_llm_deploy: gcp_check_cli_auth ## Crée ou met à jour le service Ollama (GPU L4, privé — IAM requis pour l'appeler) ; LLM_NUM_PARALLEL/LLM_CONCURRENCY/LLM_CONTEXT_LENGTH pour un test de parallélisme
	@echo "🚀 Déploiement de $(CLOUDRUN_LLM_SERVICE) (GPU L4, NUM_PARALLEL=$(LLM_NUM_PARALLEL))..."
	gcloud run deploy $(CLOUDRUN_LLM_SERVICE) \
		--image $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_LLM_IMAGE):latest \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--gpu=1 \
		--gpu-type=nvidia-l4 \
		--no-gpu-zonal-redundancy \
		--cpu=4 \
		--memory=16Gi \
		--concurrency=$(LLM_CONCURRENCY) \
		--set-env-vars=OLLAMA_NUM_PARALLEL=$(LLM_NUM_PARALLEL)$(if $(LLM_CONTEXT_LENGTH),$(comma)OLLAMA_CONTEXT_LENGTH=$(LLM_CONTEXT_LENGTH),) \
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

ollama_load_test_gcp: gcp_check_cli_auth ## Stress-test de charge sur berlue-llm (cf. scripts/ollama_load_test.py) — nécessite le service déjà chaud (make gcp_up WARM_MODELS="...")
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
# CYCLE DE VIE — gcp_up / gcp_down
# ==============================================================================
# Monte et préchauffe berlue-eval (+ berlue-llm si WARM_MODELS est fourni),
# à lancer une fois en début de session avant une série de
# cloudrun_eval_service_invoke ; gcp_down redescend tout en fin de session.
# ⚠️ Coûte tant que c'est en l'air (GPU L4 si WARM_MODELS non vide) — ne pas
# oublier gcp_down.

WARM_MODELS ?=

gcp_up: gcp_check_cli_auth ## Monte et préchauffe berlue-eval (+ berlue-llm si WARM_MODELS="modele1 modele2 ...")
	@if [ -n "$(WARM_MODELS)" ]; then \
		echo "🔥 gcp_up : min-instances=1 sur $(CLOUDRUN_LLM_SERVICE)..."; \
		gcloud run services update $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --min-instances=1; \
		LLM_URL=$$(gcloud run services describe $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)"); \
		LLM_TOKEN=$$(gcloud auth print-identity-token --impersonate-service-account=$(CLOUDRUN_SA_EMAIL) --audiences=$$LLM_URL); \
		echo "⏳ Attente que $(CLOUDRUN_LLM_SERVICE) réponde..."; \
		for i in $$(seq 1 60); do \
			CODE=$$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $$LLM_TOKEN" "$$LLM_URL/api/tags"); \
			[ "$$CODE" = "200" ] && break; \
			sleep 2; \
		done; \
		echo "✅ $(CLOUDRUN_LLM_SERVICE) prêt ($$LLM_URL)."; \
		for MODEL in $(WARM_MODELS); do \
			echo "⬇️  Pull + warmup de $$MODEL sur $(CLOUDRUN_LLM_SERVICE)..."; \
			curl -sf -X POST "$$LLM_URL/api/pull" -H "Authorization: Bearer $$LLM_TOKEN" -H "Content-Type: application/json" -d "{\"name\":\"$$MODEL\",\"stream\":false}" > /dev/null; \
			curl -sf -X POST "$$LLM_URL/api/generate" -H "Authorization: Bearer $$LLM_TOKEN" -H "Content-Type: application/json" -d "{\"model\":\"$$MODEL\",\"prompt\":\"hi\",\"stream\":false}" > /dev/null; \
			echo "✅ $$MODEL chaud."; \
		done; \
		echo "🔥 gcp_up : min-instances=1 + BERLUE_OLLAMA_HOST=$$LLM_URL sur $(CLOUDRUN_EVAL_SERVICE)..."; \
		gcloud run services update $(CLOUDRUN_EVAL_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --min-instances=1 --update-env-vars=BERLUE_OLLAMA_HOST=$$LLM_URL; \
	else \
		echo "🔥 gcp_up : min-instances=1 sur $(CLOUDRUN_EVAL_SERVICE)..."; \
		gcloud run services update $(CLOUDRUN_EVAL_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --min-instances=1; \
	fi
	@EVAL_URL=$$(gcloud run services describe $(CLOUDRUN_EVAL_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)"); \
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
	echo "✅ Split $(DATASET)/$(RATIO) chaud."
	@echo "✅ gcp_up terminé — cloudrun_eval_service_invoke prêt à l'emploi."

gcp_down: gcp_check_cli_auth ## Redescend berlue-eval et berlue-llm à min-instances=0 (sécurité budget, idempotent, inconditionnel)
	@echo "🧯 gcp_down : min-instances=0 sur $(CLOUDRUN_EVAL_SERVICE) et $(CLOUDRUN_LLM_SERVICE)..."
	gcloud run services update $(CLOUDRUN_EVAL_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --min-instances=0
	gcloud run services update $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --min-instances=0
	@echo "✅ gcp_down terminé."
