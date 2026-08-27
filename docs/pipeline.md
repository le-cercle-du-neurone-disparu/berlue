# Pipeline HurluBerlu en local

Orchestrateur du pipeline Berlue — voir `berlue/pipeline/hurlu_berlu.py`.
Enchaîne aujourd'hui 4 étapes : génération de la réponse (Ollama), extraction
des affirmations, échantillonnage et score de divergence SelfCheckGPT. Le RAG
inversé (`rag/`) et la fusion des scores (`fusion.py`) sont encore des TODO,
pas branchés dans l'orchestrateur.

## Prérequis

- Dépendances installées : `pip install -r requirements.txt -r requirements_dev.txt`
- Ollama qui tourne en local avec un modèle disponible — cf. `docs/ollama-setup.md`
  (`make ollama_setup` puis `make ollama_check`).
- Le score de divergence (étape SelfCheck) charge le modèle `selfcheckgpt`
  (NLI) au premier appel — téléchargement HuggingFace la première fois,
  potentiellement plusieurs centaines de Mo.

## Lancer une étape à la fois

```bash
make pipeline_generate   # étape 1 seule : génère la réponse brute du LLM
make pipeline_extract    # étapes 1-2 : + extraction des affirmations
make pipeline_samples    # étapes 1-3 : + échantillonnage SelfCheckGPT (K appels LLM)
make pipeline_selfcheck  # pipeline complet aujourd'hui disponible (RAG et fusion pas encore implémentés)
```

Chaque cible affiche uniquement le résultat de l'étape où elle s'arrête —
pratique pour vérifier un maillon sans attendre les suivants (SelfCheck en
particulier, qui refait K appels au LLM).

Question surchargeable :

```bash
make pipeline_extract QUESTION="Pourquoi la mer est salée ?"
```

Équivalent direct sans `make` :

```bash
python -m berlue.pipeline.hurlu_berlu --until extract --question "Pourquoi la mer est salée ?"
```

(`--until` accepte `generate`, `extract`, `samples`, `selfcheck` — défaut
`selfcheck`, le pipeline complet disponible aujourd'hui.)

## Aller plus vite pendant le développement

`SELFCHECK_K` (nombre d'échantillons) vaut 5 par défaut — le réduire accélère
nettement les étapes `samples`/`selfcheck` en dev :

```bash
BERLUE_SELFCHECK_K=2 make pipeline_selfcheck
```

Changer de modèle Ollama (utile pour un modèle plus rapide/plus petit en
itération, cf. `ollama list` pour les modèles déjà présents) :

```bash
BERLUE_OLLAMA_MODEL=qwen2.5:0.5b make pipeline_extract
```

## Lancer les tests liés

```bash
pytest tests/test_pipeline.py -v
```

Tests unitaires purs — un `OllamaClient` stubé remplace le vrai client dans
`tests/test_pipeline.py`, aucun serveur Ollama ni modèle SelfCheckGPT requis.
