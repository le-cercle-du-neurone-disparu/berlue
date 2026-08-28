# Client Ollama en local

Wrapper autour du LLM local — voir `berlue/llm/client.py` (`OllamaClient`).
Point de contact utilisé par `selfcheck/sampler.py` et
`pipeline/hurlu_berlu.py` pour générer des réponses (`generate`/
`generate_many`) ; `berlue/api/service.py` appelle en plus le SDK `ollama`
directement pour lister les modèles installés (`get_available_llms`), hors
`OllamaClient`.

## Prérequis

- Ollama qui tourne en local avec un modèle disponible — cf.
  `docs/setup/ollama-setup.md` (`make ollama_setup` puis `make ollama_check`).

## Utiliser directement

```bash
python -m berlue.llm.client
```

Auto-détecte le serveur Ollama et le premier modèle installé, puis lance un
smoke-test fixe : un `generate()` et un `generate_many(k=3)` sur une question
codée dans le script — le script ne lit pas `sys.argv`, `PROMPT`/`K` sur
`make llm_generate`/`llm_generate_many` n'ont donc aucun effet.

Changer de modèle pour de vrai : `BERLUE_OLLAMA_MODEL` n'est lu que par
`OllamaClient()` construit depuis du code (cf. `docs/pipeline/hurlu_berlu.md`,
`docs/pipeline/selfcheck.md`), pas par ce script de smoke-test qui
auto-détecte son propre modèle.

## Lancer les tests liés

```bash
pytest tests/test_llm_client.py -v
```

Deux catégories dans le même fichier :

- **Unitaires** (par défaut) — le client Ollama interne (`OllamaClient.client`)
  est remplacé par un faux client, aucun réseau requis. Couvrent le happy
  path, les 3 branches d'erreur de `generate()`, et la distribution des
  températures de `generate_many()`.
- **Fonctionnels** (`@pytest.mark.functional`) — appellent le vrai Ollama :

  ```bash
  make test_llm_functional
  ```
