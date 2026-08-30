# API d'évaluation

Six routes en lecture seule (`berlue/api/fast_eval.py`, montées sur
l'app dans `berlue/api/fast.py`) pour consulter les
résultats d'évaluation du pipeline Berlue déjà en cache (`berlue.evaluation.result_store`).
Aucune ne déclenche de calcul — remplir le cache se fait via `evaluate_model`/
`evaluate_model_generated` (cf. [`baseline.md`](baseline.md) pour le mécanisme
d'évaluation sous-jacent), pas par l'API.

Les paramètres `dataset`/`ratio`/`model_id`/`pipeline_version`/
`generation_version`/`eval_version` identifient un scope d'évaluation (un
seul dataset, ratio train/test, LLM évalué, trois versions) — voir
`berlue.evaluation.result_store.EvalScope` et
[`storage.md`](storage.md) pour quelle table dépend de quel axe
de version.

Deux modes d'évaluation, trois routes chacun (mêmes formes, préfixe/suffixe
`-generated` pour le second) :

- **mode dataset** : Berlue vérifie une réponse du dataset (`right_answer`/
  `hallucinated_answer`).
- **mode généré** : le LLM sous test génère sa propre réponse, jugée par un
  LLM-juge ancré sur les réponses de référence du dataset.

## Mode dataset

### `GET /evaluated-models`

Liste les scopes déjà entièrement évalués et stockés.

| Paramètre | Type | Requis | Description |
|---|---|---|---|
| `model_id` | string | non | Filtre sur un modèle précis |
| `ratio` | float | non | Filtre sur un ratio train/test précis |
| `pipeline_version` | string | non | Filtre sur une version du pipeline Berlue précise |
| `eval_version` | string | non | Filtre sur une version de méthodologie d'éval précise |

