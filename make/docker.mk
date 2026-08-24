# ==============================================================================
# DOCKER & ARTIFACT REGISTRY COMMANDS
# ==============================================================================

docker_build_local: ## Build the Docker image locally for testing
	@echo "🐳 Building local Docker image $(GAR_IMAGE):dev..."
	docker build \
		--build-arg DOCKER_BASE_IMAGE=$(DOCKER_BASE_IMAGE) \
		--build-arg PACKAGE_NAME=$(PACKAGE_NAME) \
		--tag=$(GAR_IMAGE):dev .

docker_run_local: ## Run the local Docker container on port 8080
	@echo "🏃‍♂️ Running container $(GAR_IMAGE):dev..."
	@echo "👉 Go to http://localhost:8080"
	docker run -it \
		--env-file .env \
		-p 8000:8000 \
		$(GAR_IMAGE):dev

artifact_registry_create: ## Create the Docker repository in Artifact Registry
	@echo "📦 Creating Artifact Registry repository $(ARTIFACTSREPO)..."
	gcloud artifacts repositories create $(ARTIFACTSREPO) \
		--repository-format=docker \
		--location=$(GCP_REGION) \
		--description="Docker repository $(ARTIFACTSREPO) for project $(GCP_PROJECT)" \
		--project=$(GCP_PROJECT) || true

artifact_registry_role: ## Grant yourself permission to push to Artifact Registry
	@echo "🔐 Adding Artifact Registry Writer role to your account..."
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
		--member="user:$$(gcloud config get-value account)" \
		--role="roles/artifactregistry.writer"

docker_auth: ## Configure Docker to authenticate with Google Cloud
	@echo "🔑 Configuring Docker authentication for GCP..."
	gcloud auth configure-docker $(GCP_REGION)-docker.pkg.dev --quiet

docker_build_prod: ## Build the Docker image for production (linux/amd64)
	@echo "🏗️ Building production image..."
	docker build \
		--platform linux/amd64 \
		--build-arg DOCKER_BASE_IMAGE=$(DOCKER_BASE_IMAGE) \
		--build-arg PACKAGE_NAME=$(PACKAGE_NAME) \
		-t $(GCP_REGION)-docker.pkg.dev/$(GCP_PROJECT)/$(ARTIFACTSREPO)/$(GAR_IMAGE):prod \
		.

docker_push_prod: ## Push the production image to Artifact Registry
	@echo "🚀 Pushing image to Artifact Registry..."
	docker push $(GCP_REGION)-docker.pkg.dev/$(GCP_PROJECT)/$(ARTIFACTSREPO)/$(GAR_IMAGE):prod
