# Tests

## Lancer les tests

Quatre façons de lancer la suite, selon ce que vous voulez couvrir :

```bash
make test_all         # tout : rapides + fonctionnels + gcp
make test_fast        # rapides : in-memory, aucune infra externe — c'est ce que lance la CI GitHub
make test_functional  # infra LOCALE réelle : .env, Ollama, index RAG construit, modèle entraîné
make test_gcp         # vrai projet GCP : Firestore et BigQuery, via impersonation de sa-berlue
```

Les lanes sont disjointes : `test_functional` exclut les tests `gcp`. C'est
ce qui la garde rapide (~10 s) — elle ne fait aucun appel réseau vers GCP,
contrairement à `test_gcp` (~1 min 20, dominé par la latence des appels).

Pour lancer un seul fichier de test, ou une seule fonction de test, en
`pytest` directement (pratique en développement, pour itérer vite sur un
test précis) :

```bash
pytest tests/test_rag.py                                       # tout un fichier
pytest tests/api/test_endpoints.py::test_favicon_returns_204    # une seule fonction
```

## Marquer un test

Par défaut, **un test sans marqueur est considéré rapide**. Deux marqueurs
selon l'infra nécessaire :

- `@pytest.mark.functional` — infra locale (Ollama, index RAG, `.env`) ;
- `@pytest.mark.gcp` — vrai projet GCP. À poser sur tout test qui écrit ou
  lit Firestore/BigQuery pour de bon, sinon il alourdit `test_functional` et
  la fait échouer sur un poste sans accès GCP.

Un marqueur s'applique à tout un fichier via `pytestmark = pytest.mark.gcp`
en tête de module (cf. `tests/test_gcp_result_store.py`).

Pour signaler qu'un test a besoin d'une infra locale réelle, ajoutez
`@pytest.mark.functional` au-dessus :

```python
@pytest.mark.functional
def test_env_file_exists():
    ...
```

## Tests Docker : image dédiée

Les tests fonctionnels qui buildent/lancent un conteneur (`tests/api/test_server_lifecycle.py`)
utilisent un tag Docker dédié (`DOCKER_TAG=test-lifecycle`), pas le tag `dev`
par défaut de `make docker_build_local`/`docker_run_local` — pour ne pas
écraser une image `:dev` que vous utilisez peut-être en parallèle (un
`docker-compose up` ou un `make docker_run_local` lancé à côté).
