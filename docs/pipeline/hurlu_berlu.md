# Orchestrateur HurluBerlu

Chaîne les briques du pipeline pour une question donnée — voir
`berlue/pipeline/hurlu_berlu.py` (classe `HurluBerlu`).

```
generate_answer ─> extract_claims ─┬─> branche RAG ───────────────┐
                                   └─> branche SelfCheck ─────────┴─> fusion
```

Les deux branches de vérification tournent **en parallèle** : une fois les
affirmations extraites, elles ne partagent plus rien, chacune ne lisant que la
liste d'affirmations. Chacune répartit en outre ses propres appels sur un pool
de threads (cf. [parallélisme](#parallélisme)). Chaque étape a sa propre doc
pour le détail :

1. génération de la réponse — [`llm.md`](llm.md)
2. extraction des affirmations — [`extraction.md`](extraction.md)
3. branche SelfCheckGPT : échantillonnage + score — [`selfcheck.md`](selfcheck.md)
3'. branche RAG : un verdict par affirmation — [`rag.md`](rag.md)
4. fusion des deux verdicts — [`fusion.md`](fusion.md)

`HurluBerlu(llm_client=..., llm_extract=..., retriever=...)` accepte les
trois outils en injection (chacun a un défaut si omis, sauf `llm_client` —
voir [`llm.md`](llm.md)).

## Prérequis

Dépendances installées :

```bash
pip install -r requirements.txt -r requirements_dev.txt
```

- Ollama qui tourne en local avec un modèle disponible — [`ollama-setup.md`](../setup/ollama-setup.md).
- Index FAISS du RAG construit — [`rag.md`](rag.md).

## Lancer le pipeline, étape par étape

```bash
make pipeline_generate   # étape 1 seule : génère la réponse brute du LLM
make pipeline_extract    # étapes 1-2 : + extraction des affirmations
make pipeline_selfcheck  # branche SelfCheckGPT seule : échantillons + scores
make pipeline_rag        # branche RAG seule : un verdict par affirmation
make pipeline_fusion     # pipeline complet, les deux branches en parallèle
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

(`--until` accepte `generate`, `extract`, `selfcheck`, `rag`, `fusion` —
défaut `fusion`, le pipeline complet. `selfcheck` et `rag` exécutent chacun
UNE branche seule, pas les deux : ce sont deux chemins parallèles, pas deux
étapes successives.)

## Parallélisme

Trois plafonds indépendants, réglables par variable d'environnement
(`berlue/params.py`) — `1` rend l'étage strictement séquentiel, sans créer de
pool :

| Variable | Défaut | Ce qu'elle parallélise |
|---|---|---|
| `BERLUE_RAG_WORKERS` | 4 | les vérifications RAG, une par affirmation |
| `BERLUE_SELFCHECK_SAMPLE_WORKERS` | 4 | les K générations d'échantillons |
| `BERLUE_SELFCHECK_SCORE_WORKERS` | 2 | les passages NLI, un par affirmation |

Le gain est plafonné par le serveur Ollama : au-delà de son
`OLLAMA_NUM_PARALLEL`, les requêtes concurrentes font la queue côté serveur
sans rien apporter — cf. [`ollama-gpu-parallelism.md`](../gcp/ollama-gpu-parallelism.md).
Attention au facteur multiplicatif avec le `concurrency` de
`evaluation/run_eval.py` (parallélisme par question) : le pic de requêtes
simultanées vaut `concurrency × (K + RAG_WORKERS)`.

Modèles Ollama déjà présents :

```bash
ollama list
```

Changer de modèle pour toute la chaîne :

```bash
BERLUE_OLLAMA_MODEL=qwen2.5:0.5b make pipeline_extract
```

## Lancer les tests liés

```bash
pytest tests/test_pipeline.py -v
```

Tests unitaires purs — un `OllamaClient` stubé remplace le vrai client,
aucun serveur Ollama ni modèle SelfCheckGPT requis.
