# Environnement local

```bash
make local_setup
```

Installe la version de Python fixée par le projet (`PYTHON_VERSION`,
`make/config.mk`) via `pyenv`, crée l'environnement virtuel `berlue-env`
(`VENV_NAME`) et le lie au dossier courant (`pyenv local`), installe le
package en mode éditable avec les dépendances de dev (`pip install -e
".[dev]"`), puis crée `.env` (`scripts/setup_env.sh` — questions
interactives avec valeurs par défaut, ex. `GCP_PROJECT` via `gcloud config`
si disponible ; ne touche jamais à un `.env` déjà présent).

Si `direnv` est installé, `direnv allow` est lancé automatiquement —
`.envrc` charge `.env` et active l'environnement virtuel à chaque `cd` dans
le dossier.

## Ensuite

- LLM local : `docs/setup/ollama-setup.md`
- Démarrer le pipeline : `docs/pipeline/hurlu_berlu.md`
