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

# Compte gcloud actuellement actif — jamais `gcloud config get-value account`,
# vide (ou "(unset)") tant que personne n'a positionné core/account, ce qui
# produit un membre IAM `user:` que gcloud rejette. Évalué dans la recette et
# pas au parse : un $(shell ...) ici coûterait un appel gcloud à chaque `make`,
# y compris `make help`.
GCLOUD_ACTIVE_ACCOUNT = $$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | head -n1)

# Vérifie que la session gcloud est utilisable — SANS toucher à une API du
# projet. L'ancien test (`gcloud run services list`) échouait sur un projet
# où run.googleapis.com n'est pas encore activée, donc exactement sur le
# projet neuf que gcp_setup doit provisionner : message trompeur ("non
# authentifiée"), login inutile, et gcp_setup bloqué par son propre
# prérequis. Pire, gcloud propose alors d'activer l'API de façon interactive
# ("Would you like to enable and retry?") : sans `</dev/null` la recette
# gèle en attendant une réponse invisible. `print-access-token` ne dépend
# que du credential lui-même et échoue bien quand la session a expiré.
_gcp_check_cli_auth:
	@gcloud auth print-access-token >/dev/null 2>&1 </dev/null

# Deuxième niveau, distinct du premier : le projet existe-t-il et m'est-il
# accessible ? (cloudresourcemanager répond sans activation préalable.) Un
# projet inconnu n'est pas une session expirée — deux causes, deux messages.
_gcp_check_project:
	@gcloud projects describe $(GCP_PROJECT) >/dev/null 2>&1 </dev/null

gcp_auth: ## Authentifie la session gcloud CLI, et ne relance le login que si nécessaire
	@echo "🔎 Vérification de la session gcloud (CLI)..."
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

gcp_preflight: ## Vérifie tout ce qui doit être vrai AVANT de provisionner (outils, GCP_PROJECT, session, projet accessible, facturation) — prérequis de gcp_setup, échoue en nommant la cause
	@echo "🔎 Pré-vol..."
	@command -v gcloud >/dev/null 2>&1 || { \
		echo "❌ gcloud introuvable. Installez le Google Cloud SDK : https://cloud.google.com/sdk/docs/install"; \
		exit 1; \
	}
	@command -v bq >/dev/null 2>&1 || { \
		echo "❌ bq introuvable (livré avec le Google Cloud SDK) : gcloud components install bq"; \
		exit 1; \
	}
	@if [ -z "$(GCP_PROJECT)" ]; then \
		echo "❌ GCP_PROJECT est vide — renseignez-le dans .env (cf. make local_setup, docs/setup/local-setup.md)."; \
		exit 1; \
	fi
	@$(MAKE) --no-print-directory _gcp_check_cli_auth || { \
		echo "❌ Session gcloud absente ou expirée. Lancez : make gcp_auth"; \
		exit 1; \
	}
	@$(MAKE) --no-print-directory _gcp_check_project || { \
		echo "❌ Projet '$(GCP_PROJECT)' inaccessible ou inexistant (ce n'est PAS un problème d'authentification)."; \
		echo "   Vérifiez GCP_PROJECT dans .env, ou listez vos projets : make gcp_project_list"; \
		exit 1; \
	}
	@ACCOUNT="$(GCLOUD_ACTIVE_ACCOUNT)"; \
	if [ -z "$$ACCOUNT" ]; then \
		echo "❌ Aucun compte gcloud actif. Lancez : make gcp_auth"; \
		exit 1; \
	fi; \
	echo "✅ Compte actif : $$ACCOUNT — projet : $(GCP_PROJECT)"
	@BILLING=$$(gcloud beta billing projects describe $(GCP_PROJECT) --format="value(billingEnabled)" 2>/dev/null </dev/null); \
	if [ "$$BILLING" = "True" ]; then \
		echo "✅ Facturation active sur $(GCP_PROJECT)."; \
	elif [ -z "$$BILLING" ]; then \
		echo "⚠️  Facturation non vérifiable (droits insuffisants sur le compte de facturation, ou 'gcloud beta' absent) — on continue."; \
	else \
		echo "❌ Aucun compte de facturation lié à $(GCP_PROJECT) : Cloud Run, Artifact Registry et GCS refuseront tout."; \
		echo "   👉 https://console.cloud.google.com/billing/linkedaccount?project=$(GCP_PROJECT)"; \
		exit 1; \
	fi
	@CURRENT=$$(gcloud config get-value project 2>/dev/null); \
	if [ -z "$$CURRENT" ] || [ "$$CURRENT" = "(unset)" ]; then \
		echo "⚙️  gcloud n'a pas de projet par défaut — on positionne $(GCP_PROJECT)."; \
		gcloud config set project $(GCP_PROJECT) >/dev/null 2>&1 </dev/null; \
	elif [ "$$CURRENT" != "$(GCP_PROJECT)" ]; then \
		echo "⚠️  Projet gcloud par défaut ($$CURRENT) différent de GCP_PROJECT ($(GCP_PROJECT))."; \
		echo "   Sans effet ici (toutes les cibles passent --project), laissé tel quel volontairement."; \
	fi
	@echo "✅ Pré-vol OK."

