# SelfCheckGPT

Détecte l'incohérence du LLM avec lui-même — zero-resource, ne vérifie rien
contre une source externe (contrairement au RAG inversé,
`docs/pipeline/rag.md`) : un LLM qui hallucine tend à varier davantage d'un
tirage à l'autre sur les détails inventés qu'un LLM qui rapporte un fait
qu'il connaît. Deux étapes, `berlue/selfcheck/` :

- **`sampler.py::sample_responses`** — regénère la question K fois
  (`SELFCHECK_K`, défaut 5), à des températures espacées entre
  `SELFCHECK_TEMPERATURE_MIN` et `SELFCHECK_TEMPERATURE_MAX` (défaut
  0.7–1.3), via le même `OllamaClient` que `docs/pipeline/llm.md`.
- **`scorer.py::compute_divergence`** — pour chaque affirmation, mesure sa
  divergence par rapport aux K échantillons avec le modèle NLI du package
  `selfcheckgpt` (chargé une fois, gardé en mémoire pour les appels
  suivants). Renvoie un `SelfCheckScore` (`divergence_score` 0.0 = cohérent
  → 1.0 = très divergent, `confidence` son complément).

## Lancer ces étapes

```bash
make pipeline_samples    # échantillonnage seul (K appels LLM)
make pipeline_selfcheck  # + score de divergence par affirmation
```

Équivalent direct : `python -m berlue.pipeline.hurlu_berlu --until samples`
ou `--until selfcheck` — voir `docs/pipeline/hurlu_berlu.md` pour les autres
étapes.

Réduire `SELFCHECK_K` accélère nettement l'itération en dev :

```bash
BERLUE_SELFCHECK_K=2 make pipeline_selfcheck
```

## Lancer les tests liés

```bash
pytest tests/test_pipeline.py -v -k "samples or selfcheck"
```

Tests unitaires purs — `OllamaClient` stubé pour l'échantillonnage,
`compute_divergence` monkeypatché pour le score (pas de modèle NLI chargé),
cf. `tests/test_pipeline.py`.
