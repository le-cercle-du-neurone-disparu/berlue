# ==============================================================================
# COMMANDES DE TEST
# ==============================================================================

test_all: ## Lance tous les tests du projet (rapides + fonctionnels)
	pytest

test_fast: ## Lance uniquement les tests rapides, sans infra externe (lane CI)
	pytest -m "not functional"

test_functional: ## Lance uniquement les tests fonctionnels (besoin d'une infra réelle : .env, Docker, GCP, modèle entraîné...)
	pytest -m functional
