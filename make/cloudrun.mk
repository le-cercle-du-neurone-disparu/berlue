# ==============================================================================
# COMMANDES CLOUD RUN
# ==============================================================================
# 3 environnements (test/staging/prod), même projet GCP, 3 services Cloud Run
# nommés $(GAR_IMAGE)-<env>, déployés depuis la même image :prod (build une
# fois via docker_build_prod/docker_push_prod, promotion progressive
# test -> staging -> prod). Sélection via CLOUDRUN_ENV=test|staging|prod
# (défaut test — jamais lu depuis .env, volontairement, pour ne pas risquer un
# déploiement accidentel vers le mauvais environnement).

CLOUDRUN_ENV ?= test

cloudrun_deploy: gcp_check_auth ## Déploie sur Cloud Run selon CLOUDRUN_ENV=test|staging|prod (défaut test)
	@echo "🚀 Déploiement de $(GAR_IMAGE)-$(CLOUDRUN_ENV) sur Cloud Run (accès public : $(CLOUDRUN_PUBLIC_$(CLOUDRUN_ENV)))..."
	gcloud run deploy $(GAR_IMAGE)-$(CLOUDRUN_ENV) \
		--image $(GCP_REGION)-docker.pkg.dev/$(GCP_PROJECT)/$(ARTIFACTSREPO)/$(GAR_IMAGE):prod \
		--memory $(GAR_MEMORY) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		$(if $(filter true,$(CLOUDRUN_PUBLIC_$(CLOUDRUN_ENV))),--allow-unauthenticated,--no-allow-unauthenticated)

cloudrun_list: ## Liste tous les services Cloud Run actifs du projet
	@echo "📋 Listing des services Cloud Run..."
	gcloud run services list --project $(GCP_PROJECT)

cloudrun_url: ## Récupère l'URL de l'environnement CLOUDRUN_ENV=test|staging|prod (défaut test)
	@echo "🌍 $(GAR_IMAGE)-$(CLOUDRUN_ENV) est en ligne à :"
	@gcloud run services describe $(GAR_IMAGE)-$(CLOUDRUN_ENV) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--format "value(status.url)"

cloudrun_logs: ## Suit les logs de l'environnement CLOUDRUN_ENV=test|staging|prod (défaut test)
	@echo "📜 Suivi des logs pour $(GAR_IMAGE)-$(CLOUDRUN_ENV)... (Ctrl+C pour arrêter)"
	gcloud run services logs read $(GAR_IMAGE)-$(CLOUDRUN_ENV) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--limit 50

cloudrun_delete: ## Supprime l'environnement CLOUDRUN_ENV=test|staging|prod (défaut test) et le met hors ligne
	@echo "🗑️ Suppression du service Cloud Run $(GAR_IMAGE)-$(CLOUDRUN_ENV)..."
	gcloud run services delete $(GAR_IMAGE)-$(CLOUDRUN_ENV) \
		--region $(GCP_REGION) \
		--project $(GCP_PROJECT) \
		--quiet