# API activées en un seul appel plutôt qu'une par cible : `gcloud services
# enable` accepte une liste, et une seule opération à attendre au lieu de
# cinq. artifactregistry est à part (elle vit dans ARTIFACT_PROJECT, pas
# forcément GCP_PROJECT), appoptimize aussi (confort, cf. gcp_setup).
#
# iam/iamcredentials/cloudresourcemanager/storage sont listées par principe :
# mesurées "DISABLED" sur un projet où l'impersonation, la création de compte
# de service, les bindings IAM et les buckets fonctionnent pourtant — GCP les
# traite comme disponibles sans activation explicite. Les activer ne coûte
# rien et rend la dépendance lisible ; n'en attendre aucun déblocage.
GCP_APIS = \
	run.googleapis.com \
	firestore.googleapis.com \
	bigquery.googleapis.com \
	compute.googleapis.com \
	iam.googleapis.com \
	iamcredentials.googleapis.com \
	cloudresourcemanager.googleapis.com \
	storage.googleapis.com

gcp_enable_apis: gcp_check_cli_auth ## Active en un seul appel toutes les API dont Berlue dépend (+ Artifact Registry dans ARTIFACT_PROJECT)
	@echo "⚙️ Activation des API dans $(GCP_PROJECT)..."
	gcloud services enable $(GCP_APIS) --project=$(GCP_PROJECT) </dev/null
	@$(MAKE) --no-print-directory artifact_registry_enable_api

gcp_destroy: gcp_check_cli_auth ## Revert complet de gcp_setup ET de gcp_deploy — supprime les 5 services Cloud Run, le dépôt d'images, le bucket RAG, Firestore, le dataset BigQuery et sa-berlue (avec ses rôles). DÉTRUIT LES DONNÉES D'ÉVAL, confirmation par l'ID du projet.
	@echo "🚨 Ceci va supprimer DÉFINITIVEMENT sur $(GCP_PROJECT) :"
	@echo "   - Les 5 services Cloud Run : $(GAR_IMAGE)-test/staging/prod, $(CLOUDRUN_EVAL_SERVICE), $(CLOUDRUN_LLM_SERVICE)"
	@echo "   - Le dépôt Artifact Registry $(ARTIFACTSREPO) (et ses images), plus votre droit de push"
	@echo "   - Le bucket RAG $(RAG_BUCKET_NAME) (et l'index qu'il contient)"
	@echo "   - La base Firestore (default) — TOUT le cache de prédictions d'éval"
	@echo "   - Le dataset BigQuery $(BQ_DATASET) — TOUTES les matrices d'éval"
	@echo "   - Le compte de service $(CLOUDRUN_SA_EMAIL) et ses rôles projet"
	@echo "   Ces données ne sont récupérables par aucune commande de ce dépôt."
	@echo "   Couvre donc aussi tout ce qu'ont fait gcp_deploy (images + services) et"
	@echo "   gcp_up/gcp_eval_up (instances chaudes, redescendues avant suppression)."
	@echo "   Restent en place : les API activées (gratuites, les désactiver n'est pas"
	@echo "   sans risque pour le reste du projet) et vos images Docker LOCALES."
	@read -p "Pour confirmer, tapez l'ID du projet ($(GCP_PROJECT)) : " confirm && [ "$$confirm" = "$(GCP_PROJECT)" ] || { echo "Annulé."; exit 1; }
	@# gcp_down d'abord : si une suppression échoue plus bas, rien ne reste à
	@# min-instances=1 (donc facturé) parce qu'un gcp_up/gcp_eval_up traînait.
	@$(MAKE) --no-print-directory gcp_down || true
	@$(MAKE) --no-print-directory cloudrun_delete CLOUDRUN_ENV=test || true
	@$(MAKE) --no-print-directory cloudrun_delete CLOUDRUN_ENV=staging || true
	@$(MAKE) --no-print-directory cloudrun_delete CLOUDRUN_ENV=prod || true
	@$(MAKE) --no-print-directory cloudrun_eval_service_delete || true
	@$(MAKE) --no-print-directory cloudrun_llm_delete || true
	@$(MAKE) --no-print-directory artifact_registry_delete || true
	@$(MAKE) --no-print-directory artifact_registry_role_revoke || true
	@$(MAKE) --no-print-directory rag_bucket_delete || true
	@echo "💣 Suppression de la base Firestore (default)..."
	@gcloud firestore databases delete --database="(default)" --project=$(GCP_PROJECT) --quiet </dev/null || true
	@$(MAKE) --no-print-directory bigquery_delete_dataset || true
	@$(MAKE) --no-print-directory iam_teardown_cloudrun_service_account || true
	@echo "✅ Projet ramené à son état d'avant gcp_setup (hors API, laissées activées)."

