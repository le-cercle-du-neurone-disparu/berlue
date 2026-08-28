# Environnement local

```bash
make local_setup
```

Installe la version de Python fixée par le projet (`PYTHON_VERSION`,
`make/config.mk`) via `pyenv`, crée l'environnement virtuel `berlue-env`
(`VENV_NAME`) et le lie au dossier courant :

```bash
pyenv local berlue-env
```

Installe le package en mode éditable avec les dépendances de dev :

```bash
pip install -e ".[dev]"
```

Puis crée `.env` (`scripts/setup_env.sh` — questions interactives avec
valeurs par défaut ; ne touche jamais à un `.env` déjà présent). Par
exemple pour `GCP_PROJECT`, la valeur par défaut proposée vient de :

```bash
gcloud config get-value project
```

si disponible.

Si `direnv` est installé :

```bash
direnv allow
```

est lancé automatiquement — `.envrc` charge `.env` et active l'environnement
virtuel à chaque changement de dossier.

## Ensuite

- LLM local : [`ollama-setup.md`](ollama-setup.md)
- Démarrer le pipeline : [`hurlu_berlu.md`](../pipeline/hurlu_berlu.md)
