# ==============================================================================
# COMMANDES DOCKER & ARTIFACT REGISTRY
# ==============================================================================

docker_build_local: ## Build l'image Docker locale pour les tests (tag surchargeable : DOCKER_TAG=... , défaut dev)
	@echo "🐳 Build de l'image Docker locale $(GAR_RUNTIME_IMAGE):$(DOCKER_TAG)..."
	docker build \
		--build-arg DOCKER_BASE_IMAGE=$(DOCKER_BASE_IMAGE) \
		--tag=$(GAR_RUNTIME_IMAGE):$(DOCKER_TAG) .

# L'image ne contient pas le code (cf. Dockerfile) : en local on le bind-monte
# dans /app, ce que l'entrypoint reconnaît et respecte (aucune copie depuis un
# bucket). BERLUE_APP_MODULE choisit le service — API par défaut, éval avec
# `make docker_run_local BERLUE_APP_MODULE=$(BERLUE_EVAL_MODULE)`.
docker_run_local: ## Lance le conteneur Docker local sur le port 8000, code local monté (tag : DOCKER_TAG=..., service : BERLUE_APP_MODULE=...)
	@echo "🏃‍♂️ Lancement du conteneur $(GAR_RUNTIME_IMAGE):$(DOCKER_TAG) ($(BERLUE_APP_MODULE))..."
	@echo "👉 Allez sur http://localhost:8000"
	docker run -it \
		--env-file .env \
		-e PORT=8000 \
		-e BERLUE_APP_MODULE=$(BERLUE_APP_MODULE) \
		-v $(PWD)/berlue:/app/berlue:ro \
		-v $(PWD)/models:/app/models:ro \
		-v $(PWD)/data:/app/data \
		-p 8000:8000 \
		$(GAR_RUNTIME_IMAGE):$(DOCKER_TAG)

compose_up: docker_build_local ## Lance l'API via docker-compose (rechargement à chaud, code monté en volume)
	@echo "🐳 Lancement via docker compose (image $(GAR_RUNTIME_IMAGE):dev)..."
	docker compose up

compose_down: ## Arrête et supprime les conteneurs/réseau docker-compose
	docker compose down

artifact_registry_enable_api: gcp_check_cli_auth ## Active l'API Artifact Registry (dans ARTIFACT_PROJECT)
	@echo "⚙️ Activation de l'API Artifact Registry dans $(ARTIFACT_PROJECT)..."
	gcloud services enable artifactregistry.googleapis.com --project=$(ARTIFACT_PROJECT) </dev/null

artifact_registry_create: artifact_registry_enable_api ## Crée le dépôt Docker dans Artifact Registry (dans ARTIFACT_PROJECT) — appelé par gcp_setup, doit rester rejouable sans erreur
	@if gcloud artifacts repositories describe $(ARTIFACTSREPO) --location=$(GCP_REGION) --project=$(ARTIFACT_PROJECT) >/dev/null 2>&1 </dev/null; then \
		echo "✅ Dépôt Artifact Registry $(ARTIFACTSREPO) déjà présent dans $(ARTIFACT_PROJECT), création sautée."; \
	else \
		echo "📦 Création du dépôt Artifact Registry $(ARTIFACTSREPO) dans $(ARTIFACT_PROJECT)..."; \
		$(RETRY) "création du dépôt $(ARTIFACTSREPO)" \
			gcloud artifacts repositories create $(ARTIFACTSREPO) \
				--repository-format=docker \
				--location=$(GCP_REGION) \
				--description="Dépôt Docker $(ARTIFACTSREPO) pour le projet $(ARTIFACT_PROJECT)" \
				--project=$(ARTIFACT_PROJECT); \
	fi

artifact_registry_delete: ## Supprime le dépôt Docker dans Artifact Registry (et toutes les images qu'il contient)
	@echo "💣 Suppression du dépôt Artifact Registry $(ARTIFACTSREPO) dans $(ARTIFACT_PROJECT)..."
	gcloud artifacts repositories delete $(ARTIFACTSREPO) \
		--location=$(GCP_REGION) \
		--project=$(ARTIFACT_PROJECT) \
		--quiet

