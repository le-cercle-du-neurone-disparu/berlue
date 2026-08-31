# Cloud Run

Trois usages distincts de Cloud Run dans le projet, chacun avec son image,
son coût et ses commandes. Compte de service commun (`sa-berlue`) :
[`composants.md`](composants.md#compte-de-service-cloud-run-sa-berlue).

## Service d'éval (`berlue-eval-mocked-service`)

`berlue.evaluation.run_eval`, servi par `berlue.api.eval_service`
(`uvicorn`, `Dockerfile.eval-service`) — un seul endpoint `POST /invoke`
qui reçoit les mêmes flags que la CLI en JSON. Tourne en continu
(`min-instances=1`, monté/éteint via `gcp_up`/`gcp_down`) plutôt qu'un
conteneur neuf par exécution — temps mesurés :
[`execution-benchmark.md`](../evaluation/execution-benchmark.md).

```bash
make docker_build_eval_service docker_push_eval_service   # build + push (Dockerfile.eval-service)
make cloudrun_eval_service_deploy                         # crée/met à jour le service
make gcp_up                                                # min-instances=1 + préchauffe, avant une série de runs
make cloudrun_eval_service_invoke DATASET=halueval MODEL_ID=llama3.1:8b   # START/END facultatifs — omis, tout le scope
make cloudrun_eval_service_invoke DATASET=halueval MODEL_ID=llama3.1:8b MATRIX=true
make gcp_down                                              # min-instances=0, en fin de session
```

`cloudrun_eval_service_invoke` accepte les mêmes variables que
`evaluate_model`/`evaluate_model_generated` (`DATASET`, `RATIO`,
`MODEL_ID`, versions, `MODE`, `MATRIX`, `START`/`END`, `JUDGE_MODEL`,
`WARMUP`, `BASELINE`, `COVERAGE`, `CONCURRENCY`). `START`/`END` sont facultatifs — omis, un appel traite tout le
scope (cf. [`run.md`](../evaluation/run.md) pour combien d'éléments compte
un scope avant de découper, via `evaluate_model_coverage` en local contre
le store GCP — pas besoin du service pour ça).

**`gcp_up` préchauffe trois choses**, pas seulement "le process est démarré" :
1. Le process lui-même (imports Python, store GCP) — absorbé avant que
   Cloud Run ne marque l'instance "ready" (cf. `berlue.api.eval_service`,
   section suivante).
2. **Le split de test** `DATASET`/`RATIO` (`DATASET ?= halueval`,
   `RATIO ?= 0.8`, mêmes défauts que `evaluate_model`) — chargement +
   split mis en cache **par process** (`run_eval._cached_split`, `lru_cache`
   par `(dataset, ratio)`), donc à indiquer explicitement si le run visé
   n'utilise pas le ratio par défaut, sinon le premier vrai appel repaie ce
   calcul (rapide, mais pas gratuit sur un run répété).
3. **`berlue-llm`**, si `WARM_MODELS="modele1 modele2 ..."` est fourni :
   monté à `min-instances=1`, chaque modèle tiré (`/api/pull`) et chargé en
   VRAM (un appel de génération jetable) — nécessaire avant tout
   `MODE=generated`, sans effet sinon.

`gcp_down` redescend toujours `berlue-eval-mocked-service`, `berlue-llm` et
`berlue-api-<env>` (`CLOUDRUN_ENV`, défaut `test`) à `min-instances=0`,
inconditionnellement (idempotent, pas d'état à suivre entre les deux
commandes) — cf. [`aletheia-local.md`](aletheia-local.md) pour le workflow
complet avec Aletheia en local.

⚠️ Coûte tant que c'est monté (GPU L4 si `WARM_MODELS` non vide, cf.
section suivante) — `gcp_down` en fin de session, mais **ne garantit pas
l'arrêt immédiat d'une instance `berlue-llm` déjà active** (cf. section
suivante) : `cloudrun_llm_delete` reste le seul levier garanti pour
vraiment couper la facturation GPU.

