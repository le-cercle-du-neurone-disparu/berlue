# ==============================================================================
# ML PIPELINE COMMANDS
# ==============================================================================

run_preprocess: ## Run the preprocessing step
	python -c 'from berlue.interface.main import preprocess; preprocess()'

run_train: ## Run the training step
	python -c 'from berlue.interface.main import train; train()'

run_evaluate: ## Run the evaluation step
	python -c 'from berlue.interface.main import evaluate; evaluate()'

run_pred: ## Run the prediction step
	python -c 'from berlue.interface.main import pred; pred()'

run_all: run_preprocess run_train run_evaluate run_pred ## Run the full pipeline (preprocess train evaluate pred)

run_api: ## Run the FastAPI application locally with hot-reloading
	@echo "🚀 Starting FastAPI locally..."
	uvicorn berlue.api.fast:app --host 0.0.0.0 --port 8000 --reload

run_workflow: ## Run the Prefect orchestration workflow
	PREFECT__LOGGING__LEVEL=$(PREFECT_LOG_LEVEL) python -m berlue.interface.workflow
