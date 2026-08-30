# ==============================================================================
# COMMANDES DOCKER & ARTIFACT REGISTRY
# ==============================================================================

docker_build_local: ## Build l'image Docker locale pour les tests (tag surchargeable : DOCKER_TAG=... , défaut dev)
	@echo "🐳 Build de l'image Docker locale $(GAR_IMAGE):$(DOCKER_TAG)..."
	docker build \
		--build-arg DOCKER_BASE_IMAGE=$(DOCKER_BASE_IMAGE) \
		--build-arg PACKAGE_NAME=$(PACKAGE_NAME) \
		--tag=$(GAR_IMAGE):$(DOCKER_TAG) .

docker_run_local: ## Lance le conteneur Docker local sur le port 8000 (tag surchargeable : DOCKER_TAG=... , défaut dev)
	@echo "🏃‍♂️ Lancement du conteneur $(GAR_IMAGE):$(DOCKER_TAG)..."
	@echo "👉 Allez sur http://localhost:8000"
	docker run -it \
		--env-file .env \
		-e PORT=8000 \
		-p 8000:8000 \
		$(GAR_IMAGE):$(DOCKER_TAG)

compose_up: docker_build_local ## Lance l'API via docker-compose (rechargement à chaud, code monté en volume)
	@echo "🐳 Lancement via docker compose (image $(GAR_IMAGE):dev)..."
	docker compose up

compose_down: ## Arrête et supprime les conteneurs/réseau docker-compose
	docker compose down

artifact_registry_enable_api: gcp_check_cli_auth ## Active l'API Artifact Registry (dans ARTIFACT_PROJECT)
	@echo "⚙️ Activation de l'API Artifact Registry dans $(ARTIFACT_PROJECT)..."
	gcloud services enable artifactregistry.googleapis.com --project=$(ARTIFACT_PROJECT)

artifact_registry_create: artifact_registry_enable_api ## Crée le dépôt Docker dans Artifact Registry (dans ARTIFACT_PROJECT)
	@echo "📦 Création du dépôt Artifact Registry $(ARTIFACTSREPO) dans $(ARTIFACT_PROJECT)..."
	gcloud artifacts repositories create $(ARTIFACTSREPO) \
		--repository-format=docker \
		--location=$(GCP_REGION) \
		--description="Dépôt Docker $(ARTIFACTSREPO) pour le projet $(ARTIFACT_PROJECT)" \
		--project=$(ARTIFACT_PROJECT) || true

artifact_registry_delete: ## Supprime le dépôt Docker dans Artifact Registry (et toutes les images qu'il contient)
	@echo "💣 Suppression du dépôt Artifact Registry $(ARTIFACTSREPO) dans $(ARTIFACT_PROJECT)..."
	gcloud artifacts repositories delete $(ARTIFACTSREPO) \
		--location=$(GCP_REGION) \
		--project=$(ARTIFACT_PROJECT) \
		--quiet

artifact_registry_role: ## Vous accorde la permission de push vers Artifact Registry (projet ARTIFACT_PROJECT entier)
	@echo "🔐 Ajout du rôle Artifact Registry Writer à votre compte sur $(ARTIFACT_PROJECT)..."
	gcloud projects add-iam-policy-binding $(ARTIFACT_PROJECT) \
		--member="user:$$(gcloud config get-value account)" \
		--role="roles/artifactregistry.writer" \
		--condition=None

# Accès par personne, scope = uniquement le dépôt $(ARTIFACTSREPO) (plus fin que
# artifact_registry_role ci-dessus, qui donne un accès writer projet entier à
# vous-même). ROLE = reader (lecture/pull, défaut) ou writer (lecture+écriture/push).
ROLE ?= reader

artifact_registry_grant: ## Donne l'accès à une personne sur Artifact Registry (USER=email requis, ROLE=reader|writer, défaut reader)
	@if [ -z "$(USER)" ]; then \
		echo "❌ ERREUR : USER manquant."; \
		echo "👉 Essayez : make artifact_registry_grant USER=personne@example.com ROLE=writer"; \
		exit 1; \
	fi
	@echo "🔐 Ajout de l'accès '$(ROLE)' pour $(USER) sur $(ARTIFACTSREPO) ($(ARTIFACT_PROJECT))..."
	gcloud artifacts repositories add-iam-policy-binding $(ARTIFACTSREPO) \
		--location=$(GCP_REGION) \
		--project=$(ARTIFACT_PROJECT) \
		--member="user:$(USER)" \
		--role="roles/artifactregistry.$(ROLE)"

artifact_registry_revoke: ## Retire l'accès d'une personne sur Artifact Registry (USER=email requis, ROLE=reader|writer, défaut reader)
	@if [ -z "$(USER)" ]; then \
		echo "❌ ERREUR : USER manquant."; \
		echo "👉 Essayez : make artifact_registry_revoke USER=personne@example.com ROLE=writer"; \
		exit 1; \
	fi
	@echo "🔓 Retrait de l'accès '$(ROLE)' pour $(USER) sur $(ARTIFACTSREPO) ($(ARTIFACT_PROJECT))..."
	gcloud artifacts repositories remove-iam-policy-binding $(ARTIFACTSREPO) \
		--location=$(GCP_REGION) \
		--project=$(ARTIFACT_PROJECT) \
		--member="user:$(USER)" \
		--role="roles/artifactregistry.$(ROLE)"

docker_auth: ## Configure Docker pour s'authentifier auprès de Google Cloud
	@echo "🔑 Configuration de l'authentification Docker pour GCP..."
	gcloud auth configure-docker $(GCP_REGION)-docker.pkg.dev --quiet

docker_build_prod: ## Build l'image Docker pour la production (linux/amd64)
	@echo "🏗️ Build de l'image de production..."
	docker build \
		--platform linux/amd64 \
		--build-arg DOCKER_BASE_IMAGE=$(DOCKER_BASE_IMAGE) \
		--build-arg PACKAGE_NAME=$(PACKAGE_NAME) \
		-t $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_IMAGE):prod \
		.

docker_push_prod: ## Push l'image de production vers Artifact Registry
	@echo "🚀 Push de l'image vers Artifact Registry ($(ARTIFACT_PROJECT))..."
	docker push $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_IMAGE):prod

docker_build_eval: ## Build l'image du Job Cloud Run d'éval (Dockerfile.eval, linux/amd64)
	@echo "🏗️ Build de l'image d'éval $(GAR_EVAL_IMAGE)..."
	docker build \
		--platform linux/amd64 \
		--build-arg DOCKER_BASE_IMAGE=$(DOCKER_BASE_IMAGE) \
		-f Dockerfile.eval \
		-t $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_EVAL_IMAGE):latest \
		.

docker_push_eval: ## Push l'image d'éval vers Artifact Registry
	@echo "🚀 Push de l'image d'éval vers Artifact Registry ($(ARTIFACT_PROJECT))..."
	docker push $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_EVAL_IMAGE):latest

docker_build_llm: ## Build l'image du service Cloud Run Ollama (Dockerfile.llm, linux/amd64)
	@echo "🏗️ Build de l'image LLM $(GAR_LLM_IMAGE)..."
	docker build \
		--platform linux/amd64 \
		-f Dockerfile.llm \
		-t $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_LLM_IMAGE):latest \
		.

docker_push_llm: ## Push l'image LLM vers Artifact Registry
	@echo "🚀 Push de l'image LLM vers Artifact Registry ($(ARTIFACT_PROJECT))..."
	docker push $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_LLM_IMAGE):latest
