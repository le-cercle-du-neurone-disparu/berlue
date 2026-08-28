# Linting

### Pré-requis

- **Python** : `ruff` est dans `requirements_dev.txt`, installé via `make local_setup` (ou `pip install -e ".[dev]"`).
- **Shell** : `shellcheck` est un outil externe, pas installable via pip :
  ```bash
  # Debian / Ubuntu / WSL2
  sudo apt-get install shellcheck

  # macOS
  brew install shellcheck
  ```

### Commandes

```bash
make lint            # vérifie tout (Python + shell), ne modifie rien
make lint_format      # corrige et formate automatiquement le code Python
```

### Configuration

La config `ruff` (règles activées, longueur de ligne) est dans [`pyproject.toml`](../../pyproject.toml) à la racine.

Règles actives : `E`/`F` (pycodestyle + pyflakes), `I` (tri des imports), `UP` (syntaxe moderne), `B` (bugbear). Aucune règle ignorée. `line-length = 120`.

### CI

`.github/workflows/lint.yml` lance `make lint` sur chaque push vers `main` et chaque PR.
