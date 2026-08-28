# Orchestrateur HurluBerlu

Chaîne les briques du pipeline pour une question donnée — voir
`berlue/pipeline/hurlu_berlu.py` (classe `HurluBerlu`). Chaque étape a sa
propre doc pour le détail :

1. génération de la réponse — `docs/pipeline/llm.md`
2. extraction des affirmations — `docs/pipeline/extraction.md`
3. échantillonnage + score SelfCheckGPT — `docs/pipeline/selfcheck.md`
4. vérification RAG — `docs/pipeline/rag.md`
5. fusion des deux verdicts — `docs/pipeline/fusion.md`

`HurluBerlu(llm_client=..., llm_extract=..., retriever=...)` accepte les
trois outils en injection (chacun a un défaut si omis, sauf `llm_client` —
voir `docs/pipeline/llm.md`).

## Prérequis

- Dépendances installées : `pip install -r requirements.txt -r requirements_dev.txt`
- Ollama qui tourne en local avec un modèle disponible — `docs/setup/ollama-setup.md`.
- Index FAISS du RAG construit — `docs/pipeline/rag.md`.

## Lancer le pipeline, étape par étape

```bash
make pipeline_generate   # étape 1 seule : génère la réponse brute du LLM
make pipeline_extract    # étapes 1-2 : + extraction des affirmations
make pipeline_samples    # étapes 1-3 : + échantillonnage SelfCheckGPT
make pipeline_selfcheck  # étapes 1-4 : + score de divergence SelfCheckGPT
```

Chaque cible affiche uniquement le résultat de l'étape où elle s'arrête —
pratique pour vérifier un maillon sans attendre les suivants (SelfCheck en
particulier, qui refait K appels au LLM).

Question surchargeable :

```bash
make pipeline_extract QUESTION="Pourquoi la mer est salée ?"
```

Les étapes RAG et fusion s'utilisent directement via `--until`, sans cible
`make` dédiée :

```bash
python -m berlue.pipeline.hurlu_berlu --until rag --question "Pourquoi la mer est salée ?"
python -m berlue.pipeline.hurlu_berlu --until fusion --question "Pourquoi la mer est salée ?"
```

(`--until` accepte `generate`, `extract`, `samples`, `selfcheck`, `rag`,
`fusion` — défaut `fusion`, le pipeline complet.)

Changer de modèle Ollama pour toute la chaîne (cf. `ollama list` pour les
modèles déjà présents) :

```bash
BERLUE_OLLAMA_MODEL=qwen2.5:0.5b make pipeline_extract
```

## Lancer les tests liés

```bash
pytest tests/test_pipeline.py -v
```

Tests unitaires purs — un `OllamaClient` stubé remplace le vrai client,
aucun serveur Ollama ni modèle SelfCheckGPT requis.
