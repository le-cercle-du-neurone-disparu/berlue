# ==============================================================================
# COMPUTE ENGINE (VM) COMMANDS
# ==============================================================================

vm_create: iam_setup_service_account ## Create the virtual machine with IAM rights
	@echo "🖥️ Creating VM $(INSTANCE) with service account $(SA_EMAIL)..."
	gcloud compute instances create $(INSTANCE) \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE) \
		--image-family=$(IMAGE_FAMILY) \
		--image-project=$(IMAGE_PROJECT) \
		--machine-type=$(MACHINE_TYPE) \
		--service-account=$(SA_EMAIL) \
		--scopes=https://www.googleapis.com/auth/cloud-platform

vm_setup: ## Send and execute the setup script on the VM
	@echo "📦 Sending setup script to VM..."
	gcloud compute scp scripts/setup_vm.sh $(INSTANCE):~/ \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE)
	@echo "⚙️ Executing script on the VM..."
	gcloud compute ssh $(INSTANCE) \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE) \
		--command="bash ~/setup_vm.sh $(PYTHON_VERSION) $(VENV_NAME)"
	@echo "🗑️ Cleaning up script on the VM..."
	gcloud compute ssh $(INSTANCE) \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE) \
		--command="rm ~/setup_vm.sh"

vm_connect: ## Connect to the VM via SSH with agent forwarding
	@if [ -z "$(INSTANCE)" ]; then \
		echo "❌ ERROR: Missing INSTANCE name."; \
		echo "👉 Try: make vm_connect INSTANCE=my-server"; \
		exit 1; \
	fi
	@echo "🔌 Connecting to $(INSTANCE)..."
	gcloud compute ssh $(INSTANCE) --project=$(GCP_PROJECT) --zone=$(ZONE) --ssh-flag="-A"

vm_start: ## Start the virtual machine (CPU billing resumes)
	@if [ -z "$(INSTANCE)" ]; then \
		echo "❌ ERROR: Missing INSTANCE name."; \
		exit 1; \
	fi
	@echo "🟢 Starting machine $(INSTANCE)..."
	gcloud compute instances start $(INSTANCE) \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE)

vm_stop: ## Stop the virtual machine (Save CPU billing)
	@if [ -z "$(INSTANCE)" ]; then \
		echo "❌ ERROR: Missing INSTANCE name."; \
		exit 1; \
	fi
	@echo "🔴 Stopping machine $(INSTANCE)... (CPU is no longer billed)"
	gcloud compute instances stop $(INSTANCE) \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE)

vm_delete: ## Delete the virtual machine permanently
	@echo "💣 Deleting machine $(INSTANCE) permanently..."
	gcloud compute instances delete $(INSTANCE) \
		--project=$(GCP_PROJECT) \
		--zone=$(ZONE) \
		--quiet
