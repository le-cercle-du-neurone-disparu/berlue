# ==============================================================================
# BIGQUERY COMMANDS
# ==============================================================================

bigquery_create_dataset: ## Create the BigQuery dataset
	@echo "🗄️ Creating BigQuery dataset $(BQ_DATASET)..."
	bq mk \
		--location=$(BQ_REGION) \
		--project_id=$(GCP_PROJECT) \
		$(BQ_DATASET)

bigquery_create_table: ## Create a new table in the dataset (req: TABLE_NAME)
	@if [ -z "$(TABLE_NAME)" ]; then \
		echo "❌ ERROR: Missing TABLE_NAME."; \
		echo "👉 Try: make bigquery_create_table TABLE_NAME=my_table_name"; \
		exit 1; \
	fi
	@echo "📊 Creating table $(TABLE_NAME) in dataset $(BQ_DATASET)..."
	bq mk \
		--location=$(BQ_REGION) \
		--project_id=$(GCP_PROJECT) \
		$(GCP_PROJECT):$(BQ_DATASET).$(TABLE_NAME)

bigquery_show: ## Show details of the project, dataset, or table (opt: TABLE_NAME)
	@if [ -n "$(BQ_DATASET)" ] && [ -n "$(TABLE_NAME)" ]; then \
		echo "📊 Showing table: $(BQ_DATASET).$(TABLE_NAME)"; \
		bq show $(GCP_PROJECT):$(BQ_DATASET).$(TABLE_NAME); \
	elif [ -n "$(BQ_DATASET)" ]; then \
		echo "📂 Showing dataset: $(BQ_DATASET)"; \
		bq show $(GCP_PROJECT):$(BQ_DATASET); \
	else \
		echo "🌍 Showing global project datasets:"; \
		bq ls --project_id=$(GCP_PROJECT); \
	fi

bigquery_delete_table: ## Delete a specific table (req: TABLE_NAME)
	@if [ -z "$(TABLE_NAME)" ]; then \
		echo "❌ ERROR: Missing TABLE_NAME."; \
		echo "👉 Try: make bigquery_delete_table TABLE_NAME=my_table_name"; \
		exit 1; \
	fi
	@echo "🗑️ Deleting table $(BQ_DATASET).$(TABLE_NAME)..."
	bq rm -f -t $(GCP_PROJECT):$(BQ_DATASET).$(TABLE_NAME)

bigquery_delete_dataset: ## Delete the dataset and all its tables
	@echo "💣 Deleting dataset $(BQ_DATASET) and all its contents..."
	bq rm -r -f -d $(GCP_PROJECT):$(BQ_DATASET)
