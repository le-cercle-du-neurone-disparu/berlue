# ==============================================================================
# TESTING COMMANDS
# ==============================================================================

test_all: ## Run all tests in the project
	pytest

test_infrastructure: ## Run sanity checks for GCP setup and credentials
	pytest tests/infrastructure/

test_api_local: ## Run API tests locally (FastAPI in memory)
	pytest tests/api/test_endpoints.py

test_api_docker: ## Run API tests on the local Docker container
	pytest tests/api/test_docker_endpoints.py

test_api_cloud: ## Run API tests on the deployed Cloud Run endpoint
	pytest tests/api/test_cloud_endpoints.py
