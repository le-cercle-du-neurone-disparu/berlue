# SelfCheckGPT

Détecte l'incohérence du LLM avec lui-même — zero-resource, ne vérifie rien
contre une source externe (contrairement au RAG inversé,
[`rag.md`](rag.md)) : un LLM qui hallucine tend à varier davantage d'un
tirage à l'autre sur les détails inventés qu'un LLM qui rapporte un fait
qu'il connaît. Deux étages, `berlue/selfcheck/`, enchaînés par
**`branch.py::run_selfcheck`** — le second a besoin de TOUS les échantillons
pour scorer la première affirmation, mais chacun répartit ses propres appels
sur son pool de threads :

- **`sampler.py::sample_responses`** — regénère la question K fois
  (`SELFCHECK_K`, défaut 5), à des températures espacées entre
  `SELFCHECK_TEMPERATURE_MIN` et `SELFCHECK_TEMPERATURE_MAX` (défaut
  0.7–1.3), via le même `OllamaClient` que [`llm.md`](llm.md). Les K appels
  partent en parallèle (`BERLUE_SELFCHECK_SAMPLE_WORKERS`, défaut 4) ; la
  liste rendue reste ordonnée par température croissante, quel que soit
  l'ordre d'achèvement.
- **`scorer.py::compute_divergence`** — pour chaque affirmation, mesure sa
  divergence par rapport aux K échantillons avec le modèle NLI du package
  `selfcheckgpt` (chargé une fois, gardé en mémoire pour les appels
  suivants). Renvoie un `SelfCheckScore` (`divergence_score` 0.0 = cohérent
  → 1.0 = très divergent, `confidence` son complément). Une affirmation par
  thread (`BERLUE_SELFCHECK_SCORE_WORKERS`, défaut 2 — ces passages tiennent
  une place mémoire sur l'appareil de torch, GPU compris).

## Lancer cette branche

```bash
make pipeline_selfcheck  # échantillons + score de divergence par affirmation
```

Équivalent direct (voir [`hurlu_berlu.md`](hurlu_berlu.md) pour les autres
étapes) :

```bash
python -m berlue.pipeline.hurlu_berlu --until selfcheck
```

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