Sans filtre, retourne tous les scopes en cache. Réponse : `EvaluationListOutput`
— une liste d'objets `EvaluationResult` (`{dataset, ratio, model_id,
pipeline_version, eval_version, matrix, n_examples, dataset_test_size,
computed_at}`, `matrix` au format décrit en fin de page).

```bash
curl "http://localhost:8000/evaluated-models?model_id=llama3.1:8b"
```

```json
{
  "evaluations": [
    {
      "dataset": "halueval",
      "ratio": 0.8,
      "model_id": "llama3.1:8b",
      "pipeline_version": "v1",
      "generation_version": null,
      "eval_version": "v1",
      "matrix": {
        "ground_truth_true": {
          "predicted_true": 612,
          "predicted_undecided": 34,
          "predicted_false": 48
        },
        "ground_truth_false": {
          "predicted_true": 29,
          "predicted_undecided": 41,
          "predicted_false": 636
        }
      },
      "n_examples": 1400,
      "dataset_test_size": 1400,
      "computed_at": "2026-08-29T09:41:12.503921+00:00"
    }
  ]
}
```

### `GET /model-evaluation`

Résultat complet (`EvaluationResult`) d'un scope précis, identifié par ses
paramètres (obtenus via `/evaluated-models`) — tous requis.

| Paramètre | Type | Requis |
|---|---|---|
| `dataset` | string | oui |
| `ratio` | float | oui |
| `model_id` | string | oui |
| `pipeline_version` | string | oui |
| `eval_version` | string | oui |

Répond `404` si ce scope précis n'a pas encore de matrice stockée (aucun
calcul n'est déclenché en réponse à un manque). `n_examples`/
`dataset_test_size` dans la réponse permettent de savoir si ce résultat
couvre le split de test officiel complet ou un sous-ensemble partiel (cf.
[`storage.md`](storage.md#run-complet-ou-partiel--n_examples-vs-dataset_test_size)) —
comparer les deux plutôt que supposer `n_examples` toujours complet.

```bash
curl "http://localhost:8000/model-evaluation?dataset=halueval&ratio=0.8&model_id=llama3.1:8b&pipeline_version=v1&eval_version=v1"
```

```json
{
  "dataset": "halueval",
  "ratio": 0.8,
  "model_id": "llama3.1:8b",
  "pipeline_version": "v1",
  "generation_version": null,
  "eval_version": "v1",
  "matrix": {
    "ground_truth_true": {
      "predicted_true": 612,
      "predicted_undecided": 34,
      "predicted_false": 48
    },
    "ground_truth_false": {
      "predicted_true": 29,
      "predicted_undecided": 41,
      "predicted_false": 636
    }
  },
  "n_examples": 1400,
  "dataset_test_size": 1400,
  "computed_at": "2026-08-29T09:41:12.503921+00:00"
}
```

### `GET /baseline-evaluation`

Matrice de confusion de la baseline NLI, recalculée à la volée sur le jeu de
test correspondant à `(dataset, ratio)` — jamais stockée ni mise en cache.
Indépendante de `model_id`/`pipeline_version` (la baseline ne dépend pas du
pipeline Berlue en mode dataset) : un seul appel sert pour tous les scopes
qui partagent le même `(dataset, ratio)`.

| Paramètre | Type | Requis |
|---|---|---|
| `dataset` | string | oui |
| `ratio` | float | oui |

```bash
curl "http://localhost:8000/baseline-evaluation?dataset=halueval&ratio=0.8"
```

```json
{
  "ground_truth_true": {
    "predicted_true": 590,
    "predicted_undecided": 41,
    "predicted_false": 63
  },
  "ground_truth_false": {
    "predicted_true": 52,
    "predicted_undecided": 48,
    "predicted_false": 606
  }
}
```

## Mode généré

### `GET /evaluated-models-generated`

Liste les scopes déjà entièrement évalués (mode généré) — mêmes filtres que
`/evaluated-models`, plus `generation_version`.

| Paramètre | Type | Requis |
|---|---|---|
| `model_id` | string | non |
| `ratio` | float | non |
| `pipeline_version` | string | non |
| `generation_version` | string | non |
| `eval_version` | string | non |

```bash
curl "http://localhost:8000/evaluated-models-generated?model_id=llama3.1:8b"
```

```json
{
  "evaluations": [
    {
      "dataset": "halueval",
      "ratio": 0.8,
      "model_id": "llama3.1:8b",
      "pipeline_version": null,
      "generation_version": "v1",
      "eval_version": "v1",
      "matrix": {
        "ground_truth_true": {
          "predicted_true": 380,
          "predicted_undecided": 52,
          "predicted_false": 68
        },
        "ground_truth_false": {
          "predicted_true": 41,
          "predicted_undecided": 58,
          "predicted_false": 401
        }
      },
      "n_examples": 500,
      "dataset_test_size": 1400,
      "computed_at": "2026-08-29T10:37:04.118203+00:00"
    }
  ]
}
```

### `GET /model-evaluation-generated`

Résultat complet (`EvaluationResult`) Berlue-vs-juge d'un scope précis —
mêmes paramètres que `/model-evaluation`, plus `generation_version` (tous
requis), même comportement `404`.

```bash
curl "http://localhost:8000/model-evaluation-generated?dataset=halueval&ratio=0.8&model_id=llama3.1:8b&pipeline_version=v1&generation_version=v1&eval_version=v1"
```

```json
{
  "dataset": "halueval",
  "ratio": 0.8,
  "model_id": "llama3.1:8b",
  "pipeline_version": null,
  "generation_version": "v1",
  "eval_version": "v1",
  "matrix": {
    "ground_truth_true": {
      "predicted_true": 380,
      "predicted_undecided": 52,
      "predicted_false": 68
    },
    "ground_truth_false": {
      "predicted_true": 41,
      "predicted_undecided": 58,
      "predicted_false": 401
    }
  },
  "n_examples": 500,
  "dataset_test_size": 1400,
  "computed_at": "2026-08-29T10:37:04.118203+00:00"
}
```

### `GET /baseline-evaluation-generated`

Résultat complet (`EvaluationResult`) baseline-vs-juge pour un `(dataset,
ratio, model_id, generation_version, eval_version)` précis. Contrairement à
`/baseline-evaluation` (mode dataset), **pas de calcul à la volée** : en
mode généré, la baseline classifie la réponse générée par ce modèle précis,
donc son résultat est mis en cache comme le reste du mode — `404` si pas
encore stocké. Pas de `pipeline_version` (indépendante du pipeline Berlue) :
peuplé exclusivement par `evaluate_model_generated_baseline_matrix`
(`make evaluate_model_generated_baseline_matrix`) — jamais par
`evaluate_model_generated_matrix`, qui ne construit que la matrice Berlue
et ne touche jamais celle-ci (cf. [`modes.md`](modes.md)).

| Paramètre | Type | Requis |
|---|---|---|
| `dataset` | string | oui |
| `ratio` | float | oui |
| `model_id` | string | oui |
| `generation_version` | string | oui |
| `eval_version` | string | oui |

```bash
curl "http://localhost:8000/baseline-evaluation-generated?dataset=halueval&ratio=0.8&model_id=llama3.1:8b&generation_version=v1&eval_version=v1"
```

```json
{
  "dataset": "halueval",
  "ratio": 0.8,
  "model_id": "llama3.1:8b",
  "pipeline_version": null,
  "generation_version": "v1",
  "eval_version": "v1",
  "matrix": {
    "ground_truth_true": {
      "predicted_true": 349,
      "predicted_undecided": 61,
      "predicted_false": 90
    },
    "ground_truth_false": {
      "predicted_true": 77,
      "predicted_undecided": 64,
      "predicted_false": 359
    }
  },
  "n_examples": 500,
  "dataset_test_size": 1400,
  "computed_at": "2026-08-29T10:37:04.118203+00:00"
}
```

## Format d'une matrice de confusion

Cinq des six routes (toutes sauf `/baseline-evaluation`, qui renvoie la
matrice directement) l'imbriquent dans le champ `matrix` d'un
`EvaluationResult` — même format 2×3 (`berlue.api.schemas.ConfusionMatrix`)
dans tous les cas :

```json
{
  "ground_truth_true": {
    "predicted_true": 0,
    "predicted_undecided": 0,
    "predicted_false": 0
  },
  "ground_truth_false": {
    "predicted_true": 0,
    "predicted_undecided": 0,
    "predicted_false": 0
  }
}
```
