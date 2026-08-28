# ==============================================================================
# CLIENT OLLAMA — usage direct (nécessite Ollama en local, cf. docs/setup/ollama-setup.md)
# ==============================================================================

# Surchargeables : `make llm_generate PROMPT="..."`, `make llm_generate_many K=5`.
PROMPT ?= Pourquoi le ciel est bleu ?
K ?= 3

llm_generate: ## Smoke-test OllamaClient (auto-détecte serveur/modèle, question fixe)
	python -m berlue.llm.client "$(PROMPT)"

llm_generate_many: ## Idem llm_generate (le script ne lit pas sys.argv)
	python -m berlue.llm.client "$(PROMPT)" --k $(K)
