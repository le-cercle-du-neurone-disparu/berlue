# ==============================================================================
# COMMANDES DU PIPELINE ML
# ==============================================================================

# Surchargeable sur la ligne de commande : `make run_train MODEL_TARGET=gcs`.
MODEL_TARGET ?= local

run_preprocess: ## Lance l'étape de prétraitement
	python -c 'from berlue.interface.main import preprocess; preprocess()'

run_train: ## Lance l'étape d'entraînement (MODEL_TARGET=local|gcs|mlflow, défaut local)
	python -c 'from berlue.interface.main import train; train()'

run_evaluate: ## Lance l'étape d'évaluation (MODEL_TARGET=local|gcs|mlflow, défaut local)
	python -c 'from berlue.interface.main import evaluate; evaluate()'

run_pred: ## Lance l'étape de prédiction (MODEL_TARGET=local|gcs|mlflow, défaut local)
	python -c 'from berlue.interface.main import pred; pred()'

run_all: run_preprocess run_train run_evaluate run_pred ## Lance le pipeline complet (preprocess train evaluate pred)

run_api_local: ## Lance l'application FastAPI en local avec rechargement à chaud
	@echo "🚀 Démarrage de FastAPI en local..."
	uvicorn berlue.api.fast:app --host 0.0.0.0 --port 8000 --reload

run_api: ## Lance l'API selon RUN_ENV=local|docker|gcp (github : pas encore configuré, tâche à part)
ifeq ($(RUN_ENV),local)
	@$(MAKE) run_api_local
else ifeq ($(RUN_ENV),docker)
	@$(MAKE) docker_run_local
else ifeq ($(RUN_ENV),gcp)
	@$(MAKE) cloudrun_deploy
else ifeq ($(RUN_ENV),github)
	@echo "⚠️  RUN_ENV=github : pas encore configuré (prévu dans une tâche dédiée)."
	@exit 1
else
	@echo "❌ RUN_ENV doit valoir local, docker ou gcp (github pas encore dispo). Valeur actuelle : '$(RUN_ENV)'"
	@exit 1
endif

run_workflow: ## Lance le workflow d'orchestration Prefect
	PREFECT__LOGGING__LEVEL=$(PREFECT_LOG_LEVEL) python -m berlue.interface.workflow
