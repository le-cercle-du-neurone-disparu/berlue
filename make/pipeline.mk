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

evaluate_baseline: ## Évalue la baseline NLI seule (mode dataset) sur DATASET/RATIO
	python -m berlue.evaluation.run_eval --baseline --dataset $(DATASET) --ratio $(RATIO)

# Surchargeables : `make evaluate_model DATASET=halueval RATIO=0.7 MODEL_ID=llama3.2:1b START=100 END=200`.
# Un seul DATASET à la fois — les résultats ne mélangent jamais plusieurs
# datasets, cf. docs/evaluation/storage.md.
DATASET ?= halueval
RATIO ?= 0.8
MODEL_ID ?= random-mock
PIPELINE_VERSION ?= v1
GENERATION_VERSION ?= v1
EVAL_VERSION ?= v1
START ?= 0
END ?=

evaluate_model: ## Remplit le cache d'un scope sur [START:END] avec le pipeline Berlue (mock aujourd'hui)
	python -m berlue.evaluation.run_eval \
		--dataset $(DATASET) --ratio $(RATIO) --model-id $(MODEL_ID) \
		--pipeline-version $(PIPELINE_VERSION) --generation-version $(GENERATION_VERSION) --eval-version $(EVAL_VERSION) \
		--start $(START) $(if $(END),--end $(END),)

evaluate_model_all: ## Remplit tout le cache d'un scope puis construit/stocke sa matrice finale
	@$(MAKE) --no-print-directory evaluate_model START=0 END=
	@$(MAKE) --no-print-directory evaluate_model_matrix

evaluate_model_matrix: ## Construit/stocke la matrice finale d'un scope depuis le cache — échoue si incomplet
	python -m berlue.evaluation.run_eval \
		--dataset $(DATASET) --ratio $(RATIO) --model-id $(MODEL_ID) \
		--pipeline-version $(PIPELINE_VERSION) --generation-version $(GENERATION_VERSION) --eval-version $(EVAL_VERSION) \
		--matrix

evaluate_model_coverage: ## Affiche le total d'éléments d'un scope (pour préparer un découpage START/END) + index déjà en cache/manquants, sans rien calculer — MODE=dataset|generated
	python -m berlue.evaluation.run_eval \
		--dataset $(DATASET) --ratio $(RATIO) --model-id $(MODEL_ID) --mode $(MODE) \
		--pipeline-version $(PIPELINE_VERSION) --generation-version $(GENERATION_VERSION) --eval-version $(EVAL_VERSION) \
		--coverage

# PURGE_SCOPE = all (défaut) | results (5 tables individuelles) | matrices (3 tables)
#            | signals (signaux pré-fusion seuls)
#            | fusion (prédictions + matrice du mode 1, EN GARDANT les signaux :
#                      relancer ensuite evaluate_model_all ne recalcule que la fusion,
#                      RAG et SelfCheck sortant du cache — pour régler les FUSION_*).
PURGE_SCOPE ?= all

evaluate_model_purge: ## Purge le cache filtré par DATASET/RATIO/MODEL_ID/PIPELINE_VERSION/GENERATION_VERSION/EVAL_VERSION/JUDGE_MODEL/PURGE_SCOPE — vide = joker (attention : défauts non vides ci-dessus, blanquer explicitement pour un joker, ex. `make evaluate_model_purge DATASET= RATIO= MODEL_ID= PIPELINE_VERSION= EVAL_VERSION=`)
	python -m berlue.evaluation.run_eval --purge --purge-scope $(PURGE_SCOPE) \
		$(if $(DATASET),--purge-dataset $(DATASET),) \
		$(if $(RATIO),--purge-ratio $(RATIO),) \
		$(if $(MODEL_ID),--purge-model-id $(MODEL_ID),) \
		$(if $(PIPELINE_VERSION),--purge-pipeline-version $(PIPELINE_VERSION),) \
		$(if $(GENERATION_VERSION),--purge-generation-version $(GENERATION_VERSION),) \
		$(if $(EVAL_VERSION),--purge-eval-version $(EVAL_VERSION),) \
		$(if $(JUDGE_MODEL),--purge-judge-model $(JUDGE_MODEL),)

