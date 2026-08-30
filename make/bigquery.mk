# ==============================================================================
# COMMANDES BIGQUERY
# ==============================================================================

bigquery_enable_api: gcp_check_cli_auth ## Active l'API BigQuery pour le projet
	@echo "⚙️ Activation de l'API BigQuery..."
	gcloud services enable bigquery.googleapis.com --project=$(GCP_PROJECT)

bigquery_create_dataset: ## Crée le dataset BigQuery s'il n'existe pas déjà
	@if bq show --project_id=$(GCP_PROJECT) $(BQ_DATASET) >/dev/null 2>&1; then \
		echo "✅ Dataset BigQuery $(BQ_DATASET) déjà présent, création sautée."; \
	else \
		echo "🗄️ Création du dataset BigQuery $(BQ_DATASET)..."; \
		bq mk \
			--location=$(BQ_REGION) \
			--project_id=$(GCP_PROJECT) \
			$(BQ_DATASET); \
	fi

bigquery_create_table: ## Crée une nouvelle table dans le dataset (req : TABLE_NAME)
	@if [ -z "$(TABLE_NAME)" ]; then \
		echo "❌ ERREUR : TABLE_NAME manquant."; \
		echo "👉 Essayez : make bigquery_create_table TABLE_NAME=my_table_name"; \
		exit 1; \
	fi
	@echo "📊 Création de la table $(TABLE_NAME) dans le dataset $(BQ_DATASET)..."
	bq mk \
		--location=$(BQ_REGION) \
		--project_id=$(GCP_PROJECT) \
		$(GCP_PROJECT):$(BQ_DATASET).$(TABLE_NAME)

bigquery_show: ## Affiche les détails du projet, du dataset ou de la table (opt : TABLE_NAME)
	@if [ -n "$(BQ_DATASET)" ] && [ -n "$(TABLE_NAME)" ]; then \
		echo "📊 Affichage de la table : $(BQ_DATASET).$(TABLE_NAME)"; \
		bq show $(GCP_PROJECT):$(BQ_DATASET).$(TABLE_NAME); \
	elif [ -n "$(BQ_DATASET)" ]; then \
		echo "📂 Affichage du dataset : $(BQ_DATASET)"; \
		bq show $(GCP_PROJECT):$(BQ_DATASET); \
	else \
		echo "🌍 Affichage des datasets du projet global :"; \
		bq ls --project_id=$(GCP_PROJECT); \
	fi

bigquery_delete_table: ## Supprime une table spécifique (req : TABLE_NAME)
	@if [ -z "$(TABLE_NAME)" ]; then \
		echo "❌ ERREUR : TABLE_NAME manquant."; \
		echo "👉 Essayez : make bigquery_delete_table TABLE_NAME=my_table_name"; \
		exit 1; \
	fi
	@echo "🗑️ Suppression de la table $(BQ_DATASET).$(TABLE_NAME)..."
	bq rm -f -t $(GCP_PROJECT):$(BQ_DATASET).$(TABLE_NAME)

bigquery_delete_dataset: ## Supprime le dataset et toutes ses tables
	@echo "💣 Suppression du dataset $(BQ_DATASET) et de tout son contenu..."
	bq rm -r -f -d $(GCP_PROJECT):$(BQ_DATASET)

# Accès par personne sur le dataset BigQuery de l'éval — ACL classique du
# dataset (`bq show`/`bq update`, cf. scripts/bigquery_dataset_access.py),
# pas IAM : `bq add-iam-policy-binding` sur un dataset nécessite un
# allowlisting non actif sur ce projet. BQ_ROLE = reader (lecture seule,
# défaut) ou writer (lecture+écriture).
BQ_ROLE ?= reader

bigquery_grant: ## Donne l'accès à une personne sur le dataset BigQuery de l'éval (USER=email requis, BQ_ROLE=reader|writer, défaut reader)
	@if [ -z "$(USER)" ]; then \
		echo "❌ ERREUR : USER manquant."; \
		echo "👉 Essayez : make bigquery_grant USER=personne@example.com BQ_ROLE=writer"; \
		exit 1; \
	fi
	@echo "🔐 Ajout de l'accès '$(BQ_ROLE)' pour $(USER) sur le dataset $(BQ_DATASET)..."
	python3 scripts/bigquery_dataset_access.py \
		--dataset-ref=$(GCP_PROJECT):$(BQ_DATASET) \
		--user=$(USER) \
		--role=$(if $(filter writer,$(BQ_ROLE)),WRITER,READER) \
		--action=grant

bigquery_revoke: ## Retire l'accès d'une personne sur le dataset BigQuery de l'éval (USER=email requis)
	@if [ -z "$(USER)" ]; then \
		echo "❌ ERREUR : USER manquant."; \
		echo "👉 Essayez : make bigquery_revoke USER=personne@example.com"; \
		exit 1; \
	fi
	@echo "🔓 Retrait de l'accès pour $(USER) sur le dataset $(BQ_DATASET)..."
	python3 scripts/bigquery_dataset_access.py \
		--dataset-ref=$(GCP_PROJECT):$(BQ_DATASET) \
		--user=$(USER) \
		--action=revoke

bigquery_test_read: ## Teste l'accès en lecture au dataset BigQuery de l'éval (liste ses tables)
	@echo "🔎 Test lecture sur le dataset $(BQ_DATASET)..."
	@bq ls $(GCP_PROJECT):$(BQ_DATASET) >/dev/null && echo "✅ Lecture OK." || { echo "❌ Lecture refusée."; exit 1; }

bigquery_test_write: ## Teste l'accès en écriture au dataset BigQuery de l'éval (crée puis supprime une table jetable)
	@echo "🔎 Test écriture sur le dataset $(BQ_DATASET)..."
	@bq query --use_legacy_sql=false --project_id=$(GCP_PROJECT) \
		"CREATE OR REPLACE TABLE \`$(GCP_PROJECT).$(BQ_DATASET)._access_probe\` AS SELECT 1 AS ok" >/dev/null \
		&& bq query --use_legacy_sql=false --project_id=$(GCP_PROJECT) \
			"DROP TABLE \`$(GCP_PROJECT).$(BQ_DATASET)._access_probe\`" >/dev/null \
		&& echo "✅ Écriture OK (table jetable créée puis supprimée)." \
		|| { echo "❌ Écriture refusée."; exit 1; }
