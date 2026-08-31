# ==============================================================================
# COMMANDES INFRASTRUCTURE GCP & IAM
# ==============================================================================

# Cache du résultat de gcp_check_cli_auth : évite de refaire le vrai appel
# GCP (un peu lent) à chaque cible d'un même enchaînement (ex. un script qui
# lance plusieurs `make cloudrun_deploy` à la suite, chacun avec un check en
# prérequis). Fichier vidé de sens tout seul (mtime trop vieux) après
# GCP_AUTH_CACHE_MINUTES, pas besoin de le nettoyer explicitement.
GCP_CLI_AUTH_CACHE_FILE = /tmp/.berlue-gcp-cli-auth-ok-$(GCP_PROJECT)
GCP_AUTH_CACHE_MINUTES = 10

# Vrai appel gcloud (CLI) — utilisé par gcp_auth (fix si besoin) et
# gcp_check_cli_auth (échoue si besoin), pour ne pas dupliquer le test.
_gcp_check_cli_auth:
	@gcloud run services list --project=$(GCP_PROJECT) --region=$(GCP_REGION) >/dev/null 2>&1

gcp_auth: ## Authentifie la session gcloud CLI via un vrai appel GCP, et ne relance le login que si nécessaire
	@echo "🔎 Vérification de l'authentification gcloud (CLI) — appel réel à Cloud Run..."
	@if $(MAKE) --no-print-directory _gcp_check_cli_auth; then \
		echo "✅ CLI gcloud déjà authentifiée."; \
	else \
		echo "🔑 Authentification requise (CLI, ouvre le navigateur)..."; \
		gcloud auth login; \
	fi
	@touch $(GCP_CLI_AUTH_CACHE_FILE)

gcp_check_cli_auth: ## Vérifie que la session gcloud CLI est authentifiée, échoue (exit 1) sinon — à mettre en prérequis des cibles gcloud/bq (ex. cloudrun_deploy, firestore_create_database, gcp_destroy). Résultat mis en cache 10 min.
	@if [ -n "$$(find $(GCP_CLI_AUTH_CACHE_FILE) -mmin -$(GCP_AUTH_CACHE_MINUTES) 2>/dev/null)" ]; then \
		exit 0; \
	fi; \
	$(MAKE) --no-print-directory _gcp_check_cli_auth || { \
		echo "❌ CLI gcloud non authentifiée (ou token expiré). Lancez : make gcp_auth"; \
		exit 1; \
	}; \
	touch $(GCP_CLI_AUTH_CACHE_FILE)

gcp_destroy: gcp_check_cli_auth ## Supprime TOUT ce qui a été déployé sur GCP pour Berlue (3 environnements Cloud Run + dépôt Artifact Registry et ses images + bucket RAG) — demande confirmation
	@echo "⚠️  Ceci va supprimer DÉFINITIVEMENT :"
	@echo "   - Les services Cloud Run : $(GAR_IMAGE)-test, $(GAR_IMAGE)-staging, $(GAR_IMAGE)-prod"
	@echo "   - Le dépôt Artifact Registry : $(ARTIFACTSREPO) (et toutes les images qu'il contient)"
	@echo "   - Le bucket RAG : $(RAG_BUCKET_NAME) (et l'index qu'il contient)"
	@read -p "Confirmer la suppression ? (taper 'oui' pour continuer) " confirm && [ "$$confirm" = "oui" ] || { echo "Annulé."; exit 1; }
	@$(MAKE) --no-print-directory cloudrun_delete CLOUDRUN_ENV=test || true
	@$(MAKE) --no-print-directory cloudrun_delete CLOUDRUN_ENV=staging || true
	@$(MAKE) --no-print-directory cloudrun_delete CLOUDRUN_ENV=prod || true
	@$(MAKE) --no-print-directory artifact_registry_delete || true
	@$(MAKE) --no-print-directory rag_bucket_delete || true
	@echo "✅ Suppression terminée."

