# 1. Chargement du .env
-include .env

# 2. Export des variables pour qu'elles soient dispo dans le terminal
export

# 3. Valeurs dérivées (nom fixe + identité/paramètre propre à chacun dans .env)
SA_EMAIL = $(SA_NAME)@$(GCP_PROJECT).iam.gserviceaccount.com
BUCKET_NAME = $(GCP_PROJECT)-berlue_$(BUCKET_SUFFIX)

# 4. Import des sous-makefiles (Ordre logique MLOps)
# include make/local.mk # Étape 1 : Création de l'environnement local
# include make/gcp.mk
# include make/bigquery.mk
# include make/vm.mk
# include make/docker.mk
# include make/cloudrun.mk
# include make/pipeline.mk
# include make/tests.mk
include make/*.mk

# --- Menu d'aide automatique ---
.DEFAULT_GOAL := help

help: ## Affiche ce menu d'aide
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<commande>\033[0m\n\nCommandes disponibles :\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ==============================================================================
# 🧹 NETTOYAGE & SETUP DU PROJET
# ==============================================================================

reinstall_package: ## Force la désinstallation et réinstallation du package avec les dépendances dev
	@echo "🔄 Réinstallation du package..."
	@pip uninstall -y berlue || :
	@pip install -e ".[dev]"
	@echo "✅ Package réinstallé avec succès."

init_data_folders: ## Crée les dossiers locaux pour les données et les sorties de modèle
	@echo "📁 Création des dossiers de données locaux..."
	@mkdir -p data/raw
	@mkdir -p data/processed
	@mkdir -p training_outputs/metrics
	@mkdir -p training_outputs/models
	@mkdir -p training_outputs/params
	@echo "✅ Dossiers créés. (Assurez-vous qu'ils sont dans votre .gitignore !)"

clean: ## Nettoie le cache Python, les fichiers de build et les fichiers cachés de l'OS
	@echo "🧹 Nettoyage du projet..."
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@find . -type d -name ".ipynb_checkpoints" -exec rm -rf {} +
	@find . -type f -name "*.pyc" -delete
	@find . -type f -name ".coverage" -delete
	@find . -type f -name "*Zone.Identifier" -delete
	@find . -type f -name ".DS_Store" -delete
	@rm -rf build/ dist/ *.egg-info/ *.dist-info/
	@echo "✅ Nettoyage terminé avec succès."
