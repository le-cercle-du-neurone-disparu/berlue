# ==============================================================================
# COMMANDES COMPUTE ENGINE (VM)
# ==============================================================================

vm_create: iam_setup_service_account ## Crée la machine virtuelle avec les droits IAM
	@echo "🖥️ Création de la VM $(INSTANCE) avec le compte de service $(SA_EMAIL)..."
	gcloud compute instances create $(INSTANCE) \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE) \
		--image-family=$(IMAGE_FAMILY) \
		--image-project=$(IMAGE_PROJECT) \
		--machine-type=$(MACHINE_TYPE) \
		--service-account=$(SA_EMAIL) \
		--scopes=https://www.googleapis.com/auth/cloud-platform

vm_setup: ## Envoie et exécute le script de setup sur la VM
	@echo "📦 Envoi du script de setup vers la VM..."
	gcloud compute scp scripts/setup_vm.sh $(INSTANCE):~/ \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE)
	@echo "⚙️ Exécution du script sur la VM..."
	gcloud compute ssh $(INSTANCE) \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE) \
		--command="bash ~/setup_vm.sh $(PYTHON_VERSION) $(VENV_NAME)"
	@echo "🗑️ Nettoyage du script sur la VM..."
	gcloud compute ssh $(INSTANCE) \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE) \
		--command="rm ~/setup_vm.sh"

vm_connect: ## Se connecte à la VM via SSH avec agent forwarding
	@if [ -z "$(INSTANCE)" ]; then \
		echo "❌ ERREUR : nom d'INSTANCE manquant."; \
		echo "👉 Essayez : make vm_connect INSTANCE=my-server"; \
		exit 1; \
	fi
	@echo "🔌 Connexion à $(INSTANCE)..."
	gcloud compute ssh $(INSTANCE) --project=$(GCP_PROJECT) --zone=$(ZONE) --ssh-flag="-A"

vm_start: ## Démarre la machine virtuelle (la facturation CPU reprend)
	@if [ -z "$(INSTANCE)" ]; then \
		echo "❌ ERREUR : nom d'INSTANCE manquant."; \
		exit 1; \
	fi
	@echo "🟢 Démarrage de la machine $(INSTANCE)..."
	gcloud compute instances start $(INSTANCE) \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE)

vm_stop: ## Arrête la machine virtuelle (économise la facturation CPU)
	@if [ -z "$(INSTANCE)" ]; then \
		echo "❌ ERREUR : nom d'INSTANCE manquant."; \
		exit 1; \
	fi
	@echo "🔴 Arrêt de la machine $(INSTANCE)... (le CPU n'est plus facturé)"
	gcloud compute instances stop $(INSTANCE) \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE)

vm_delete: ## Supprime définitivement la machine virtuelle
	@echo "💣 Suppression définitive de la machine $(INSTANCE)..."
	gcloud compute instances delete $(INSTANCE) \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE) \
		--quiet