gcp_setup: gcp_preflight ## Provisionne TOUTE l'infra GCP dont Berlue a besoin (API, Firestore, BigQuery, compte de service, Artifact Registry + auth Docker, bucket RAG) — rejouable ; ne build aucune image et ne crée aucun service Cloud Run (coût variable, cf. cloudrun.md)
	@echo "🚀 Mise en place de l'infra GCP sur $(GCP_PROJECT)..."
	@$(MAKE) --no-print-directory gcp_enable_apis
	@$(MAKE) --no-print-directory firestore_create_database
	@$(MAKE) --no-print-directory bigquery_create_dataset
	@$(MAKE) --no-print-directory iam_setup_cloudrun_service_account
	@$(MAKE) --no-print-directory artifact_registry_create
	@$(MAKE) --no-print-directory artifact_registry_role
	@$(MAKE) --no-print-directory docker_auth_if_available
	@$(MAKE) --no-print-directory rag_bucket_create
	@$(MAKE) --no-print-directory rag_bucket_grant_sa
	@$(MAKE) --no-print-directory gcp_enable_cost_observability || \
		echo "⚠️  Observabilité des coûts non activée (confort, sans impact sur le reste) — make gcp_enable_cost_observability pour réessayer."
	@echo ""
	@$(MAKE) --no-print-directory gcp_doctor

gcp_deploy: gcp_check_cli_auth ## Build + push les 3 images PUIS déploie les 3 services (CLOUDRUN_ENV=test|staging|prod, défaut test) — le barreau entre gcp_setup (l'infra) et gcp_up (allumer)
	@echo "📦 Build/push des images puis déploiement (CLOUDRUN_ENV=$(CLOUDRUN_ENV))..."
	@$(MAKE) --no-print-directory docker_build_push_all
	@$(MAKE) --no-print-directory cloudrun_deploy_all