**Vérifier qu'un modèle tourne vraiment** (pas juste servi depuis un cache
Firestore déjà rempli par une session précédente) :

```bash
make gcp_verify_warm MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b
```

Purge d'abord un tag réservé (`eval_version=warmup-check`, jamais utilisé
pour un vrai run — le seul des 3 axes de version qui filtre toutes les
tables, cf. [`storage.md`](../evaluation/storage.md), donc le seul sur
lequel une purge est sûre même sans préciser les autres filtres), puis
force 1 appel généré+jugé sur une seule question : garanti cache-miss.

## Service Ollama (`berlue-llm`)

Service séparé (pas bundlé dans l'image d'éval), GPU L4, appelé par le
service d'éval en mode `generated` via jeton d'identité OIDC
(`roles/run.invoker` pour `sa-berlue`, accordé automatiquement au
déploiement). **Coûte dès la
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
make cloudrun_llm_scale_to_zero           # retire la garantie de capacité chaude, idempotent
make cloudrun_llm_delete                  # seul levier garanti pour arrêter la facturation liée
```

`cloudrun_llm_scale_to_zero`/`min-instances=0` **ne garantit pas l'arrêt
immédiat d'une instance déjà active** — Cloud Run peut la garder tant qu'il
la classe *active* plutôt qu'*idle*, indépendamment de `min-instances` (cas
réel et détail du diagnostic : [`aletheia-local.md`](aletheia-local.md#terminer-une-session--toujours-forcer-larrêt-réel)).
`cloudrun_llm_delete` reste le seul levier garanti après une session — à
utiliser systématiquement, pas seulement en dernier recours.

`cloudrun_llm_deploy` accepte `LLM_NUM_PARALLEL`/`LLM_CONCURRENCY`/
`LLM_CONTEXT_LENGTH`/`LLM_CPU`/`LLM_MEMORY` (défauts = config de prod
ci-dessus) pour caler le service sur un run précis — `LLM_NUM_PARALLEL`
doit égaler le `CONCURRENCY` prévu côté éval (jamais un maximum "au cas
où", ça coûte du débit réel, cf.
[`ollama-gpu-parallelism.md`](ollama-gpu-parallelism.md)), `LLM_CPU=8
LLM_MEMORY=32Gi` recommandé dès qu'on vise une vraie concurrence (cf.
[`infra-gpu.md`](infra-gpu.md)) :

```bash
make cloudrun_llm_deploy LLM_NUM_PARALLEL=32 LLM_CONCURRENCY=42 LLM_CPU=8 LLM_MEMORY=32Gi
```

Une nouvelle révision perd le modèle tiré (disque éphémère, cf. plus bas) :
relancer `gcp_up WARM_MODELS="..."` après. Toujours redéployer sans
surcharge ensuite pour revenir à la config de prod.

`make ollama_load_test_gcp` (cf. `scripts/ollama_load_test.py`) envoie une
charge directement à `berlue-llm` (auth OIDC automatique), sans passer par
le service d'éval — utile pour balayer beaucoup de paliers de concurrence
rapidement (nécessite `gcp_up WARM_MODELS="..."` au préalable) :

```bash
MODEL=llama3.1:8b START_THREADS=32 MAX_THREADS=32 RAMP_INTERVAL_S=5 HOLD_AT_MAX_S=30 \
  make ollama_load_test_gcp
```

Le modèle doit être tiré une fois le service déployé (`POST /api/pull` avec
un jeton d'identité) — automatisé par `make gcp_up WARM_MODELS="..."` (cf.
section précédente) plutôt qu'à la main. **Le modèle ne survit pas à un
scale-to-zero** (disque éphémère du conteneur, pas de volume persistant) :
`model not found` à la requête suivante, re-pull nécessaire (~100s,
téléchargement réseau réel) — d'où `gcp_up`/`gcp_down` plutôt qu'un
`min-instances` laissé actif entre deux sessions.
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
