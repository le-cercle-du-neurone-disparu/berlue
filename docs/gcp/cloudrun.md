# Cloud Run

Trois usages distincts de Cloud Run dans le projet — un Job et deux
services, chacun avec son image, son coût et ses commandes. Compte de
service commun (`sa-berlue`) : [`composants.md`](composants.md#compte-de-service-cloud-run-sa-berlue).

## Job d'éval (`berlue-eval-mocked`)

```bash
make docker_build_eval docker_push_eval   # build + push l'image (Dockerfile.eval)
make cloudrun_eval_deploy                 # crée/met à jour le Job
make cloudrun_eval_run DATASET=halueval MODEL_ID=llama3.1:8b START=0 END=50
make cloudrun_eval_baseline DATASET=halueval RATIO=0.8              # baseline mode dataset
make cloudrun_eval_baseline_generated DATASET=halueval MODEL_ID=llama3.1:8b  # baseline mode généré
make cloudrun_eval_logs                   # logs des exécutions
```

`cloudrun_eval_run` accepte les mêmes variables que `evaluate_model`
(`DATASET`, `RATIO`, `MODEL_ID`, versions, `START`/`END`), plus
`MODE=dataset|generated` et `MATRIX=true|false`. Coût CPU seul, quasi
gratuit (~0,02-0,03 $ pour un run de plusieurs milliers de lignes,
détails dans
[`execution-benchmark.md`](../evaluation/execution-benchmark.md)).

## Service Ollama (`berlue-llm`)

Service séparé (pas bundlé dans l'image d'éval), GPU L4, appelé par le Job
d'éval en mode `generated` via jeton d'identité OIDC (`roles/run.invoker`
pour `sa-berlue`, accordé automatiquement au déploiement). **Coûte dès la
première requête** (~0,67 $/h GPU + CPU/mémoire du service) — jamais de
`min-instances` fixé sans décision explicite. Choix du type de GPU,
parallélisme (`OLLAMA_NUM_PARALLEL`/`--concurrency`) et pourquoi un seul
service partagé plutôt qu'un par rôle : [`infra-gpu.md`](infra-gpu.md).

Nécessite l'API Compute Engine, pas incluse dans `gcp_setup` (spécifique
au GPU, pas au reste de l'éval) :

```bash
make gcp_enable_compute
```

```bash
make docker_build_llm docker_push_llm     # build + push l'image (Dockerfile.llm)
make cloudrun_llm_deploy                  # crée/met à jour le service (+ IAM run.invoker)
make cloudrun_llm_url                     # récupère l'URL du service
make cloudrun_llm_logs
make cloudrun_llm_scale_to_zero           # sécurité budget, idempotent — à lancer après chaque session de test
make cloudrun_llm_delete                  # arrête définitivement toute facturation liée
```

Le modèle doit être tiré manuellement une fois le service déployé
(`POST /api/pull` avec un jeton d'identité — pas de cible `make` dédiée
pour l'instant) — **le modèle ne survit pas à un scale-to-zero** (disque
éphémère du conteneur, pas de volume persistant) : `model not found` à la
requête suivante, re-pull nécessaire (~100s, téléchargement réseau réel).
Pas de délai d'inactivité configurable côté Cloud Run avant le
scale-to-zero — seulement `min-instances` fixe (coûte en continu) ou
accepter le re-pull. Temps mesurés local vs GCP :
[`execution-benchmark.md`](../evaluation/execution-benchmark.md).

## Service API (`berlue-api-*`)

3 environnements, 3 services Cloud Run (`berlue-api-test`/`-staging`/
`-prod`), une seule image `:prod` construite et poussée une fois, puis
promue progressivement sur les 3 :

```bash
make docker_build_prod
make docker_push_prod
make cloudrun_deploy CLOUDRUN_ENV=test
make cloudrun_deploy CLOUDRUN_ENV=staging
make cloudrun_deploy CLOUDRUN_ENV=prod
```

```bash
make cloudrun_url CLOUDRUN_ENV=...        # récupère l'URL de l'environnement
```

Accès public par défaut, contrôlé par environnement dans
`make/config.mk` :

```makefile
CLOUDRUN_PUBLIC_test = true
CLOUDRUN_PUBLIC_staging = true
CLOUDRUN_PUBLIC_prod = true
```

Repasser un flag à `false` + relancer `cloudrun_deploy` pour cet
environnement verrouille l'accès derrière IAM
(`--no-allow-unauthenticated`).

```bash
make cloudrun_delete CLOUDRUN_ENV=test    # supprime un seul environnement
```
