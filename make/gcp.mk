# ==============================================================================
# COMMANDES INFRASTRUCTURE GCP & IAM
# ==============================================================================

# Cache du résultat de gcp_check_auth : évite de refaire les vrais appels GCP
# (un peu lents) à chaque cible d'un même enchaînement (ex. un script qui lance
# plusieurs `make cloudrun_deploy` à la suite, chacun avec gcp_check_auth en
# prérequis). Fichier vidé de sens tout seul (mtime trop vieux) après
# GCP_AUTH_CACHE_MINUTES, pas besoin de le nettoyer explicitement.
GCP_AUTH_CACHE_FILE = /tmp/.berlue-gcp-auth-ok-$(GCP_PROJECT)
GCP_AUTH_CACHE_MINUTES = 10

# Vrai appel gcloud (CLI) — utilisé par gcp_auth (fix si besoin) et
# gcp_check_auth (échoue si besoin), pour ne pas dupliquer le test.
_gcp_check_cli_auth:
	@gcloud run services list --project=$(GCP_PROJECT) --region=$(GCP_REGION) >/dev/null 2>&1

# Vrai appel via google-cloud-storage (ADC) — 'gcloud auth application-default
# print-access-token' ne suffit pas : il peut réussir sans garantir qu'un appel
# via les libs client (le vrai consommateur de l'ADC ici) passe.
_gcp_check_adc_auth:
	@python3 -c "from google.cloud import storage; storage.Client(project='$(GCP_PROJECT)').list_buckets(max_results=1)" >/dev/null 2>&1

gcp_auth: ## Authentifie gcloud (CLI + Application Default Credentials) via de vrais appels GCP, et ne relance le login que si nécessaire
	@echo "🔎 Vérification de l'authentification gcloud (CLI) — appel réel à Cloud Run..."
	@if $(MAKE) --no-print-directory _gcp_check_cli_auth; then \
		echo "✅ CLI gcloud déjà authentifiée."; \
	else \
		echo "🔑 Authentification requise (CLI, ouvre le navigateur)..."; \
		gcloud auth login; \
	fi
	@echo "🔎 Vérification des Application Default Credentials — appel réel via google-cloud-storage..."
	@if $(MAKE) --no-print-directory _gcp_check_adc_auth; then \
		echo "✅ Application Default Credentials déjà valides."; \
	else \
		echo "🔑 Authentification requise (Application Default Credentials, ouvre le navigateur)..."; \
		gcloud auth application-default login; \
	fi
	@touch $(GCP_AUTH_CACHE_FILE)

gcp_check_auth: ## Vérifie que gcloud (CLI + ADC) est authentifié, échoue (exit 1) sinon — à mettre en prérequis des cibles qui touchent à GCP (ex. cloudrun_deploy). Résultat mis en cache 10 min.
	@if [ -n "$$(find $(GCP_AUTH_CACHE_FILE) -mmin -$(GCP_AUTH_CACHE_MINUTES) 2>/dev/null)" ]; then \
		exit 0; \
	fi; \
	$(MAKE) --no-print-directory _gcp_check_cli_auth || { \
		echo "❌ CLI gcloud non authentifiée (ou token expiré). Lancez : make gcp_auth"; \
		exit 1; \
	}; \
	$(MAKE) --no-print-directory _gcp_check_adc_auth || { \
		echo "❌ Application Default Credentials non authentifiées (ou expirées). Lancez : make gcp_auth"; \
		exit 1; \
	}; \
	touch $(GCP_AUTH_CACHE_FILE)

gcp_destroy: gcp_check_auth ## Supprime TOUT ce qui a été déployé sur GCP pour Berlue (3 environnements Cloud Run + dépôt Artifact Registry et ses images) — demande confirmation
	@echo "⚠️  Ceci va supprimer DÉFINITIVEMENT :"
	@echo "   - Les services Cloud Run : $(GAR_IMAGE)-test, $(GAR_IMAGE)-staging, $(GAR_IMAGE)-prod"
	@echo "   - Le dépôt Artifact Registry : $(ARTIFACTSREPO) (et toutes les images qu'il contient)"
	@read -p "Confirmer la suppression ? (taper 'oui' pour continuer) " confirm && [ "$$confirm" = "oui" ] || { echo "Annulé."; exit 1; }
	@$(MAKE) --no-print-directory cloudrun_delete CLOUDRUN_ENV=test || true
	@$(MAKE) --no-print-directory cloudrun_delete CLOUDRUN_ENV=staging || true
	@$(MAKE) --no-print-directory cloudrun_delete CLOUDRUN_ENV=prod || true
	@$(MAKE) --no-print-directory artifact_registry_delete || true
	@echo "✅ Suppression terminée."

