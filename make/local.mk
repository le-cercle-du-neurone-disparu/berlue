# ==============================================================================
# CONFIGURATION DE L'ENVIRONNEMENT LOCAL
# ==============================================================================

local_setup: ## Configure l'environnement virtuel local avec pyenv
	@echo "🐍 Installation de Python $(PYTHON_VERSION)..."
	pyenv install -s $(PYTHON_VERSION)
	@echo "📦 Création de l'environnement virtuel $(VENV_NAME)..."
	pyenv virtualenv $(PYTHON_VERSION) $(VENV_NAME) || true
	@echo "🔗 Liaison de l'environnement virtuel au dossier courant..."
	pyenv local $(VENV_NAME)
	@echo "🛠️ Mise à jour de pip..."
	pip install --upgrade pip
	@if [ ! -f setup.py ]; then \
		echo "❌ ERREUR CRITIQUE : setup.py introuvable ! Impossible d'installer le package."; \
		exit 1; \
	fi
	@echo "📚 Installation du projet et des dépendances en mode éditable..."
	pip install -e ".[dev]"
	@bash scripts/setup_env.sh
	@command -v direnv >/dev/null 2>&1 && direnv allow || true
	@echo "✅ Configuration locale terminée ! Votre dossier utilise maintenant $(VENV_NAME)."
