# ==============================================================================
# COMMANDES INFRASTRUCTURE GCP & IAM
# ==============================================================================

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
