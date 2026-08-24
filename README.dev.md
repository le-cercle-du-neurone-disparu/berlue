# Guide dev — linters

## Pré-requis

- **Python** : `ruff` est dans `requirements_dev.txt`, installé via `make local_setup` (ou `pip install -e ".[dev]"`).
- **Shell** : `shellcheck` est un outil externe, pas installable via pip :
  ```bash
  # Debian / Ubuntu / WSL2
  sudo apt-get install shellcheck

  # macOS
  brew install shellcheck
  ```

## Lancer les linters

```bash
make lint            # tout (Python + shell)
make lint_python      # ruff check uniquement
make lint_shell        # shellcheck uniquement (scripts/*.sh)
```

Pour corriger automatiquement ce qui est fixable (imports inutilisés/mal triés, etc.) :

```bash
make lint_python FIX=1
```

## Formatage

`ruff format` (équivalent Black) existe mais **n'est pas dans `make lint`** pour l'instant — il reformatterait 14 fichiers d'un coup (tout le style existant, pas juste des erreurs), ce qui créerait des conflits avec les branches en cours. À activer dans une tâche dédiée une fois celles-ci mergées.

```bash
make format_python         # reformate les fichiers pour de vrai
make lint_python_format    # vérifie sans rien modifier (--check)
```

## Configuration

La config `ruff` (règles activées/ignorées, longueur de ligne) est dans [`pyproject.toml`](pyproject.toml) à la racine — c'est la seule source de vérité, pas de doublon ici.

Règles actives : `E`/`F` (pycodestyle + pyflakes), `I` (tri des imports), `UP` (syntaxe moderne), `B` (bugbear). `F403`/`F405` sont ignorées car `from berlue.params import *` est un pattern volontaire du projet. `line-length = 120`.

## Sans passer par `make`

```bash
ruff check berlue/ tests/              # équivalent à make lint_python
ruff check --fix berlue/ tests/        # équivalent à make lint_python FIX=1
shellcheck scripts/*.sh                # équivalent à make lint_shell
```
