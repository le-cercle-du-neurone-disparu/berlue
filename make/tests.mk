# ==============================================================================
# COMMANDES DE TEST
# ==============================================================================

test_all: ## Lance tous les tests du projet (rapides + fonctionnels + gcp)
	pytest

test_fast: ## Lance uniquement les tests rapides, sans infra externe (lane CI)
	pytest -m "not functional and not gcp"

test_functional: ## Lance les tests fonctionnels (besoin d'une infra locale réelle : .env, Docker, modèle entraîné...), hors tests gcp
	pytest -m "functional and not gcp"

test_gcp: ## Lance uniquement les tests qui vérifient un vrai environnement GCP (test/staging/prod)
	pytest -m gcp

test_llm_functional: ## Lance les tests fonctionnels du client Ollama (vrai serveur requis, cf. docs/ollama-setup.md)
	pytest tests/test_llm_client.py -m functional -v