artifact_registry_role: ## Vous accorde la permission de push vers Artifact Registry (projet ARTIFACT_PROJECT entier)
	@ACCOUNT="$(GCLOUD_ACTIVE_ACCOUNT)"; \
	if [ -z "$$ACCOUNT" ]; then \
		echo "❌ Aucun compte gcloud actif. Lancez : make gcp_auth"; \
		exit 1; \
	fi; \
	echo "🔐 Ajout du rôle Artifact Registry Writer à $$ACCOUNT sur $(ARTIFACT_PROJECT)..."; \
	gcloud projects add-iam-policy-binding $(ARTIFACT_PROJECT) \
		--member="user:$$ACCOUNT" \
		--role="roles/artifactregistry.writer" \
		--condition=None \
		--quiet </dev/null

artifact_registry_role_revoke: ## Vous retire la permission de push vers Artifact Registry (contrepartie d'artifact_registry_role, appelée par gcp_destroy)
	@ACCOUNT="$(GCLOUD_ACTIVE_ACCOUNT)"; \
	if [ -z "$$ACCOUNT" ]; then \
		echo "❌ Aucun compte gcloud actif. Lancez : make gcp_auth"; \
		exit 1; \
	fi; \
	echo "🔓 Retrait du rôle Artifact Registry Writer à $$ACCOUNT sur $(ARTIFACT_PROJECT)..."; \
	gcloud projects remove-iam-policy-binding $(ARTIFACT_PROJECT) \
		--member="user:$$ACCOUNT" \
		--role="roles/artifactregistry.writer" \
		--condition=None \
		--quiet </dev/null

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
	gcloud auth configure-docker $(GCP_REGION)-docker.pkg.dev --quiet </dev/null

# Variante utilisée par gcp_setup : un poste qui ne fait que lancer l'éval
# n'a pas forcément Docker installé, et ça ne doit pas faire échouer tout le
# provisionnement. gcp_doctor le redira.
docker_auth_if_available: ## Comme docker_auth, mais se contente d'un avertissement si Docker n'est pas installé
	@if command -v docker >/dev/null 2>&1; then \
		$(MAKE) --no-print-directory docker_auth; \
	else \
		echo "⚠️  Docker introuvable — authentification Docker sautée (nécessaire seulement pour build/push des images)."; \
	fi

# Les 2 images du projet, build + push. Indépendantes de CLOUDRUN_ENV et du
# code applicatif : `berlue-runtime` ne porte que les dépendances, et sert
# aussi bien l'API que le service d'éval (le module servi est choisi au
# déploiement, cf. BERLUE_APP_MODULE). Elle n'a donc à être rebuildée que
# quand requirements.txt ou le Dockerfile changent — un changement de Python
# passe par `make code_deploy` (cf. make/code.mk).
docker_build_push_all: ## Build et push les 2 images (runtime applicatif, Ollama) vers Artifact Registry
	@command -v docker >/dev/null 2>&1 || { \
		echo "❌ Docker introuvable — indispensable pour builder les images."; \
		exit 1; \
	}
	@$(MAKE) --no-print-directory docker_build_prod
	@$(MAKE) --no-print-directory docker_push_prod
	@$(MAKE) --no-print-directory docker_build_llm
	@$(MAKE) --no-print-directory docker_push_llm
	@echo "✅ 2 images à jour dans $(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)."

docker_build_prod: ## Build l'image runtime applicatif pour la production (linux/amd64)
	@echo "🏗️ Build de l'image runtime $(GAR_RUNTIME_IMAGE)..."
	docker build \
		--platform linux/amd64 \
		--build-arg DOCKER_BASE_IMAGE=$(DOCKER_BASE_IMAGE) \
		-t $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_RUNTIME_IMAGE):prod \
		.