gcp_doctor: ## Vérifie brique par brique que l'infra GCP est réellement utilisable (n'échoue pas à la première erreur) et rappelle ce qui reste à faire à la main
	@bash scripts/gcp_doctor.sh

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
	@if gcloud iam service-accounts describe $(CLOUDRUN_SA_EMAIL) --project=$(GCP_PROJECT) >/dev/null 2>&1 </dev/null; then \
		echo "✅ Compte de service $(CLOUDRUN_SA_EMAIL) déjà présent, création sautée."; \
	else \
		echo "🤖 Création du compte de service $(CLOUDRUN_SA_EMAIL)..."; \
		gcloud iam service-accounts create $(CLOUDRUN_SA_NAME) \
			--display-name="Berlue Cloud Run (éval GCP)" \
			--project=$(GCP_PROJECT) </dev/null; \
	fi
	@# Un compte de service tout juste créé n'est pas immédiatement visible des
	@# commandes suivantes (cohérence éventuelle) : les bindings ci-dessous
	@# échouent alors en "does not exist". Invisible sur un projet déjà
	@# provisionné, où le SA existe depuis longtemps.
	@$(RETRY) "propagation de $(CLOUDRUN_SA_EMAIL)" \
		gcloud iam service-accounts describe $(CLOUDRUN_SA_EMAIL) --project=$(GCP_PROJECT) --format="value(email)"
	@echo "🔐 Firestore lecture/écriture (datastore.user), restreint à la base (default)..."
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
		--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
		--role="roles/datastore.user" \
		--condition="$(FIRESTORE_CONDITION)" \
		--quiet </dev/null
	@echo "🔐 BigQuery — lecture/écriture des données (dataEditor)..."
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
		--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
		--role="roles/bigquery.dataEditor" \
		--condition=None \
		--quiet </dev/null
	@echo "🔐 BigQuery — exécution de requêtes (jobUser — sans lui, dataEditor seul ne permet pas de lancer une requête MERGE/SELECT)..."
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
		--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
		--role="roles/bigquery.jobUser" \
		--condition=None \
		--quiet </dev/null
	@ACCOUNT="$(GCLOUD_ACTIVE_ACCOUNT)"; \
	if [ -z "$$ACCOUNT" ]; then \
		echo "❌ Aucun compte gcloud actif — impossible de vous accorder les droits sur $(CLOUDRUN_SA_EMAIL). Lancez : make gcp_auth"; \
		exit 1; \
	fi; \
	echo "🔐 Autorise $$ACCOUNT à déployer Cloud Run avec ce service account (iam.serviceAccountUser, sur le SA lui-même)..."; \
	gcloud iam service-accounts add-iam-policy-binding $(CLOUDRUN_SA_EMAIL) \
		--member="user:$$ACCOUNT" \
		--role="roles/iam.serviceAccountUser" \
		--project=$(GCP_PROJECT) \
		--condition=None \
		--quiet </dev/null; \
	echo "🔐 Autorise $$ACCOUNT à tester ce service account par impersonation (iam.serviceAccountTokenCreator — distinct de serviceAccountUser, qui ne permet que de l'attacher à Cloud Run) : 'gcloud auth print-access-token --impersonate-service-account=$(CLOUDRUN_SA_EMAIL)'..."; \
	gcloud iam service-accounts add-iam-policy-binding $(CLOUDRUN_SA_EMAIL) \
		--member="user:$$ACCOUNT" \
		--role="roles/iam.serviceAccountTokenCreator" \
		--project=$(GCP_PROJECT) \
		--condition=None \
		--quiet </dev/null

# Contrepartie exacte d'iam_setup_cloudrun_service_account. Les bindings de
# niveau PROJET doivent être retirés AVANT la suppression du compte de
# service : supprimer le SA d'abord laisse dans la policy du projet des
# entrées orphelines `deleted:serviceAccount:...?uid=...` que plus rien ne
# nettoie. Les deux bindings posés sur le SA lui-même (serviceAccountUser,
# serviceAccountTokenCreator) disparaissent avec lui, eux.
iam_teardown_cloudrun_service_account: gcp_check_cli_auth ## Retire les rôles projet de sa-berlue puis supprime le compte de service (appelée par gcp_destroy)
	@echo "🔓 Retrait des rôles projet de $(CLOUDRUN_SA_EMAIL)..."
	@gcloud projects remove-iam-policy-binding $(GCP_PROJECT) \
		--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
		--role="roles/datastore.user" \
		--condition="$(FIRESTORE_CONDITION)" \
		--quiet </dev/null || true
	@gcloud projects remove-iam-policy-binding $(GCP_PROJECT) \
		--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
		--role="roles/bigquery.dataEditor" \
		--condition=None \
		--quiet </dev/null || true
	@gcloud projects remove-iam-policy-binding $(GCP_PROJECT) \
		--member="serviceAccount:$(CLOUDRUN_SA_EMAIL)" \
		--role="roles/bigquery.jobUser" \
		--condition=None \
		--quiet </dev/null || true
	@echo "💣 Suppression du compte de service $(CLOUDRUN_SA_EMAIL)..."
	@gcloud iam service-accounts delete $(CLOUDRUN_SA_EMAIL) \
		--project=$(GCP_PROJECT) --quiet </dev/null || true

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
