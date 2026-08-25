# ==============================================================================
# 🦙 OLLAMA (LLM LOCAL)
# ==============================================================================

ollama_setup: ## Installe Ollama en local, démarre le serveur et lance les tests post-install (check_ollama.sh)
	@bash scripts/setup_ollama.sh

ollama_check: ## Vérifie qu'Ollama fonctionne et utilise bien le GPU (et pas seulement le CPU)
	@bash scripts/check_ollama.sh

ollama_bench: ## Détecte la VRAM du GPU et compare les 3 meilleurs modèles Llama/Qwen/Gemma/Mistral en dessous de cette limite
	@bash scripts/check_ollama.sh --bench

ollama_perf: ## Mesure précisément latence/débit (tokens/s) sur la même sélection top-3/famille, via l'API Ollama
	@bash scripts/check_ollama.sh --perf
