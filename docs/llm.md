# Client Ollama en local

Wrapper autour du LLM local — voir `berlue/llm/client.py` (`OllamaClient`).
Seul point de contact avec Ollama dans tout le repo ; `selfcheck/sampler.py`
et `pipeline/hurlu_berlu.py` passent par lui, jamais directement par le SDK
`ollama`.

## Prérequis

- Ollama qui tourne en local avec un modèle disponible — cf.
  `docs/ollama-setup.md` (`make ollama_setup` puis `make ollama_check`).

## Utiliser directement

```bash
make llm_generate                              # une génération, prompt par défaut
make llm_generate PROMPT="Pourquoi la mer est salée ?"
make llm_generate_many                         # K=3 générations à températures espacées
make llm_generate_many K=5
```

Équivalent direct sans `make` :

```bash
python -m berlue.llm.client "Pourquoi la mer est salée ?"        # une génération
python -m berlue.llm.client "Pourquoi la mer est salée ?" --k 5  # 5 générations
```

Options complètes : `python -m berlue.llm.client --help`
(`--temperature`, `--temperature-min`, `--temperature-max`).

Changer de modèle (cf. `ollama list` pour les modèles déjà présents) :

```bash
BERLUE_OLLAMA_MODEL=qwen2.5:0.5b make llm_generate
```

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
