# ==============================================================================
# CLOUD RUN COMMANDS
# ==============================================================================

cloudrun_deploy: ## Deploy the container to Google Cloud Run
	@echo "🚀 Deploying $(GAR_IMAGE) to Cloud Run..."
	gcloud run deploy $(GAR_IMAGE) \
		--image $(GCP_REGION)-docker.pkg.dev/$(GCP_PROJECT)/$(ARTIFACTSREPO)/$(GAR_IMAGE):prod \
		--memory $(GAR_MEMORY) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--allow-unauthenticated

cloudrun_list: ## List all active Cloud Run services in the project
	@echo "📋 Listing Cloud Run services..."
	gcloud run services list --project $(GCP_PROJECT)

cloudrun_url: ## Retrieve the live URL of the deployed API
	@echo "🌍 Your API is live at:"
	@gcloud run services describe $(GAR_IMAGE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--format "value(status.url)"

cloudrun_logs: ## Tail the real-time logs of the Cloud Run service
	@echo "📜 Tailing logs for $(GAR_IMAGE)... (Press Ctrl+C to stop)"
	gcloud run services logs read $(GAR_IMAGE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--limit 50

cloudrun_delete: ## Delete the Cloud Run service and take the API offline
	@echo "🗑️ Deleting Cloud Run service $(GAR_IMAGE)..."
	gcloud run services delete $(GAR_IMAGE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--quiet