evaluate_explore_results: ## Liste les scopes déjà en cache pour les 5 tables de résultats individuels (local ou GCP selon EVAL_STORE_TARGET)
	PYTHONPATH=. python scripts/explore_eval_store.py --kind results

evaluate_explore_matrices: ## Liste les scopes déjà en cache pour les 3 tables de matrices (local ou GCP selon EVAL_STORE_TARGET)
	PYTHONPATH=. python scripts/explore_eval_store.py --kind matrices

# PUSH_SCOPE = all (défaut) | results (eval_predictions seulement) | matrices.
PUSH_SCOPE ?= all

evaluate_push_to_gcp: ## Pousse un scope (résultats mode 1 et/ou matrices selon PUSH_SCOPE) du store local vers GCP
	PYTHONPATH=. python scripts/push_local_to_gcp.py \
		--dataset $(DATASET) --ratio $(RATIO) --model-id $(MODEL_ID) \
		--pipeline-version $(PIPELINE_VERSION) --generation-version $(GENERATION_VERSION) --eval-version $(EVAL_VERSION) \
		--push-scope $(PUSH_SCOPE)

# Mode 2 (réponse générée + LLM-juge) — surchargeable comme ci-dessus, plus
# JUDGE_MODEL : `make evaluate_model_generated JUDGE_MODEL=llama3.1:8b`.
JUDGE_MODEL ?= qwen2.5:0.5b
# WARMUP=true : précharge generator/judge en VRAM avant de chronométrer la
# boucle — cf. evaluate_model_generated ci-dessous et docs/evaluation/execution-benchmark.md.
WARMUP ?= false
# CONCURRENCY : questions traitées en parallèle au sein de chaque étape — 1
# par défaut (séquentiel). À aligner sur le OLLAMA_NUM_PARALLEL réel du
# serveur ciblé, cf. docs/gcp/ollama-gpu-parallelism.md.
CONCURRENCY ?= 1

evaluate_model_generated: ## Mode généré, Berlue seul : remplit le cache d'un scope sur [START:END] (génération + Berlue + juge, jamais la baseline) ; WARMUP=true précharge les modèles avant de chronométrer ; CONCURRENCY pour paralléliser chaque étape
	python -m berlue.evaluation.run_eval --mode generated \
		--dataset $(DATASET) --ratio $(RATIO) --model-id $(MODEL_ID) \
		--pipeline-version $(PIPELINE_VERSION) --generation-version $(GENERATION_VERSION) --eval-version $(EVAL_VERSION) \
		--judge-model $(JUDGE_MODEL) --start $(START) $(if $(END),--end $(END),) \
		--concurrency $(CONCURRENCY) \
		$(if $(filter true,$(WARMUP)),--warmup,)

evaluate_model_generated_all: ## Mode généré, Berlue seul : remplit tout le cache d'un scope puis construit/stocke sa matrice finale — jamais la baseline (cf. evaluate_model_generated_baseline_all)
	@$(MAKE) --no-print-directory evaluate_model_generated START=0 END=
	@$(MAKE) --no-print-directory evaluate_model_generated_matrix

evaluate_model_generated_baseline_all: ## Mode généré, baseline seule : classifie les réponses déjà générées puis construit/stocke sa matrice finale — jamais Berlue
	@$(MAKE) --no-print-directory evaluate_model_generated_baseline START=0 END=
	@$(MAKE) --no-print-directory evaluate_model_generated_baseline_matrix

evaluate_model_generated_matrix: ## Mode généré, Berlue seul : construit/stocke la matrice Berlue-vs-juge — échoue si incomplet, ne dépend jamais de la baseline
	python -m berlue.evaluation.run_eval --mode generated --matrix \
		--dataset $(DATASET) --ratio $(RATIO) --model-id $(MODEL_ID) \
		--pipeline-version $(PIPELINE_VERSION) --generation-version $(GENERATION_VERSION) --eval-version $(EVAL_VERSION) \
		--judge-model $(JUDGE_MODEL)

