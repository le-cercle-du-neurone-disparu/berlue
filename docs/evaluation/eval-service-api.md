# API d'évaluation — calcul

Deux endpoints (`berlue/api/eval_service.py`, servis par le service Cloud
Run `berlue-eval`) qui **déclenchent du calcul** — remplir
le cache, construire une matrice, lire une couverture, ou purger — plutôt
que de consulter des résultats déjà en cache (ça, c'est [`api.md`](api.md),
routes publiques séparées, montées sur l'API produit).

Privé (`--no-allow-unauthenticated`, IAM `roles/run.invoker` réservé à
`sa-berlue`) — pas destiné à être appelé par un site ; piloté uniquement
via `make` (`cloudrun_eval_service_invoke`, `gcp_eval_up`, `gcp_verify_warm`,
cf. [`cloudrun.md`](../gcp/cloudrun.md) pour le déploiement, le cycle de
vie `gcp_eval_up`/`gcp_down`, et les exemples `make`). Cette page documente le
contrat HTTP lui-même — utile pour écrire un nouvel outil contre le
service, pas pour l'usage courant.

`POST /purge` est délibérément un endpoint **séparé** de `POST /invoke`,
pas un simple flag dans son body — une purge est destructive, jamais
question qu'un body `/invoke` mal formé (ou un copier-coller d'une requête
précédente) la déclenche par accident.

## `GET /health`

Liveness/readiness — `{"status": "ok"}`, sans authentification particulière
au-delà de l'accès au service. Répond seulement une fois `lifespan` terminé
(store + parser construits), donc sert aussi de signal "l'instance est
vraiment chaude", pas juste "le conteneur a démarré" — cf.
[`cloudrun.md`](../gcp/cloudrun.md) pour comment `gcp_eval_up` s'en sert.

## `POST /invoke`

Reçoit en JSON exactement les mêmes flags que la CLI locale
(`python -m berlue.evaluation.run_eval`, cf. [`run.md`](run.md)) — mêmes
noms sans le `--`, underscores au lieu de tirets, mêmes défauts. Tout champ
omis garde le défaut CLI. Ne fait jamais de purge (cf. `POST /purge`
ci-dessous).

