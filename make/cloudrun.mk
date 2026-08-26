# ==============================================================================
# COMMANDES CLOUD RUN
# ==============================================================================

cloudrun_deploy: ## Déploie le conteneur sur Google Cloud Run
	@echo "🚀 Déploiement de $(GAR_IMAGE) sur Cloud Run..."
	gcloud run deploy $(GAR_IMAGE) \
		--image $(GCP_REGION)-docker.pkg.dev/$(GCP_PROJECT)/$(ARTIFACTSREPO)/$(GAR_IMAGE):prod \
		--memory $(GAR_MEMORY) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--allow-unauthenticated

cloudrun_list: ## Liste tous les services Cloud Run actifs du projet
	@echo "📋 Listing des services Cloud Run..."
	gcloud run services list --project $(GCP_PROJECT)

cloudrun_url: ## Récupère l'URL en direct de l'API déployée
	@echo "🌍 Votre API est en ligne à :"
	@gcloud run services describe $(GAR_IMAGE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--format "value(status.url)"

cloudrun_logs: ## Suit les logs en temps réel du service Cloud Run
	@echo "📜 Suivi des logs pour $(GAR_IMAGE)... (Ctrl+C pour arrêter)"
	gcloud run services logs read $(GAR_IMAGE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--limit 50

cloudrun_delete: ## Supprime le service Cloud Run et met l'API hors ligne
	@echo "🗑️ Suppression du service Cloud Run $(GAR_IMAGE)..."
	gcloud run services delete $(GAR_IMAGE) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--quiet