evaluate_model_generated_baseline: ## Mode généré, baseline seule : classifie par la baseline NLI les réponses déjà générées sur [START:END] — seul endroit où la baseline mode 2 est calculée (jamais dans evaluate_model_generated)
	python -m berlue.evaluation.run_eval --mode generated --baseline \
		--dataset $(DATASET) --ratio $(RATIO) --model-id $(MODEL_ID) \
		--generation-version $(GENERATION_VERSION) --eval-version $(EVAL_VERSION) \
		--start $(START) $(if $(END),--end $(END),)

evaluate_model_generated_baseline_matrix: ## Mode généré : construit/stocke la matrice baseline-vs-juge, sans dépendre du verdict Berlue — échoue si incomplet
	python -m berlue.evaluation.run_eval --mode generated --baseline --matrix \
		--dataset $(DATASET) --ratio $(RATIO) --model-id $(MODEL_ID) \
		--generation-version $(GENERATION_VERSION) --eval-version $(EVAL_VERSION) \
		--judge-model $(JUDGE_MODEL)

download_halueval_data: ## Télécharge le dataset HaluEval complet (~10k lignes, ~6 Mo) — no-op si déjà présent
	python -c 'from berlue.evaluation.data import download_dataset; from berlue.params import HALUEVAL_URL, HALUEVAL_DATA_PATH; download_dataset(HALUEVAL_URL, HALUEVAL_DATA_PATH)'

download_truthfulqa_data: ## Télécharge le dataset TruthfulQA complet (~790 lignes, ~500 Ko) — no-op si déjà présent
	python -c 'from berlue.evaluation.data import download_dataset; from berlue.params import TRUTHFULQA_URL, TRUTHFULQA_DATA_PATH; download_dataset(TRUTHFULQA_URL, TRUTHFULQA_DATA_PATH)'

download_eval_data: download_halueval_data download_truthfulqa_data ## Télécharge HaluEval + TruthfulQA (les deux jeux utilisés par l'évaluation offline)

ollama_load_test: ## Stress-test de charge sur Ollama local (cf. scripts/ollama_load_test.py pour MODEL/START_THREADS/MAX_THREADS/...) — détermine le CONCURRENCY optimal pour cette machine
	python scripts/ollama_load_test.py

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

test_fever_rag: ## Lance les tests pytest du RAG inversé (tests/test_rag.py, nécessite build_fever_index au préalable)
	@if [ ! -f data/fever/faiss/index.faiss ]; then \
		echo "❌ data/fever/faiss/index.faiss introuvable — lance d'abord make build_fever_index."; \
		exit 1; \
	fi
	pytest tests/test_rag.py -m functional

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
# PIPELINE HURLUBERLU (nécessite Ollama en local, cf. docs/setup/ollama-setup.md)
# ==============================================================================

# Surchargeable sur la ligne de commande : `make pipeline_extract QUESTION="..."`.
QUESTION ?= Pourquoi l'eau mouille ?

pipeline_generate: ## Étape 1 seule : génère la réponse brute du LLM
	python -m berlue.pipeline.hurlu_berlu --until generate --question "$(QUESTION)"

pipeline_extract: ## Étapes 1-2 : génère la réponse puis extrait les affirmations
	python -m berlue.pipeline.hurlu_berlu --until extract --question "$(QUESTION)"

pipeline_samples: ## Étapes 1-3 : ajoute l'échantillonnage SelfCheckGPT (K appels LLM)
	python -m berlue.pipeline.hurlu_berlu --until samples --question "$(QUESTION)"

pipeline_selfcheck: ## Étapes 1-4 : ajoute le score de divergence SelfCheckGPT
	python -m berlue.pipeline.hurlu_berlu --until selfcheck --question "$(QUESTION)"

pipeline_rag: ## Étapes 1-5 : ajoute le RAG
	python -m berlue.pipeline.hurlu_berlu --until rag --question "$(QUESTION)"

pipeline_fusion: ## Étapes 1-6 : ajoute le score de fusion
	python -m berlue.pipeline.hurlu_berlu --question "$(QUESTION)"
