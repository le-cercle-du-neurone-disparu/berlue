# Évaluation

Comment mesurer Berlue face à une baseline — méthodologie, où les résultats
sont stockés/calculés, et comment les consulter.

- [`modes.md`](modes.md) — les deux modes d'évaluation (dataset vs généré
  + juge), pourquoi les deux coexistent.
- [`storage.md`](storage.md) — où et comment les résultats sont stockés
  (concepts, implémentation locale SQLite, implémentation GCP
  Firestore/BigQuery, transfert local → GCP).
- [`run.md`](run.md) — où le calcul s'exécute (local, service Cloud Run).
- [`api.md`](api.md) — les routes de lecture des résultats déjà en cache
  (API produit, publique).
- [`eval-service-api.md`](eval-service-api.md) — l'endpoint qui déclenche
  le calcul (service Cloud Run d'éval, privé, piloté par `make`).
- [`baseline.md`](baseline.md) — entraîner/évaluer la baseline NLI en
  local.
- [`table-examples.md`](table-examples.md) — un exemple de ligne par
  table du cache local.
- [`execution-benchmark.md`](execution-benchmark.md) — temps et coût
  mesurés, local vs GCP.
- [`model-comparison-notes.md`](model-comparison-notes.md) — comparaison
  de modèles Ollama comme générateur et comme juge (mode généré).
