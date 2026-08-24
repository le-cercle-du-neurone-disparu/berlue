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

test_api_cloud: ## Run API tests on the deployed Cloud Run endpoint (URL résolue automatiquement via gcloud, cf. cloudrun_url)
	$(eval RESOLVED_SERVICE_URL := $(shell gcloud run services describe $(GAR_IMAGE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format "value(status.url)" 2>/dev/null))
	@if [ -z "$(RESOLVED_SERVICE_URL)" ]; then \
		echo "❌ Impossible de récupérer l'URL Cloud Run (service pas encore déployé ? voir make cloudrun_deploy)"; \
		exit 1; \
	fi
	@echo "🔗 URL Cloud Run résolue : $(RESOLVED_SERVICE_URL)"
	SERVICE_URL=$(RESOLVED_SERVICE_URL) pytest tests/api/test_cloud_endpoints.py

test_api: ## Lance les tests API selon TEST_ENV=local|docker|gcp (github : pas encore configuré, tâche à part)
ifeq ($(TEST_ENV),local)
	@$(MAKE) test_api_local
else ifeq ($(TEST_ENV),docker)
	@$(MAKE) test_api_docker
else ifeq ($(TEST_ENV),gcp)
	@$(MAKE) test_api_cloud
else ifeq ($(TEST_ENV),github)
	@echo "⚠️  TEST_ENV=github : pas encore configuré (prévu dans une tâche dédiée)."
	@exit 1
else
	@echo "❌ TEST_ENV doit valoir local, docker ou gcp (github pas encore dispo). Valeur actuelle : '$(TEST_ENV)'"
	@exit 1
endif
