# ==============================================================================
# COMMANDES BIGQUERY
# ==============================================================================

bigquery_create_dataset: ## Crée le dataset BigQuery
	@echo "🗄️ Création du dataset BigQuery $(BQ_DATASET)..."
	bq mk \
		--location=$(BQ_REGION) \
		--project_id=$(GCP_PROJECT) \
		$(BQ_DATASET)

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
