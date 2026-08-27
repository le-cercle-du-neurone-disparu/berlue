# ==============================================================================
# CLIENT OLLAMA — usage direct (nécessite Ollama en local, cf. docs/ollama-setup.md)
# ==============================================================================

# Surchargeables : `make llm_generate PROMPT="..."`, `make llm_generate_many K=5`.
PROMPT ?= Pourquoi le ciel est bleu ?
K ?= 3

llm_generate: ## Une génération unique via OllamaClient (PROMPT surchargeable)
	python -m berlue.llm.client "$(PROMPT)"

llm_generate_many: ## K générations indépendantes à températures espacées (PROMPT, K surchargeables)
	python -m berlue.llm.client "$(PROMPT)" --k $(K)
