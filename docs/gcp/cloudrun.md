# Cloud Run

Trois usages distincts de Cloud Run dans le projet, chacun avec son image,
son coût et ses commandes. Compte de service commun (`sa-berlue`) :
[`composants.md`](composants.md#compte-de-service-cloud-run-sa-berlue).

## Allumer : deux chemins, un extincteur

| Commande | Monte à `min-instances=1` | Pour |
|---|---|---|
| `make gcp_up` | `berlue-api-<env>` + `berlue-llm` | le produit : Aletheia → API → LLM |
| `make gcp_eval_up` | `berlue-eval-mocked-service` + `berlue-llm` | l'évaluation : `/invoke` → LLM |
| `make gcp_down` | *(les 3 à 0)* | fin de session, toujours |

`berlue-llm` est commun aux deux — les deux chemins appellent le LLM — et il
est monté dans les deux cas : **c'est le GPU L4, ~0,67 $/h dès la première
seconde**. `WARM_MODELS="llama3.1:8b"` ne décide donc pas si le GPU s'allume,
seulement quels modèles y sont tirés et chargés en VRAM d'avance.

La brique commune est aussi utilisable seule : `make cloudrun_llm_up`.

## Tout déployer d'un coup

```bash
make gcp_deploy                    # CLOUDRUN_ENV=test par défaut
```

Build + push les 3 images (`docker_build_push_all`) puis déploie les 3
services (`cloudrun_deploy_all`). **L'ordre n'est pas cosmétique** :
`cloudrun_deploy` lit l'URL de `berlue-llm` pour câbler `BERLUE_OLLAMA_HOST`
sur l'API, donc `berlue-llm` est déployé en premier. Déployer l'API sans
lui échoue désormais explicitement, au lieu de partir avec un
`BERLUE_OLLAMA_HOST` vide.

Ce que ça ne fait pas : allumer quoi que ce soit. Les services sortent de
là à `min-instances=0` — c'est `gcp_up`/`gcp_eval_up` qui forcent une instance chaude, et
c'est lui qui coûte.

Seule l'API est déclinée par environnement. Le service d'éval et le service
Ollama sont uniques pour le projet, partagés par les trois environnements :
`make gcp_deploy CLOUDRUN_ENV=staging` ne crée pas un second `berlue-llm`,
il redéploie l'API dans staging. Pour une simple promotion (même image,
autre environnement), inutile de rebuilder :

```bash
make cloudrun_deploy CLOUDRUN_ENV=staging
```

## Service d'éval (`berlue-eval-mocked-service`)

`berlue.evaluation.run_eval`, servi par `berlue.api.eval_service`
(`uvicorn`, `Dockerfile.eval-service`) — un seul endpoint `POST /invoke`
qui reçoit les mêmes flags que la CLI en JSON. Tourne en continu
(`min-instances=1`, monté/éteint via `gcp_eval_up`/`gcp_down`) plutôt qu'un
conteneur neuf par exécution — temps mesurés :
[`execution-benchmark.md`](../evaluation/execution-benchmark.md).

```bash
make docker_build_eval_service docker_push_eval_service   # build + push (Dockerfile.eval-service)
make cloudrun_eval_service_deploy                         # crée/met à jour le service
make gcp_eval_up                                           # min-instances=1 (éval + LLM) + préchauffe, avant une série de runs
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

**`gcp_eval_up` préchauffe trois choses**, pas seulement "le process est démarré" :
1. Le process lui-même (imports Python, store GCP) — absorbé avant que
   Cloud Run ne marque l'instance "ready" (cf. `berlue.api.eval_service`,
   section suivante).
2. **Le split de test** `DATASET`/`RATIO` (`DATASET ?= halueval`,
   `RATIO ?= 0.8`, mêmes défauts que `evaluate_model`) — chargement +
   split mis en cache **par process** (`run_eval._cached_split`, `lru_cache`
   par `(dataset, ratio)`), donc à indiquer explicitement si le run visé
   n'utilise pas le ratio par défaut, sinon le premier vrai appel repaie ce
   calcul (rapide, mais pas gratuit sur un run répété).
3. **`berlue-llm`**, monté à `min-instances=1` dans tous les cas (l'éval
   comme l'API l'appellent) — c'est le GPU, il coûte dès cet instant. Si
   `WARM_MODELS="modele1 modele2 ..."` est fourni, chaque modèle est en plus
   tiré (`/api/pull`) et chargé en VRAM (un appel de génération jetable) :
   `WARM_MODELS` ne décide pas **si** le GPU s'allume, seulement ce qui y
   est préchargé.

`gcp_down` redescend toujours `berlue-eval-mocked-service`, `berlue-llm` et
`berlue-api-<env>` (`CLOUDRUN_ENV`, défaut `test`) à `min-instances=0`,
inconditionnellement (idempotent, pas d'état à suivre entre les deux
commandes). Un service pas encore déployé est ignoré avec un avertissement
et n'interrompt plus la série — auparavant le premier service absent
laissait les suivants allumés, donc facturés. Cf.
[`aletheia-local.md`](aletheia-local.md) pour le workflow complet avec
Aletheia en local.

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

⚠️ **Prérequis manuel, à demander tôt** : un projet neuf a **0** en « Total
Nvidia L4 GPU allocation, per project per region » (europe-west1).
`cloudrun_llm_deploy` échoue tant que la demande d'augmentation n'est pas
accordée (console GCP → IAM & Admin → Quotas), avec un délai qui peut
atteindre plusieurs heures. L'API Compute Engine, elle, est déjà activée
par `make gcp_setup`.

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
relancer `gcp_up`/`gcp_eval_up` avec `WARM_MODELS="..."` après. Toujours redéployer sans
surcharge ensuite pour revenir à la config de prod.

`make ollama_load_test_gcp` (cf. `scripts/ollama_load_test.py`) envoie une
charge directement à `berlue-llm` (auth OIDC automatique), sans passer par
le service d'éval — utile pour balayer beaucoup de paliers de concurrence
rapidement (nécessite `gcp_eval_up WARM_MODELS="..."` au préalable) :

```bash
MODEL=llama3.1:8b START_THREADS=32 MAX_THREADS=32 RAMP_INTERVAL_S=5 HOLD_AT_MAX_S=30 \
  make ollama_load_test_gcp
```

Le modèle doit être tiré une fois le service déployé (`POST /api/pull` avec
un jeton d'identité) — automatisé par `make cloudrun_llm_up WARM_MODELS="..."` (cf.
section précédente) plutôt qu'à la main. **Le modèle ne survit pas à un
scale-to-zero** (disque éphémère du conteneur, pas de volume persistant) :
`model not found` à la requête suivante, re-pull nécessaire (~100s,
téléchargement réseau réel) — d'où `gcp_up`/`gcp_eval_up`/`gcp_down` plutôt qu'un
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
