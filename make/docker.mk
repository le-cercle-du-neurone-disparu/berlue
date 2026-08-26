# ==============================================================================
# COMMANDES DOCKER & ARTIFACT REGISTRY
# ==============================================================================

docker_build_local: ## Build l'image Docker localement pour les tests
	@echo "🐳 Build de l'image Docker locale $(GAR_IMAGE):dev..."
	docker build \
		--build-arg DOCKER_BASE_IMAGE=$(DOCKER_BASE_IMAGE) \
		--build-arg PACKAGE_NAME=$(PACKAGE_NAME) \
		--tag=$(GAR_IMAGE):dev .

docker_run_local: ## Lance le conteneur Docker local sur le port 8080
	@echo "🏃‍♂️ Lancement du conteneur $(GAR_IMAGE):dev..."
	@echo "👉 Allez sur http://localhost:8080"
	docker run -it \
		--env-file .env \
		-p 8000:8000 \
		$(GAR_IMAGE):dev

artifact_registry_create: ## Crée le dépôt Docker dans Artifact Registry
	@echo "📦 Création du dépôt Artifact Registry $(ARTIFACTSREPO)..."
	gcloud artifacts repositories create $(ARTIFACTSREPO) \
		--repository-format=docker \
		--location=$(GCP_REGION) \
		--description="Dépôt Docker $(ARTIFACTSREPO) pour le projet $(GCP_PROJECT)" \
		--project=$(GCP_PROJECT) || true

artifact_registry_role: ## Vous accorde la permission de push vers Artifact Registry
	@echo "🔐 Ajout du rôle Artifact Registry Writer à votre compte..."
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
		--member="user:$$(gcloud config get-value account)" \
		--role="roles/artifactregistry.writer"

docker_auth: ## Configure Docker pour s'authentifier auprès de Google Cloud
	@echo "🔑 Configuration de l'authentification Docker pour GCP..."
	gcloud auth configure-docker $(GCP_REGION)-docker.pkg.dev --quiet

docker_build_prod: ## Build l'image Docker pour la production (linux/amd64)
	@echo "🏗️ Build de l'image de production..."
	docker build \
		--platform linux/amd64 \
		--build-arg DOCKER_BASE_IMAGE=$(DOCKER_BASE_IMAGE) \
		--build-arg PACKAGE_NAME=$(PACKAGE_NAME) \
		-t $(GCP_REGION)-docker.pkg.dev/$(GCP_PROJECT)/$(ARTIFACTSREPO)/$(GAR_IMAGE):prod \
		.

docker_push_prod: ## Push l'image de production vers Artifact Registry
	@echo "🚀 Push de l'image vers Artifact Registry..."
	docker push $(GCP_REGION)-docker.pkg.dev/$(GCP_PROJECT)/$(ARTIFACTSREPO)/$(GAR_IMAGE):prod
