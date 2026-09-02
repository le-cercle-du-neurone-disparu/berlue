# ==============================================================================
# COMMANDES FIRESTORE
# ==============================================================================
# Cache des prédictions individuelles de l'évaluation du pipeline Berlue
# (EVAL_STORE_TARGET=gcp) — une seule base Firestore par projet, mode Native.
# Credentials pour ces cibles (provisionnement) : session gcloud CLI (cf.
# gcp_auth dans make/gcp.mk), pas de clé de compte de service à part. Le
# runtime (GcpResultStore) a sa propre note d'auth, cf.
# docs/evaluation/storage.md#implémentation-gcp-firestore--bigquery.

firestore_enable_api: gcp_check_cli_auth ## Active l'API Firestore pour le projet
	@echo "⚙️ Activation de l'API Firestore..."
	gcloud services enable firestore.googleapis.com --project=$(GCP_PROJECT) </dev/null

firestore_create_database: gcp_check_cli_auth ## Crée la base Firestore (mode Native) du projet si elle n'existe pas déjà — une seule par projet
	@if gcloud firestore databases describe --database='(default)' --project=$(GCP_PROJECT) >/dev/null 2>&1 </dev/null; then \
		echo "✅ Base Firestore déjà présente, création sautée."; \
	else \
		echo "🔥 Création de la base Firestore (native, $(GCP_REGION))..."; \
		$(RETRY) "création de la base Firestore" \
			gcloud firestore databases create \
				--project=$(GCP_PROJECT) \
				--location=$(GCP_REGION) \
				--type=firestore-native; \
	fi

# Accès par personne sur la base Firestore de l'éval — IAM projet (Firestore
# n'a pas de binding IAM scopé à une base précise), restreint à la base
# `(default)` via une condition IAM pour ne pas déborder sur d'éventuelles
# autres bases du même projet. FIRESTORE_ROLE = reader (lecture seule,
# défaut) ou writer (lecture+écriture) — la révocation doit utiliser le même
# rôle que celui accordé (le binding IAM = membre + rôle + condition).
FIRESTORE_ROLE ?= reader
FIRESTORE_CONDITION = expression=resource.name == \"projects/$(GCP_PROJECT)/databases/(default)\",title=berlue-eval-firestore-default

# La condition ne s'applique qu'à l'écriture. `datastore.databases.list` porte
# sur le projet, pas sur une base : une condition qui nomme une base précise ne
# peut jamais y correspondre, et le listing des bases est alors refusé — même
# à qui a le droit de les lire. La lecture est donc accordée sans condition,
# ce qui reste étroit : le rôle est en lecture seule et le projet n'héberge
# qu'une base.
FIRESTORE_GRANT_CONDITION = $(if $(filter writer,$(FIRESTORE_ROLE)),$(FIRESTORE_CONDITION),None)

firestore_grant: ## Donne l'accès à une personne sur la base Firestore de l'éval (USER=email requis, FIRESTORE_ROLE=reader|writer, défaut reader)
	@if [ -z "$(USER)" ]; then \
		echo "❌ ERREUR : USER manquant."; \
		echo "👉 Essayez : make firestore_grant USER=personne@example.com FIRESTORE_ROLE=writer"; \
		exit 1; \
	fi
	@echo "🔐 Ajout de l'accès '$(FIRESTORE_ROLE)' pour $(USER) sur la base Firestore (default)..."
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
		--member="user:$(USER)" \
		--role="roles/datastore.$(if $(filter writer,$(FIRESTORE_ROLE)),user,viewer)" \
		--condition="$(FIRESTORE_GRANT_CONDITION)"

firestore_revoke: ## Retire l'accès d'une personne sur la base Firestore de l'éval (USER=email requis, FIRESTORE_ROLE doit correspondre au rôle accordé, défaut reader)
	@if [ -z "$(USER)" ]; then \
		echo "❌ ERREUR : USER manquant."; \
		echo "👉 Essayez : make firestore_revoke USER=personne@example.com FIRESTORE_ROLE=writer"; \
		exit 1; \
	fi
	@echo "🔓 Retrait de l'accès '$(FIRESTORE_ROLE)' pour $(USER) sur la base Firestore (default)..."
	gcloud projects remove-iam-policy-binding $(GCP_PROJECT) \
		--member="user:$(USER)" \
		--role="roles/datastore.$(if $(filter writer,$(FIRESTORE_ROLE)),user,viewer)" \
		--condition="$(FIRESTORE_GRANT_CONDITION)"

firestore_test_read: ## Teste l'accès en lecture à la base Firestore de l'éval
	@echo "🔎 Test lecture sur Firestore..."
	@TOKEN=$$(gcloud auth print-access-token); \
	CODE=$$(curl -s -o /dev/null -w "%{http_code}" \
		"https://firestore.googleapis.com/v1/projects/$(GCP_PROJECT)/databases/(default)/documents/_access_probe/probe" \
		-H "Authorization: Bearer $$TOKEN"); \
	if [ "$$CODE" = "200" ] || [ "$$CODE" = "404" ]; then \
		echo "✅ Lecture OK (http $$CODE)."; \
	else \
		echo "❌ Lecture refusée (http $$CODE)."; \
		exit 1; \
	fi

firestore_test_write: ## Teste l'accès en écriture à la base Firestore de l'éval (crée puis supprime un document jetable)
	@echo "🔎 Test écriture sur Firestore..."
	@TOKEN=$$(gcloud auth print-access-token); \
	URL="https://firestore.googleapis.com/v1/projects/$(GCP_PROJECT)/databases/(default)/documents/_access_probe/probe"; \
	CODE=$$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$$URL" \
		-H "Authorization: Bearer $$TOKEN" -H "Content-Type: application/json" \
		-d '{"fields": {"ok": {"booleanValue": true}}}'); \
	if [ "$$CODE" = "200" ]; then \
		curl -s -X DELETE "$$URL" -H "Authorization: Bearer $$TOKEN" >/dev/null; \
		echo "✅ Écriture OK (document jetable créé puis supprimé)."; \
	else \
		echo "❌ Écriture refusée (http $$CODE)."; \
		exit 1; \
	fi
