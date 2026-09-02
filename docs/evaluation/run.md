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

## `START`/`END` : uniquement pour découper en plusieurs appels

Chaque commande de remplissage de cache (`evaluate_model`,
`evaluate_model_generated`, `evaluate_model_generated_baseline`, en local
comme sur GCP) accepte `START`/`END`, mais **aucun des deux n'est requis** :
`START` vaut `0` par défaut, `END` vide (défaut) veut dire "jusqu'au bout du
scope" — omis, une commande traite donc tout le scope en un seul appel. Ne
préciser `START`/`END` que pour répartir volontairement le travail en
plusieurs appels (plusieurs workers, un run trop long à faire d'un coup,
reprendre après un Ctrl+C) — les exemples ci-dessous ne les montrent que
dans ce cas précis.

**Combien d'éléments dans un scope, avant de découper** (aucun calcul,
juste une lecture) :

```bash
make evaluate_model_coverage DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b               # mode dataset (défaut)
make evaluate_model_coverage DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b MODE=generated
```

Affiche le total (lignes en mode dataset, questions distinctes en mode
généré — c'est bien ce total, pas `_official_valid_question_count`, sur
lequel `START`/`END` itèrent réellement, une question sans référence
complète y comptant aussi même si elle sera ignorée à l'exécution) plus les
index déjà en cache / manquants — pratique aussi bien pour planifier un
découpage que pour voir ce qu'il reste après un run interrompu. Marche en
local (lit `BERLUE_EVAL_STORE_TARGET`) comme contre le store GCP, sans
jamais avoir besoin du service.

## Local

Process Python natif — `berlue.evaluation.run_eval` tourne directement sur
la machine qui lance `make`, pas de conteneur.

### Mode dataset

Berlue et la baseline NLI sont deux chemins **toujours séparés** ici aussi
(même principe qu'en mode généré, cf. section suivante) — deux commandes
indépendantes, jamais mélangées dans un même appel.

**Berlue** (le pipeline évalué, `MODEL_ID`/`PIPELINE_VERSION` — aujourd'hui
`RandomBerluePipeline`, un mock) :

```bash
# remplit tout le cache du scope en un seul appel
make evaluate_model DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b

# découpé en deux appels (deux workers, ou pour ne pas tout faire d'un bloc)
make evaluate_model DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b START=0 END=100
make evaluate_model DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b START=100 END=200

# construit/stocke la matrice depuis le cache déjà rempli
make evaluate_model_matrix DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b

# remplit tout le cache d'un scope puis construit sa matrice, en un seul
# appel — pratique en dev, ne reflète pas le découpage en tranches d'un run
# réel (cf. séquence testée plus bas). Ne touche jamais la baseline.
make evaluate_model_all DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b
```

**Baseline NLI** (`NliBaseline` — TF-IDF + régression logistique,
`berlue/nli_baseline/`, comparaison classique, pas un LLM) : indépendante
de `MODEL_ID`/`PIPELINE_VERSION`, ne dépend que de `(dataset, ratio)` — un
seul appel sert tous les scopes qui partagent ce couple. Recalculée à la
volée à chaque appel, jamais stockée (bon marché, CPU seul —
[`storage.md`](storage.md#résultats-individuels--un-par-prédiction-berlue-ou-baseline)
pour le détail) :

```bash
make evaluate_baseline DATASET=halueval RATIO=0.8
```

### Mode généré

Berlue et la baseline sont deux chemins **toujours séparés** ici aussi
(cf. [`modes.md`](modes.md)) — chacun son remplissage de cache, chacun sa
matrice, jamais mélangés dans un même appel. Les deux ont la même forme à
trois commandes (fill / matrice / les deux d'un coup).

**Berlue** (génération + fact-check Berlue + juge — jamais la baseline) :

```bash
# tout le scope, un seul appel
make evaluate_model_generated DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b

# ou découpé en deux appels (deux workers, ou pour ne pas tout faire d'un bloc)
make evaluate_model_generated DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b START=0 END=50
make evaluate_model_generated DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b START=50 END=100

# construit/stocke la matrice Berlue-vs-juge, depuis le cache déjà rempli
make evaluate_model_generated_matrix DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b

# les deux d'un coup — tout le scope, un seul appel. Jamais la baseline
# (même principe qu'en mode dataset, evaluate_model_all — les deux "_all"
# ne gèrent jamais l'autre chemin)
make evaluate_model_generated_all DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b

# WARMUP=true précharge generator/judge en VRAM (appel jetable chacun) avant
# de démarrer le chrono — utile pour un benchmark, sans quoi le premier appel
# réel paierait le chargement modèle (cf. execution-benchmark.md). Pertinent
# surtout sur la première tranche d'un découpage — sur un seul appel qui
# couvre tout le scope, le chargement n'est de toute façon payé qu'une fois.
make evaluate_model_generated DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b START=0 END=50 WARMUP=true

# CONCURRENCY : questions traitées en parallèle au sein de chaque étape
# (génération, Berlue, juge), 1 par défaut (séquentiel) — doit être égal
# au OLLAMA_NUM_PARALLEL du serveur ciblé pour ce run précis (jamais un
# maximum "au cas où" côté serveur, ça coûte du débit réel, cf.
# docs/gcp/ollama-gpu-parallelism.md et execution-benchmark.md pour la
# méthode et des chiffres mesurés).
make evaluate_model_generated DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b CONCURRENCY=32
```

Procédure pour déterminer le meilleur `CONCURRENCY`/`OLLAMA_NUM_PARALLEL`
sur une machine donnée (stress test rapide puis confirmation sur le vrai
batch) : [`ollama-gpu-parallelism.md`](../gcp/ollama-gpu-parallelism.md#procédure-trouver-le-concurrency-optimal-sur-sa-machine) —
chiffres déjà mesurés sur les machines de référence dans
[`execution-benchmark.md`](execution-benchmark.md), à reproduire sur une
autre machine plutôt qu'à supposer.

**Baseline NLI** (classifie les réponses déjà générées par Berlue
ci-dessus, sans regénérer ni rejuger — seul endroit où la baseline mode 2
est calculée, jamais dans `evaluate_model_generated`) :

```bash
# classifie tout le cache d'un scope
make evaluate_model_generated_baseline DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b

# construit/stocke la matrice baseline-vs-juge, depuis le cache —
# ne dépend jamais du verdict Berlue, reuse le verdict du juge déjà en cache
make evaluate_model_generated_baseline_matrix DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b

# les deux d'un coup — tout le scope, un seul appel. Jamais Berlue
make evaluate_model_generated_baseline_all DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b
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

## GCP — service Cloud Run (`berlue-eval`)

`EVAL_RUN_TARGET=gcp` reste un paramètre validé sans effet direct sur le
code Python lui-même (`GcpResultStore` bascule déjà seul entre
impersonation locale et identité Cloud Run — cf.
[`auth.md`](../gcp/auth.md)) — mais un vrai chemin d'exécution existe : le
service Cloud Run `berlue-eval` (`berlue.api.eval_service`, servi par l'image
applicative unique via `BERLUE_APP_MODULE`), tourne en continu (`min-instances=1`,
monté/éteint par `gcp_eval_up`/`gcp_down`) plutôt qu'un conteneur neuf par
exécution — même contrat de flags que la CLI locale, reçus en JSON par un
endpoint `POST /invoke` :

```bash
# DATASET/RATIO ici préchauffent aussi le split de test (cf. cloudrun.md) —
# à indiquer pour matcher le run visé, sinon le premier vrai appel le repaie
make gcp_eval_up DATASET=halueval RATIO=0.8 WARM_MODELS="llama3.1:8b"
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b   # tout le scope, un seul appel

# ou découpé (START/END facultatifs, cf. section dédiée plus haut) :
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b START=0 END=50
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b START=50 END=100

# mode généré (appelle le service Ollama berlue-llm) + construction des matrices
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.8 MODEL_ID=llama3.1:8b MODE=generated MATRIX=true

make gcp_down                                               # min-instances=0, en fin de session
```

Accepte les mêmes variables que `evaluate_model`/`evaluate_model_generated`
(`DATASET`, `RATIO`, `MODEL_ID`, versions, `START`/`END`), plus
`MODE=dataset|generated`, `MATRIX=true|false`, `WARMUP=true|false`,
`BASELINE=true|false`, `COVERAGE=true|false` et `CONCURRENCY` (mode
`generated` uniquement — nécessite `berlue-llm` redéployé avec un
`OLLAMA_NUM_PARALLEL` au moins égal, cf.
[`cloudrun.md`](../gcp/cloudrun.md) et
[`execution-benchmark.md`](execution-benchmark.md) pour des chiffres
mesurés).

**Mode `generated`** appelle Ollama (génération + juge) — servi par un
service Cloud Run séparé, `berlue-llm` (GPU L4, privé, appelé via jeton
OIDC), pas bundlé dans l'image d'éval — détail, IAM, contraintes
(scale-to-zero) : [`cloudrun.md`](../gcp/cloudrun.md).

Détail des cibles (déploiement, `gcp_eval_up`/`gcp_down`, `WARM_MODELS`,
`gcp_verify_warm`) : [`cloudrun.md`](../gcp/cloudrun.md). Temps mesurés
local vs GCP pour les deux modes : [`execution-benchmark.md`](execution-benchmark.md).
