# ==============================================================================
# 🧹 LINT
# ==============================================================================
# Python : ruff (dans requirements_dev.txt, cf. pyproject.toml pour la config).
# Shell : shellcheck — outil externe, pas installable via pip.
#   Debian/Ubuntu/WSL : sudo apt-get install shellcheck
#   macOS             : brew install shellcheck

lint_python: ## Vérifie le code Python avec ruff (make lint_python FIX=1 pour corriger ce qui est automatisable)
ifeq ($(FIX),1)
	ruff check --fix berlue/ tests/
else
	ruff check berlue/ tests/
endif

# format_python / lint_python_format : PAS inclus dans `lint` pour l'instant —
# `ruff format --check` reformatterait 14 fichiers d'un coup (tout le style du
# code existant, pas juste des erreurs), ce qui créerait des conflits avec les
# autres branches en cours. À activer plus tard dans une tâche dédiée, une fois
# les autres branches mergées.
format_python: ## Formate le code Python avec ruff (écrit les fichiers)
	ruff format berlue/ tests/

lint_python_format: ## Vérifie le formatage Python sans rien modifier (pas encore dans `lint`, cf. commentaire ci-dessus)
	ruff format --check berlue/ tests/

lint_shell: ## Vérifie les scripts shell avec shellcheck
	@command -v shellcheck >/dev/null 2>&1 || { \
		echo "❌ shellcheck n'est pas installé. Debian/Ubuntu/WSL : sudo apt-get install shellcheck — macOS : brew install shellcheck"; \
		exit 1; \
	}
	shellcheck scripts/*.sh

lint: lint_python lint_shell ## Lance les linters (Python + shell) — pas le formatage, cf. lint_python_format
