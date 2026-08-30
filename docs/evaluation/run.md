# Exécution de l'évaluation

Où le service d'évaluation s'exécute — piloté par `EVAL_RUN_TARGET`
(`local` ou `gcp`), indépendant d'où les résultats sont stockés (cf.
[`storage.md`](storage.md)).

Indépendants l'un de l'autre, sauf une contrainte dans un seul sens :
exécution locale → stockage local ou GCP au choix ; exécution GCP → stockage
GCP obligatoire (pas de stockage local persistant/partagé dans un container
Cloud Run).

```bash
# fixe explicitement les deux axes (défauts déjà "local"/"local")
BERLUE_EVAL_RUN_TARGET=local BERLUE_EVAL_STORE_TARGET=local make evaluate_model
```

## Local

Process Python natif — `berlue.evaluation.run_eval` tourne directement sur
la machine qui lance `make`, pas de conteneur.

### Mode dataset

```bash
# remplit le cache sur [START:END]
make evaluate_model DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b START=0 END=10

# construit/stocke la matrice depuis le cache déjà rempli
make evaluate_model_matrix DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b

# baseline seule, recalculée à la volée (jamais stockée)
make evaluate_baseline DATASET=halueval RATIO=0.8

# remplit tout le cache d'un scope puis construit sa matrice, en un seul
# appel — pratique en dev, ne reflète pas le découpage en tranches d'un run
# réel (cf. séquence testée plus bas)
make evaluate_model_all DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b
```

### Mode généré

Berlue et la baseline sont deux chemins totalement séparés (cf.
[`modes.md`](modes.md)) — chacun son remplissage de cache, chacun sa
matrice, jamais mélangés :

```bash
# Berlue : génération + fact-check Berlue + juge sur [START:END] (jamais la baseline)
make evaluate_model_generated DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b START=0 END=10

# Berlue : construit/stocke la matrice Berlue-vs-juge
make evaluate_model_generated_matrix DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b

# baseline : classifie les réponses déjà générées ci-dessus, sans regénérer ni rejuger —
# seul endroit où la baseline mode 2 est calculée
make evaluate_model_generated_baseline DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b START=0 END=10

# baseline : construit/stocke la matrice baseline-vs-juge, depuis le cache —
# ne dépend jamais du verdict Berlue, reuse le verdict du juge déjà en cache
make evaluate_model_generated_baseline_matrix DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b

# remplit tout le cache d'un scope (Berlue + baseline, séparément) puis
# construit leurs 2 matrices (elles aussi séparées), en un seul appel
make evaluate_model_generated_all DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b

# WARMUP=true précharge generator/judge en VRAM (appel jetable chacun) avant
# de démarrer le chrono — utile pour un benchmark, sans quoi le premier appel
# réel paierait le chargement modèle (cf. execution-benchmark.md)
make evaluate_model_generated DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b START=0 END=10 WARMUP=true
```

Chaque commande du mode généré affiche, en plus du compte de questions
traitées, un récapitulatif de temps détaillé par tâche (`⏱ génération :
Xs total, Ys/appel (n=...) | Berlue : ... | juge : ...` pour
`evaluate_model_generated` ; `⏱ baseline NLI : ...` pour
`evaluate_model_generated_baseline`, jamais mélangés) — ne compte que les
calculs réellement effectués (jamais les hits de
cache), donc comparable d'un run à l'autre même si le scope est partiellement
déjà en cache.

Séquence réelle testée (les deux modes, génération scindée en tranches
pour simuler plusieurs workers sur le même scope) :
[`execution-benchmark.md`](execution-benchmark.md#local).

## GCP — Job Cloud Run (`berlue-eval-mocked`)

`EVAL_RUN_TARGET=gcp` reste un paramètre validé sans effet direct sur le
code Python lui-même (`GcpResultStore` bascule déjà seul entre
impersonation locale et identité Cloud Run — cf.
[`auth.md`](../gcp/auth.md)) — mais un vrai chemin d'exécution existe : le
Job Cloud Run `berlue-eval-mocked`, image `Dockerfile.eval`, vérifié en
conditions réelles (déployé, exécuté, résultats confirmés dans Firestore).

```bash
# mode dataset, sur [START:END]
make cloudrun_eval_run DATASET=halueval MODEL_ID=llama3.1:8b START=0 END=50

# mode généré (appelle le service Ollama berlue-llm) + construction des matrices
make cloudrun_eval_run DATASET=halueval MODEL_ID=llama3.1:8b MODE=generated MATRIX=true
```

Détail des cibles de déploiement/exécution (build, deploy, logs...) :
[`cloudrun.md`](../gcp/cloudrun.md).

`cloudrun_eval_run` accepte les mêmes variables que `evaluate_model`
(`DATASET`, `RATIO`, `MODEL_ID`, versions, `START`/`END`), plus
`MODE=dataset|generated` et `MATRIX=true|false`. Passées au Job via
`--update-env-vars` (`BERLUE_JOB_*`, lues par `run_eval.py` en plus des
flags CLI) plutôt que `gcloud run jobs execute --args`, qui a un bug connu :
il rejette toute liste contenant une valeur dupliquée (ex. `v1` répété pour
plusieurs versions) — cf. `tmp/eval-model-design.md` §17 pour le détail.

**Mode `generated`** appelle Ollama (génération + juge) — servi par un
service Cloud Run séparé, `berlue-llm` (GPU L4, privé, appelé par le Job
via jeton OIDC), pas bundlé dans l'image d'éval — détail, IAM, contraintes
(scale-to-zero) : [`cloudrun.md`](../gcp/cloudrun.md).

**"-mocked" dans le nom de l'image d'éval** : rappel volontaire que le
pipeline Berlue exécuté dedans est encore `RandomBerluePipeline`, pas
`HurluBerlu`.

Temps mesurés local vs GCP pour les deux modes :
[`execution-benchmark.md`](execution-benchmark.md).