docker_push_prod: ## Push l'image runtime applicatif vers Artifact Registry
	@echo "🚀 Push de l'image vers Artifact Registry ($(ARTIFACT_PROJECT))..."
	docker push $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_RUNTIME_IMAGE):prod

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

# ==============================================================================
# IMAGE VENUE D'UN AUTRE PROJET
# ==============================================================================
# Quand IMAGE_SOURCE_PROJECT désigne un projet tiers, Cloud Run n'y a aucun
# droit par défaut : le déploiement échoue tard, sur une erreur de permission
# peu parlante. Ces deux cibles rendent le problème visible avant.

image_source_grant: gcp_check_cli_auth ## Autorise le compte de service Cloud Run de CE projet à tirer les images de IMAGE_SOURCE_PROJECT (à lancer par qui a les droits sur le projet source)
	@if [ "$(IMAGE_SOURCE_PROJECT)" = "$(GCP_PROJECT)" ]; then \
		echo "ℹ️  IMAGE_SOURCE_PROJECT vaut $(GCP_PROJECT) : les images sont déjà locales, rien à autoriser."; \
		exit 0; \
	fi
	@echo "🔐 Lecture de $(IMAGE_SOURCE_REPO) ($(IMAGE_SOURCE_PROJECT)) pour $(CLOUDRUN_SA_EMAIL)..."
	gcloud artifacts repositories add-iam-policy-binding $(IMAGE_SOURCE_REPO) \
		--location=$(IMAGE_SOURCE_REGION) \
		--project=$(IMAGE_SOURCE_PROJECT) \
		--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
		--role="roles/artifactregistry.reader" \
		--quiet </dev/null >/dev/null
	@echo "✅ $(CLOUDRUN_SA_EMAIL) peut tirer les images de $(IMAGE_SOURCE_PROJECT)."

image_source_check: ## Vérifie que les images pointées par IMAGE_SOURCE_* existent et sont lisibles avec vos droits
	@echo "🔎 Source des images : $(IMAGE_SOURCE_REGION)-docker.pkg.dev/$(IMAGE_SOURCE_PROJECT)/$(IMAGE_SOURCE_REPO)"
	@FAIL=0; \
	for URI in "$(RUNTIME_IMAGE_URI)" "$(LLM_IMAGE_URI)"; do \
		if gcloud artifacts docker images describe "$$URI" >/dev/null 2>&1 </dev/null; then \
			echo "  ✅ $$URI"; \
		else \
			echo "  ❌ $$URI — absente, ou illisible avec votre compte"; \
			FAIL=1; \
		fi; \
	done; \
	if [ "$$FAIL" = "1" ]; then \
		echo "   👉 Si le dépôt est dans un autre projet : make image_source_grant (côté projet source)."; \
		exit 1; \
	fi

# ==============================================================================
# LAISSER UN AUTRE PROJET TIRER NOS IMAGES
# ==============================================================================
# Symétrique d'image_source_grant : celui-ci se lance CHEZ NOUS pour qu'un
# collègue déploie sur nos images sans jamais les reconstruire.
#
# Le compte à autoriser n'est pas celui qu'on croit. Cloud Run tire ses images
# avec son AGENT DE SERVICE — service-<numéro>@serverless-robot-prod — et non
# avec le compte d'exécution du service (sa-berlue@leur-projet), qui ne sert
# qu'une fois le conteneur démarré. Autoriser le second laisse le déploiement
# échouer sur une image introuvable.
#
#   make image_reader_grant CONSUMER_PROJECT=<id ou numéro du projet du collègue>