gcp_setup: gcp_check_cli_auth ## Provisionne l'infra GCP nécessaire au projet Berlue (API Firestore/BigQuery/Cloud Run/Compute + Firestore + dataset BigQuery + service account Cloud Run + observabilité des coûts + bucket RAG) — tout ce qui est gratuit et anticipable, jamais gcp_up/gcp_down (ça, c'est le coût variable à la demande)
	@echo "🚀 Mise en place de l'infra GCP..."
	@$(MAKE) --no-print-directory firestore_enable_api
	@$(MAKE) --no-print-directory bigquery_enable_api
	@$(MAKE) --no-print-directory cloudrun_enable_api
	@$(MAKE) --no-print-directory gcp_enable_compute
	@$(MAKE) --no-print-directory firestore_create_database
	@$(MAKE) --no-print-directory bigquery_create_dataset
	@$(MAKE) --no-print-directory iam_setup_cloudrun_service_account
	@$(MAKE) --no-print-directory gcp_enable_cost_observability
	@$(MAKE) --no-print-directory rag_bucket_create
	@$(MAKE) --no-print-directory rag_bucket_grant_sa
	@echo "✅ Infra GCP prête."

gcp_project_list: ## Liste tous les projets GCP disponibles pour votre compte
	@echo "📋 Listing des projets GCP..."
	gcloud projects list
	# Alternatives utiles :
	# gcloud projects list --format="value(projectId)" # ne liste que les IDs
	# gcloud config get-value project # affiche seulement l'ID du projet actif

gcp_enable_compute: ## Active l'API Compute Engine pour le projet
	@echo "⚙️ Activation de l'API Compute Engine..."
	gcloud services enable compute.googleapis.com --project=$(GCP_PROJECT)

gcp_enable_cost_observability: ## Active l'API nécessaire à l'onglet "Cost" des services Cloud Run dans la Console
	@echo "⚙️ Activation de l'API App Optimize (coût par service Cloud Run)..."
	gcloud services enable appoptimize.googleapis.com --project=$(GCP_PROJECT)

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
		--condition=None \
		--quiet
	@echo "🔐 Ajout du rôle Cloud Storage Object Admin..."
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
		--member="serviceAccount:$(SA_EMAIL)" \
		--role="roles/storage.objectAdmin" \
		--condition=None \
		--quiet

iam_setup_cloudrun_service_account: gcp_check_cli_auth ## Crée $(CLOUDRUN_SA_NAME) (compte de service Cloud Run) et lui donne les droits Firestore/BigQuery nécessaires à EVAL_STORE_TARGET=gcp
	@if gcloud iam service-accounts describe $(CLOUDRUN_SA_EMAIL) --project=$(GCP_PROJECT) >/dev/null 2>&1; then \
		echo "✅ Compte de service $(CLOUDRUN_SA_EMAIL) déjà présent, création sautée."; \
	else \
		echo "🤖 Création du compte de service $(CLOUDRUN_SA_EMAIL)..."; \
		gcloud iam service-accounts create $(CLOUDRUN_SA_NAME) \
			--display-name="Berlue Cloud Run (éval GCP)" \
			--project=$(GCP_PROJECT); \
	fi
	@echo "🔐 Firestore lecture/écriture (datastore.user), restreint à la base (default)..."
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
		--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
		--role="roles/datastore.user" \
		--condition="$(FIRESTORE_CONDITION)" \
		--quiet
	@echo "🔐 BigQuery — lecture/écriture des données (dataEditor)..."
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
		--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
		--role="roles/bigquery.dataEditor" \
		--condition=None \
		--quiet
	@echo "🔐 BigQuery — exécution de requêtes (jobUser — sans lui, dataEditor seul ne permet pas de lancer une requête MERGE/SELECT)..."
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
		--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
		--role="roles/bigquery.jobUser" \
		--condition=None \
		--quiet
	@echo "🔐 Autorise votre compte à déployer Cloud Run avec ce service account (iam.serviceAccountUser, sur le SA lui-même)..."
	gcloud iam service-accounts add-iam-policy-binding $(CLOUDRUN_SA_EMAIL) \
		--member="user:$$(gcloud config get-value account)" \
		--role="roles/iam.serviceAccountUser" \
		--project=$(GCP_PROJECT) \
		--condition=None \
		--quiet
	@echo "🔐 Autorise votre compte à tester ce service account par impersonation (iam.serviceAccountTokenCreator — distinct de serviceAccountUser, qui ne permet que de l'attacher à Cloud Run) : 'gcloud auth print-access-token --impersonate-service-account=$(CLOUDRUN_SA_EMAIL)'..."
	gcloud iam service-accounts add-iam-policy-binding $(CLOUDRUN_SA_EMAIL) \
		--member="user:$$(gcloud config get-value account)" \
		--role="roles/iam.serviceAccountTokenCreator" \
		--project=$(GCP_PROJECT) \
		--condition=None \
		--quiet

