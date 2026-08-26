# Tests

## Lancer les tests

Trois façons de lancer la suite, selon ce que vous voulez couvrir :

```bash
make test_all         # tout : rapides + fonctionnels
make test_fast        # rapides : in-memory, aucune infra externe — c'est ce que lance la CI GitHub
make test_functional  # fonctionnels : besoin d'une infra réelle (.env, modèle entraîné, Docker, GCP...)
```

Pour lancer un seul fichier de test, ou une seule fonction de test, en
`pytest` directement (pratique en développement, pour itérer vite sur un
test précis) :

```bash
pytest tests/test_fusion.py                                    # tout un fichier
pytest tests/api/test_endpoints.py::test_favicon_returns_204    # une seule fonction
```

## Marquer un test comme fonctionnel

Par défaut, **un test sans marqueur est considéré rapide**. Pour signaler
qu'un test a besoin d'une infra réelle, ajoutez `@pytest.mark.functional`
au-dessus :

```python
@pytest.mark.functional
def test_env_file_exists():
    ...
```