# À lancer CHEZ LE CONSOMMATEUR : le propriétaire du dépôt doit poser
# l'autorisation, mais le numéro de projet dont il a besoin n'est lisible que
# depuis le projet consommateur. Cette cible produit la ligne exacte à lui
# renvoyer, plutôt qu'un échange sur ce qu'est un numéro de projet.
image_reader_request: gcp_check_cli_auth ## Affiche la commande à envoyer au propriétaire des images pour qu'il autorise VOTRE Cloud Run
	@NUM=$$(gcloud projects describe $(GCP_PROJECT) --format="value(projectNumber)" 2>/dev/null </dev/null); \
	if [ -z "$$NUM" ]; then \
		echo "❌ Numéro de projet illisible pour $(GCP_PROJECT) — êtes-vous authentifié sur le bon projet ?"; \
		exit 1; \
	fi; \
	echo "📋 Envoyez cette ligne au propriétaire du dépôt d'images :"; \
	echo ""; \
	echo "    make image_reader_grant CONSUMER_PROJECT=$$NUM"; \
	echo ""; \
	echo "   (projet $(GCP_PROJECT), agent Cloud Run service-$$NUM@serverless-robot-prod.iam.gserviceaccount.com)"; \
	echo "   Une fois qu'il l'a lancée, mettez dans votre .env :"; \
	echo "       IMAGE_SOURCE_PROJECT=<son projet>"; \
	echo "   puis vérifiez avec : make image_source_check"

image_reader_grant: gcp_check_cli_auth ## Autorise le Cloud Run d'un AUTRE projet à tirer nos images (CONSUMER_PROJECT=<id|numéro> requis)
	@if [ -z "$(CONSUMER_PROJECT)" ]; then \
		echo "❌ ERREUR : CONSUMER_PROJECT manquant."; \
		echo "👉 make image_reader_grant CONSUMER_PROJECT=projet-du-collegue"; \
		exit 1; \
	fi
	@NUM=$$(echo "$(CONSUMER_PROJECT)" | grep -qE '^[0-9]+$$' && echo "$(CONSUMER_PROJECT)" \
		|| gcloud projects describe "$(CONSUMER_PROJECT)" --format="value(projectNumber)" 2>/dev/null </dev/null); \
	if [ -z "$$NUM" ]; then \
		echo "❌ Projet $(CONSUMER_PROJECT) introuvable, ou numéro illisible."; \
		echo "   Le collègue peut le donner : gcloud projects describe <son-projet> --format='value(projectNumber)'"; \
		exit 1; \
	fi; \
	AGENT="service-$$NUM@serverless-robot-prod.iam.gserviceaccount.com"; \
	echo "🔐 Lecture de $(ARTIFACTSREPO) pour l'agent Cloud Run de $(CONSUMER_PROJECT) ($$AGENT)..."; \
	gcloud artifacts repositories add-iam-policy-binding $(ARTIFACTSREPO) \
		--location=$(GCP_REGION) \
		--project=$(ARTIFACT_PROJECT) \
		--member="serviceAccount:$$AGENT" \
		--role="roles/artifactregistry.reader" \
		--quiet </dev/null >/dev/null; \
	echo "✅ Leur Cloud Run peut tirer nos images."; \
	echo "   Chez eux : IMAGE_SOURCE_PROJECT=$(ARTIFACT_PROJECT) dans .env, puis make cloudrun_deploy."

image_reader_revoke: gcp_check_cli_auth ## Retire à un autre projet le droit de tirer nos images (CONSUMER_PROJECT=<id|numéro> requis)
	@if [ -z "$(CONSUMER_PROJECT)" ]; then \
		echo "❌ ERREUR : CONSUMER_PROJECT manquant."; \
		exit 1; \
	fi
	@NUM=$$(echo "$(CONSUMER_PROJECT)" | grep -qE '^[0-9]+$$' && echo "$(CONSUMER_PROJECT)" \
		|| gcloud projects describe "$(CONSUMER_PROJECT)" --format="value(projectNumber)" 2>/dev/null </dev/null); \
	gcloud artifacts repositories remove-iam-policy-binding $(ARTIFACTSREPO) \
		--location=$(GCP_REGION) \
		--project=$(ARTIFACT_PROJECT) \
		--member="serviceAccount:service-$$NUM@serverless-robot-prod.iam.gserviceaccount.com" \
		--role="roles/artifactregistry.reader" \
		--quiet </dev/null >/dev/null || true
	@echo "✅ Accès retiré."