| Champ JSON | Type | Défaut | Description |
|---|---|---|---|
| `dataset` | string | `"halueval"` | Un seul dataset (jamais mélangé) |
| `ratio` | float | `0.8` (`params.TRAIN_RATIO`) | Ratio train/test |
| `model_id` | string | `"random-mock"` | Identité du modèle évalué |
| `pipeline_version` | string | `"v1"` (`params.PIPELINE_VERSION`) | Version du pipeline Berlue |
| `generation_version` | string | `"v1"` (`params.GENERATION_VERSION`) | Version de la génération LLM |
| `eval_version` | string | `"v1"` (`params.EVAL_VERSION`) | Version de la méthodologie d'éval |
| `start` | int | `0` | Index de départ dans le jeu de test |
| `end` | int | `null` (jusqu'au bout) | Index de fin (exclu) |
| `mode` | `"dataset"` \| `"generated"` | `"dataset"` | Berlue vérifie la réponse du dataset, ou le LLM génère sa réponse jugée par un LLM-juge |
| `judge_model` | string | `"llama3.1:8b"` (`params.JUDGE_MODEL`) | Modèle du LLM-juge (`mode="generated"` uniquement) |
| `warmup` | bool | `false` | `mode="generated"` uniquement : précharge generator/judge en VRAM sur `berlue-llm` avant de démarrer le chrono de la boucle — cf. note ci-dessous |
| `matrix` | bool | `false` | Construit/stocke la matrice finale au lieu de remplir le cache (échoue si le scope est incomplet) |
| `coverage` | bool | `false` | N'évalue rien — retourne le total d'éléments du scope + index déjà en cache/manquants |
| `baseline` | bool | `false` | Évalue la baseline NLI seule au lieu de Berlue, jamais les deux — respecte `mode` : `dataset`, recalculée à la volée, ignore les autres champs ; `generated`, classifie les réponses déjà générées pour ce scope, sans regénérer ni rejuger |

**`warmup` ne couvre que le LLM** — le préchauffage "process" (imports
Python, store GCP, split dataset), lui, n'est **jamais** un champ de
requête : il est automatique, géré par le cycle de vie de l'instance et
`gcp_eval_up`, pour les deux modes indifféremment (mode 1 en profite tout
autant que mode 2, même s'il n'y a pas de LLM à charger) — cf.
[`cloudrun.md`](../gcp/cloudrun.md) pour le détail des 3 paliers que
`gcp_eval_up` préchauffe.

Réponse : `{"result": ...}` — `result` varie selon la requête, comme le
retour de la fonction Python équivalente (`run_from_args`, cf.
[`run.md`](run.md)) :
- `null` pour un simple remplissage de cache (`evaluate_model`/
  `evaluate_model_generated`/`evaluate_model_generated_baseline` sans
  `matrix`).
- Une matrice de confusion (même format que [`api.md`](api.md#format-dune-matrice-de-confusion))
  avec `matrix: true`.
- Un rapport de couverture (`{"total", "done_indices", "missing_indices",
  "skipped_indices"}`) avec `coverage: true`.

Erreurs : `400` avec un message explicite si les flags sont invalides
(argparse) ou si une opération métier échoue (ex. `--matrix` sur un cache
incomplet — même message que la CLI). Jamais un `500` nu pour ces cas.

```bash
# rempli tout le scope, mode dataset (défaut) — mêmes noms de champs que les flags CLI
curl -sf -X POST "$URL/invoke" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"dataset":"halueval","ratio":0.8,"model_id":"llama3.1:8b"}'

# construit/stocke la matrice Berlue-vs-juge (mode généré), depuis le cache déjà rempli
curl -sf -X POST "$URL/invoke" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"dataset":"halueval","ratio":0.8,"model_id":"llama3.1:8b","judge_model":"llama3.1:8b","mode":"generated","matrix":true}'
```

```json
{"result": null}
```

```json
{
  "result": {
    "ground_truth_true": {"predicted_true": 1, "predicted_undecided": 2, "predicted_false": 3},
    "ground_truth_false": {"predicted_true": 1, "predicted_undecided": 0, "predicted_false": 3}
  }
}
```

## `POST /purge`

Supprime des résultats en cache correspondant aux filtres fournis — chaque
filtre omis est un joker. Mêmes noms que les flags CLI `--purge-*`, sans le
préfixe `purge_` (implicite : cet endpoint ne fait que ça).

| Champ JSON | Type | Défaut | Description |
|---|---|---|---|
| `scope` | `"all"` \| `"results"` \| `"matrices"` | `"all"` | Limite la purge aux résultats individuels, aux matrices, ou aux deux |
| `dataset` | string | `null` (joker) | Filtre : dataset |
| `ratio` | float | `null` (joker) | Filtre : ratio train/test |
| `model_id` | string | `null` (joker) | Filtre : modèle |
| `pipeline_version` | string | `null` (joker) | Filtre : version du pipeline Berlue |
| `generation_version` | string | `null` (joker) | Filtre : version de génération |
| `eval_version` | string | `null` (joker) | Filtre : version de la méthodologie d'éval |
| `judge_model` | string | `null` (joker) | Filtre : modèle du LLM-juge (mode généré) |

⚠️ Tout filtre omis est un joker sur **toutes** les tables où il
s'applique — `eval_version` est le seul des 3 axes de version qui filtre
systématiquement toutes les tables (cf. [`storage.md`](storage.md)), donc
le seul sur lequel une purge reste sûre même sans préciser les autres
filtres. Une purge avec `pipeline_version`/`eval_version` en joker peut
déborder sur des scopes qu'on ne voulait pas toucher si `model_id` est
partagé par ailleurs.

Réponse : `{"result": {"predictions_deleted", "llm_answers_deleted",
"judge_verdicts_deleted", "berlue_generated_deleted",
"baseline_generated_deleted", "matrices_deleted",
"matrices_generated_berlue_deleted", "matrices_generated_baseline_deleted"}}`
— compte de lignes supprimées par table.

```bash
curl -sf -X POST "$URL/purge" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"dataset":"halueval","ratio":0.999,"model_id":"scope-a-purger"}'
```

```json
{
  "result": {
    "predictions_deleted": 20,
    "llm_answers_deleted": 0,
    "judge_verdicts_deleted": 0,
    "berlue_generated_deleted": 0,
    "baseline_generated_deleted": 0,
    "matrices_deleted": 1,
    "matrices_generated_berlue_deleted": 0,
    "matrices_generated_baseline_deleted": 0
  }
}
```

## Auth

`$URL`/`$TOKEN` : URL du service (`gcloud run services describe ... --format="value(status.url)"`)
et jeton d'identité OIDC (`gcloud auth print-identity-token --impersonate-service-account=sa-berlue@... --audiences=$URL`)
— `make cloudrun_eval_service_invoke`/`gcp_verify_warm` s'en chargent déjà,
cf. [`cloudrun.md`](../gcp/cloudrun.md).
