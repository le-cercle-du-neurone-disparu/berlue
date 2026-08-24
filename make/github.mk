# ==============================================================================
# 🐙 GITHUB / PULL REQUEST COMMANDS
# ==============================================================================
# Nécessite `gh` (GitHub CLI) authentifié : gh auth status

# Branche de base par défaut pour les PR (surchargeable : make gh_pr_create BASE_BRANCH=develop)
BASE_BRANCH ?= main

gh_pr_create: ## Pousse la branche courante et crée une PR non-interactive (titre/description auto-remplis depuis les commits)
	@echo "🚀 Push de la branche courante vers origin..."
	git push -u origin HEAD
	@echo "📬 Création de la PR (base: $(BASE_BRANCH))..."
	gh pr create --base $(BASE_BRANCH) --fill

gh_pr_toreview: ## Ajoute le label 'toreview' à la PR de la branche courante
	@echo "🏷️ Ajout du label 'toreview'..."
	@gh label create toreview --color 86CAAD --force >/dev/null 2>&1 || true
	gh pr edit --add-label toreview

gh_pr_wip: ## Retire le label 'toreview' de la PR de la branche courante (retour en WIP)
	@echo "🚧 Retrait du label 'toreview'..."
	gh pr edit --remove-label toreview

gh_pr_ls: ## Liste les PR ouvertes du dépôt
	@echo "📋 Liste des PR ouvertes..."
	gh pr list
