# Environnement local

## Prérequis (outillage)

| Outil | Pourquoi | Sans lui |
|---|---|---|
| `pyenv` (+ `pyenv-virtualenv`) | version de Python et venv du projet | `make local_setup` échoue |
| `gcloud` + `bq` (Google Cloud SDK) | toute la partie GCP | `make gcp_setup` s'arrête au pré-vol |
| `docker` | build/push des images, API en conteneur | seulement build/push indisponibles |
| `direnv` | charge `.env` et le venv en entrant dans le dossier | à faire à la main |
| `shellcheck` | `make lint` sur les scripts shell | `make lint` échoue |

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

Clés écrites (les mêmes que [`.env.sample`](../../.env.sample), qui fait
foi) : `GCP_PROJECT`, `GOOGLE_APPLICATION_CREDENTIALS` (optionnel),
`BUCKET_SUFFIX`, `RUN_ENV`, `PORT`, `DATA_SIZE`,
`NOTIFY_BASE_URL` (optionnel), `BERLUE_LOG_LEVEL`, `EXTRACT_MODEL`. Les
valeurs par défaut proposées sont volontairement non vides : une clé
présente mais vide dans `.env` écrase le défaut de `berlue/params.py` par
une chaîne vide, elle ne le laisse pas s'appliquer.

Si `direnv` est installé :

```bash
direnv allow
```

est lancé automatiquement — `.envrc` charge `.env` et active l'environnement
virtuel à chaque changement de dossier.

## Ensuite

- LLM local : [`ollama-setup.md`](ollama-setup.md)
- Démarrer le pipeline : [`hurlu_berlu.md`](../pipeline/hurlu_berlu.md)
- Infra GCP (une fois `GCP_PROJECT` renseigné) : [`gcp.md`](gcp.md)
