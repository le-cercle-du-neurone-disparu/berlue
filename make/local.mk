# ==============================================================================
# LOCAL ENVIRONMENT SETUP
# ==============================================================================

local_setup: ## Setup local virtual environment using pyenv
	@echo "🐍 Installing Python $(PYTHON_VERSION)..."
	pyenv install -s $(PYTHON_VERSION)
	@echo "📦 Creating virtual environment $(VENV_NAME)..."
	pyenv virtualenv $(PYTHON_VERSION) $(VENV_NAME) || true
	@echo "🔗 Linking virtual environment to current folder..."
	pyenv local $(VENV_NAME)
	@echo "🛠️ Upgrading pip..."
	pip install --upgrade pip
	@if [ ! -f setup.py ]; then \
		echo "❌ CRITICAL ERROR: setup.py not found! Cannot install the package."; \
		exit 1; \
	fi
	@echo "📚 Installing project and dependencies in editable mode..."
	pip install -e ".[dev]"
	@command -v direnv >/dev/null 2>&1 && direnv allow || true
	@echo "✅ Local setup complete! Your folder is now using $(VENV_NAME)."
