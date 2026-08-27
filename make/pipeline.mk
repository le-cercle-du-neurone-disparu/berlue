# ==============================================================================
# COMMANDES DU PIPELINE ML
# ==============================================================================

# Surchargeable sur la ligne de commande : `make run_train MODEL_TARGET=gcs`.
MODEL_TARGET ?= local

# Nombre de lignes récupérées par download_fever_data_small (le fichier complet fait
# ~145k lignes) — surchargeable : `make download_fever_data_small FEVER_SAMPLE_LINES=50000`.
FEVER_SAMPLE_LINES ?= 2000

run_preprocess: ## Lance l'étape de prétraitement
	python -c 'from berlue.interface.main import preprocess; preprocess()'

run_train: ## Lance l'étape d'entraînement (MODEL_TARGET=local|gcs|mlflow, défaut local)
	python -c 'from berlue.interface.main import train; train()'

run_evaluate: ## Lance l'étape d'évaluation (MODEL_TARGET=local|gcs|mlflow, défaut local)
	python -c 'from berlue.interface.main import evaluate; evaluate()'

run_pred: ## Lance l'étape de prédiction (MODEL_TARGET=local|gcs|mlflow, défaut local)
	python -c 'from berlue.interface.main import pred; pred()'

run_all: run_preprocess run_train run_evaluate run_pred ## Lance le pipeline complet (preprocess train evaluate pred)

train_baseline: ## Entraîne le classifieur NLI léger (baseline) et sauvegarde le .joblib localement
	python -m berlue.nli_baseline.train

evaluate_baseline: ## Évalue la baseline NLI seule sur le jeu de test HaluEval/TruthfulQA
	python -m berlue.evaluation.run_eval

download_fever_data_small: ## Télécharge un extrait FEVER pour un test rapide (FEVER_SAMPLE_LINES=2000 par défaut), fever.jsonl pointe dessus
	@echo "⬇️  Téléchargement d'un extrait FEVER ($(FEVER_SAMPLE_LINES) lignes)..."
	@mkdir -p data/fever/raw
	@curl -sL https://fever.ai/download/fever/train.jsonl | head -n $(FEVER_SAMPLE_LINES) > data/fever/raw/fever_small.jsonl
	@ln -sf fever_small.jsonl data/fever/raw/fever.jsonl
	@echo "✅ $$(wc -l < data/fever/raw/fever_small.jsonl) exemples dans data/fever/raw/fever_small.jsonl (fever.jsonl -> fever_small.jsonl)"

download_fever_data_full: ## Télécharge le corpus FEVER complet (~145k lignes), fever.jsonl pointe dessus
	@echo "⬇️  Téléchargement du corpus FEVER complet..."
	@mkdir -p data/fever/raw
	@curl -sL https://fever.ai/download/fever/train.jsonl > data/fever/raw/fever_full.jsonl
	@ln -sf fever_full.jsonl data/fever/raw/fever.jsonl
	@echo "✅ $$(wc -l < data/fever/raw/fever_full.jsonl) exemples dans data/fever/raw/fever_full.jsonl (fever.jsonl -> fever_full.jsonl)"

build_fever_index: ## Construit l'index FAISS du RAG inversé (data/fever/raw/fever.jsonl -> data/fever/faiss/)
	@if [ ! -f data/fever/raw/fever.jsonl ]; then \
		echo "❌ data/fever/raw/fever.jsonl introuvable — lance d'abord make download_fever_data_small (ou _full)."; \
		exit 1; \
	fi
	BERLUE_FEVER_DATA_PATH=data/fever/raw/fever.jsonl python -m berlue.rag.indexer

test_fever_rag: ## Lance le script de test manuel du RAG inversé (berlue/rag/test_rag.py, nécessite build_fever_index au préalable)
	@if [ ! -f data/fever/faiss/index.faiss ]; then \
		echo "❌ data/fever/faiss/index.faiss introuvable — lance d'abord make build_fever_index."; \
		exit 1; \
	fi
	python -m berlue.rag.test_rag

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

# ==============================================================================
# PIPELINE HURLUBERLU (nécessite Ollama en local, cf. docs/ollama-setup.md)
# ==============================================================================

# Surchargeable sur la ligne de commande : `make pipeline_extract QUESTION="..."`.
QUESTION ?= Pourquoi l'eau mouille ?

pipeline_generate: ## Étape 1 seule : génère la réponse brute du LLM
	python -m berlue.pipeline.hurlu_berlu --until generate --question "$(QUESTION)"

pipeline_extract: ## Étapes 1-2 : génère la réponse puis extrait les affirmations
	python -m berlue.pipeline.hurlu_berlu --until extract --question "$(QUESTION)"

pipeline_samples: ## Étapes 1-3 : ajoute l'échantillonnage SelfCheckGPT (K appels LLM)
	python -m berlue.pipeline.hurlu_berlu --until samples --question "$(QUESTION)"

pipeline_selfcheck: ## Pipeline complet jusqu'à SelfCheckGPT (RAG et fusion pas encore implémentés)
	python -m berlue.pipeline.hurlu_berlu --question "$(QUESTION)"