# Accès par personne sur sa-berlue lui-même (pas sur Firestore/BigQuery
# directement — cf. firestore_grant/bigquery_grant pour ça). CLOUDRUN_SA_ROLE
# = impersonate (serviceAccountTokenCreator, pour lancer l'éval en local en
# impersonant sa-berlue — nécessaire depuis que GcpResultStore impersonne
# systématiquement, cf. docs/gcp/auth.md) ou deploy
# (serviceAccountUser, pour `make cloudrun_deploy` avec ce SA). Ne couvre pas
# le partage inter-projets (donner à sa-berlue d'un collègue l'accès à VOS
# données Firestore/BigQuery) — autre chose, pas encore outillé.
CLOUDRUN_SA_ROLE ?= impersonate

cloudrun_sa_grant: ## Donne l'accès à une personne sur sa-berlue (USER=email requis, CLOUDRUN_SA_ROLE=impersonate|deploy, défaut impersonate)
	@if [ -z "$(USER)" ]; then \
		echo "❌ ERREUR : USER manquant."; \
		echo "👉 Essayez : make cloudrun_sa_grant USER=personne@example.com CLOUDRUN_SA_ROLE=impersonate"; \
		exit 1; \
	fi
	@echo "🔐 Ajout de l'accès '$(CLOUDRUN_SA_ROLE)' pour $(USER) sur $(CLOUDRUN_SA_EMAIL)..."
	gcloud iam service-accounts add-iam-policy-binding $(CLOUDRUN_SA_EMAIL) \
		--member="user:$(USER)" \
		--role="roles/iam.$(if $(filter deploy,$(CLOUDRUN_SA_ROLE)),serviceAccountUser,serviceAccountTokenCreator)" \
		--project=$(GCP_PROJECT) \
		--condition=None \
		--quiet

cloudrun_sa_revoke: ## Retire l'accès d'une personne sur sa-berlue (USER=email requis, CLOUDRUN_SA_ROLE doit correspondre au rôle accordé, défaut impersonate)
	@if [ -z "$(USER)" ]; then \
		echo "❌ ERREUR : USER manquant."; \
		echo "👉 Essayez : make cloudrun_sa_revoke USER=personne@example.com CLOUDRUN_SA_ROLE=impersonate"; \
		exit 1; \
	fi
	@echo "🔓 Retrait de l'accès '$(CLOUDRUN_SA_ROLE)' pour $(USER) sur $(CLOUDRUN_SA_EMAIL)..."
	gcloud iam service-accounts remove-iam-policy-binding $(CLOUDRUN_SA_EMAIL) \
		--member="user:$(USER)" \
		--role="roles/iam.$(if $(filter deploy,$(CLOUDRUN_SA_ROLE)),serviceAccountUser,serviceAccountTokenCreator)" \
		--project=$(GCP_PROJECT) \
		--condition=None \
		--quiet

cloudrun_sa_test: ## Teste l'accès en impersonation à sa-berlue pour votre propre compte (nécessite CLOUDRUN_SA_ROLE=impersonate déjà accordé)
	@echo "🔎 Test impersonation de $(CLOUDRUN_SA_EMAIL)..."
	@if gcloud auth print-access-token --impersonate-service-account=$(CLOUDRUN_SA_EMAIL) >/dev/null 2>&1; then \
		echo "✅ Impersonation OK."; \
	else \
		echo "❌ Impersonation refusée (roles/iam.serviceAccountTokenCreator manquant, ou pas encore propagé — réessayer dans quelques dizaines de secondes)."; \
		exit 1; \
	fi