gcp_project_list: ## Liste tous les projets GCP disponibles pour votre compte
	@echo "📋 Listing des projets GCP..."
	gcloud projects list
	# Alternatives utiles :
	# gcloud projects list --format="value(projectId)" # ne liste que les IDs
	# gcloud config get-value project # affiche seulement l'ID du projet actif

gcp_enable_compute: ## Active l'API Compute Engine pour le projet
	@echo "⚙️ Activation de l'API Compute Engine..."
	gcloud services enable compute.googleapis.com --project=$(GCP_PROJECT)

gcs_list_buckets: ## Liste tous les buckets Cloud Storage du projet
	@echo "🪣 Listing des buckets Cloud Storage..."
	gcloud storage ls --project=$(GCP_PROJECT)

gcs_create_bucket: ## Crée un nouveau bucket Cloud Storage
	@echo "🪣 Création du bucket gs://$(BUCKET_NAME)..."
	gcloud storage buckets create gs://$(BUCKET_NAME) \
		--location=$(GCP_REGION) \
		--project=$(GCP_PROJECT)

gcs_delete_bucket: ## Supprime le bucket Cloud Storage et tout son contenu
	@echo "💣 Suppression du bucket gs://$(BUCKET_NAME)..."
	gcloud storage rm --recursive gs://$(BUCKET_NAME)

# Accès par personne sur un bucket précis (personnel ou d'équipe — un nom de
# bucket GCS est unique globalement, pas besoin de préciser de projet).
# BUCKET_ROLE = reader (lecture seule, défaut) ou writer (lecture+écriture/delete).
BUCKET_ROLE ?= reader

gcs_grant: ## Donne l'accès à une personne sur un bucket (BUCKET=nom + USER=email requis, BUCKET_ROLE=reader|writer, défaut reader)
	@if [ -z "$(BUCKET)" ] || [ -z "$(USER)" ]; then \
		echo "❌ ERREUR : BUCKET et/ou USER manquant."; \
		echo "👉 Essayez : make gcs_grant BUCKET=mon-bucket USER=personne@example.com BUCKET_ROLE=writer"; \
		exit 1; \
	fi
	@echo "🔐 Ajout de l'accès '$(BUCKET_ROLE)' pour $(USER) sur gs://$(BUCKET)..."
	gcloud storage buckets add-iam-policy-binding gs://$(BUCKET) \
		--member="user:$(USER)" \
		--role="roles/storage.$(if $(filter writer,$(BUCKET_ROLE)),objectAdmin,objectViewer)"

gcs_revoke: ## Retire l'accès d'une personne sur un bucket (BUCKET=nom + USER=email requis, BUCKET_ROLE=reader|writer, défaut reader)
	@if [ -z "$(BUCKET)" ] || [ -z "$(USER)" ]; then \
		echo "❌ ERREUR : BUCKET et/ou USER manquant."; \
		echo "👉 Essayez : make gcs_revoke BUCKET=mon-bucket USER=personne@example.com BUCKET_ROLE=writer"; \
		exit 1; \
	fi
	@echo "🔓 Retrait de l'accès '$(BUCKET_ROLE)' pour $(USER) sur gs://$(BUCKET)..."
	gcloud storage buckets remove-iam-policy-binding gs://$(BUCKET) \
		--member="user:$(USER)" \
		--role="roles/storage.$(if $(filter writer,$(BUCKET_ROLE)),objectAdmin,objectViewer)"

iam_setup_service_account: ## Crée le compte de service et lui assigne les rôles IAM
	@echo "🤖 Création ou vérification du compte de service..."
	gcloud iam service-accounts create $(SA_NAME) \
		--display-name="Service Account for VM" \
		--project=$(GCP_PROJECT) || true
	@echo "🔐 Ajout du rôle BigQuery Data Editor..."
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
		--member="serviceAccount:$(SA_EMAIL)" \
		--role="roles/bigquery.dataEditor" \
		--quiet
	@echo "🔐 Ajout du rôle Cloud Storage Object Admin..."
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
		--member="serviceAccount:$(SA_EMAIL)" \
		--role="roles/storage.objectAdmin" \
		--quiet
