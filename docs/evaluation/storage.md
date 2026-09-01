# Stockage des résultats d'évaluation

Où les résultats de l'évaluation du pipeline Berlue sont stockés, et
comment le cache évite de tout recalculer à chaque lancement — piloté par
`EVAL_STORE_TARGET` (`local` ou `gcp`), indépendant d'où le calcul
s'exécute (cf. [`run.md`](run.md)). Pour ce que chaque mode mesure, voir
[`modes.md`](modes.md) ; pour les routes API de lecture, voir
[`api.md`](api.md).

## Concepts

Le modèle de données est le même quel que soit le backend (`local` ou
`gcp`) — seule son implémentation physique change (cf.
[`Implémentation locale`](#implémentation-locale-sqlite) et
[`Implémentation GCP`](#implémentation-gcp-firestore--bigquery) plus bas).

### Scope et versions

Un résultat stocké est identifié par un **scope** (`EvalScope`) — un seul
`dataset`, ratio train/test, modèle évalué, trois versions — plus la
question (et la réponse, en mode dataset). Deux invocations avec le même
scope (reprise après interruption, plusieurs workers en parallèle)
retrouvent donc le même cache : une prédiction déjà calculée n'est jamais
recalculée.

**Un scope porte toujours un seul `dataset`.** Un résultat ou une matrice ne
mélange jamais plusieurs datasets — pour comparer HaluEval et TruthfulQA, on
compare deux scopes séparés, jamais une matrice combinée.

**Trois axes de version indépendants**, chacun couvrant un composant
différent — pas un seul `berlue_version` qui mélangerait tout :

| Param (`params.py`) | Couvre |
|---|---|
| `PIPELINE_VERSION` | Logique du pipeline Berlue (RAG inversé + SelfCheckGPT) |
| `GENERATION_VERSION` | Logique/prompt de génération de réponse par le LLM sous test |
| `EVAL_VERSION` | Méthodologie d'éval elle-même (split train/test, sélection du jeu de test, prompt du juge, calcul des matrices) |

Ce que l'identifiant inclut varie par table selon de quel(s) axe(s) elle
dépend réellement — voir le détail ci-dessous : une réponse générée ne
dépend que du modèle et de `generation_version`, ni du dataset ni de
`pipeline_version`, donc `llm_answers` ne retient que ces deux-là.

### Résultats individuels — un par prédiction (Berlue ou baseline)

Chaque prédiction/verdict (fact-check Berlue, classification baseline,
réponse générée, verdict du juge) est stocké **immédiatement après son
calcul**, pas en fin de batch — une interruption ne perd que la prédiction
en cours. Beaucoup d'écritures ponctuelles, potentiellement concurrentes
(plusieurs workers sur le même scope), avec un besoin d'atomicité pour le
dédoublonnage : la boucle d'éval vérifie le cache avant chaque appel
pipeline/LLM.

Une **clé** (identifiant unique) et une **valeur** (le verdict/la réponse)
par table :

| Table | Mode | Valeur | Clé |
|---|---|---|---|
| `eval_predictions` | 1 | Verdict Berlue sur la réponse du dataset | `dataset, ratio, model_id, pipeline_version, eval_version, question_hash, answer_hash` |
| `eval_signals` | 1 | Signaux Berlue **avant** fusion (affirmations, verdicts RAG, scores SelfCheck) | `dataset, ratio, model_id, pipeline_version, question_hash, answer_hash` |
| `llm_answers` | 2 | Réponse générée par le LLM sous test | `model_id, generation_version, question_hash` |
| `judge_verdicts` | 2 | Verdict du LLM-juge sur la réponse générée | `model_id, generation_version, judge_model, eval_version, question_hash` |
| `eval_berlue_generated` | 2 | Verdict Berlue sur la réponse générée | `dataset, ratio, model_id, pipeline_version, generation_version, eval_version, question_hash` |
| `eval_baseline_generated` | 2 | Verdict baseline NLI sur la réponse générée | `dataset, ratio, model_id, generation_version, eval_version, question_hash` |

`eval_signals` n'est pas indexée sur `eval_version` : la méthodologie d'éval
n'a aucune influence sur ce que le RAG et SelfCheck produisent pour un couple
(question, réponse) donné. Cette table existe pour découpler le coût du
calcul de celui de la décision — les signaux valent plusieurs appels LLM,
la fusion qui les consomme est une fonction pure et instantanée. D'où le
geste de calibration :

```bash
# purge la fusion en gardant les signaux
make evaluate_model_purge PURGE_SCOPE=fusion PIPELINE_VERSION=<version> ...
# relance : RAG et SelfCheck sortent du cache, seule la fusion recalcule
BERLUE_FUSION_DIVERGENCE_NEUTRE=0.7 make evaluate_model_all ...
```

`llm_answers`/`judge_verdicts` ne sont indexées ni sur `dataset`/`ratio`
(une réponse générée pour une question donnée ne dépend pas du scope qui
l'a demandée) ni sur `pipeline_version` (une génération LLM ne dépend pas de
la version du pipeline Berlue) — modèle+`generation_version`+question
suffisent. `judge_verdicts` ajoute `eval_version` (le prompt du juge en
fait partie) ; `eval_baseline_generated` n'a pas de `pipeline_version` : la
baseline NLI ne dépend pas du pipeline Berlue, mais dépend de `dataset`/
`ratio` (quelles questions sont traitées) et `eval_version`. `question`/
`answer` sont hashés (SHA-256) dans les clés pour éviter des valeurs
texte arbitrairement longues dans un identifiant — le texte brut reste
stocké à côté pour lecture/debug.

La baseline NLI du **mode 1**, elle, n'est jamais stockée — recalculée à la
volée à chaque appel (route API `GET /baseline-evaluation`, cible `make
evaluate_baseline` — cf. [`run.md`](run.md#mode-dataset)), indépendante de
`model_id`/`pipeline_version` : un seul appel sert pour tous les scopes qui
partagent le même `(dataset, ratio)`.

### Matrices — une par scope, agrégée depuis les résultats individuels

Construites **une fois**, à partir de tout ce qui est déjà en cache pour un
scope (union du travail de tous les runs/workers passés dessus, pas
seulement la tranche traitée par l'appel courant) — `evaluate_model_matrix`/
`evaluate_model_generated_matrix`/`evaluate_baseline_generated_matrix`
échouent explicitement si une prédiction manque pour ce qui leur a été
demandé de couvrir, plutôt que de calculer silencieusement une matrice à
trous. Berlue et baseline sont deux chemins séparés même en mode 2 : la
matrice Berlue (`evaluate_model_generated_matrix`) ne dépend jamais du
verdict baseline, et réciproquement. Une seule ligne par scope — c'est un
**snapshot du dernier calcul complet**, pas un delta ni un historique : la
rappeler remplace la version précédente, jamais une fusion des deux.
Écriture rare, lecture/listing fréquent (les routes API, cf.
[`api.md`](api.md)).

| Table | Mode | Valeur | Clé |
|---|---|---|---|
| `eval_matrices` | 1 | Matrice Berlue vs vérité-terrain du dataset | `dataset, ratio, model_id, pipeline_version, eval_version` |
| `eval_matrices_generated_berlue` | 2 | Matrice Berlue vs juge | `dataset, ratio, model_id, pipeline_version, generation_version, eval_version` |
| `eval_matrices_generated_baseline` | 2 | Matrice baseline vs juge | `dataset, ratio, model_id, generation_version, eval_version` |

### Run complet ou partiel : `n_examples` vs `dataset_test_size`

`n_examples` compte ce que la matrice couvre réellement — mais rien n'empêche
de la construire sur un sous-ensemble volontairement réduit (démo,
développement, `test_examples` fourni explicitement). Pour distinguer un run
intégral d'un run partiel, chaque matrice porte aussi `dataset_test_size` :
la taille du **split de test officiel complet** pour ce `dataset`/`ratio`
(nombre de lignes en mode 1, nombre de questions valides — réf. correcte ET
incorrecte — en mode 2), recalculée indépendamment de tout `test_examples`
fourni en override. Le split est déterministe (seed fixe, versions
numpy/pandas/scikit-learn épinglées dans `requirements.txt`) : deux machines
qui le recalculent obtiennent le même total.

`n_examples == dataset_test_size` signifie un run complet ; sinon, un
sous-ensemble partiel. `dataset_test_size` vaut `None` quand `dataset` n'est
pas un dataset réel connu (utilisé uniquement par les tests unitaires, avec
des noms fictifs) — pas de total officiel à comparer dans ce cas.

## Implémentation locale (SQLite)

`LocalResultStore` (`berlue.evaluation.result_store`), fichier SQLite à
`params.MLOPS_DB_PATH` (`./data/mlops/hallucination_tracker.db` par défaut).
Huit tables au total (5 résultats individuels + 3 matrices, cf.
[`Concepts`](#concepts)). L'atomicité du dédoublonnage sur les résultats
individuels vient d'une contrainte `UNIQUE` (`INSERT OR IGNORE`) : deux
workers tombant sur la même question ne dupliquent rien.

Composants :
- Table `eval_predictions`/`llm_answers`/`judge_verdicts`/
  `eval_berlue_generated`/`eval_baseline_generated` — résultats individuels.
- Table `eval_matrices`/`eval_matrices_generated_berlue`/
  `eval_matrices_generated_baseline` — matrices.

Vérifier ce qui est déjà en cache :

```bash
# scopes déjà présents, par table de résultats
make evaluate_explore_results

# idem pour les matrices
make evaluate_explore_matrices

# index déjà en cache / manquants, pour un scope connu
make evaluate_model_coverage DATASET=halueval MODEL_ID=llama3.1:8b
```

Inspecter le contenu brut d'une table (fichier SQLite normal, aucun outil
dédié requis) :

```bash
# 5 dernières prédictions Berlue sur ce dataset
sqlite3 ./data/mlops/hallucination_tracker.db \
  "SELECT * FROM eval_predictions WHERE dataset='halueval' ORDER BY rowid DESC LIMIT 5;"

# la matrice stockée pour un scope précis
sqlite3 ./data/mlops/hallucination_tracker.db \
  "SELECT * FROM eval_matrices WHERE dataset='halueval' AND model_id='llama3.1:8b';"
```

Purger (filtré, chaque paramètre omis est un joker — cf.
`store.purge()`) :

```bash
make evaluate_model_purge DATASET=halueval MODEL_ID=llama3.1:8b
make evaluate_model_purge DATASET=halueval MODEL_ID=llama3.1:8b PURGE_SCOPE=matrices
```

## Implémentation GCP (Firestore + BigQuery)

`GcpResultStore` (`berlue.evaluation.gcp_result_store`) implémente la même
interface que `LocalResultStore` — `get_result_store()` le retourne pour
`target="gcp"`. Deux projets configurables indépendamment
(`EVAL_FIRESTORE_PROJECT`, `EVAL_BIGQUERY_PROJECT`, projet propre par
défaut) plutôt qu'un seul `GCP_PROJECT` qui piloterait tout : une équipe de
plusieurs développeurs, chacun avec son propre projet GCP, doit pouvoir
partager un cache déjà rempli par un collègue plutôt que de tout recalculer.

Composants :
- **Firestore** — les 5 tables de résultats individuels, une collection
  chacune. Profil transactionnel — le point fort de Firestore, contrairement
  à BigQuery qui n'a pas d'équivalent atomique simple à "insert si absent"
  et impose des quotas stricts sur le nombre d'opérations DML par table, mal
  adapté à des milliers de petites écritures individuelles. Dédoublonnage
  via une création avec `documentId` imposé (409 si le document existe
  déjà) plutôt qu'une contrainte `UNIQUE` (pas de notion native).
- **BigQuery** (dataset `berlue`, cf. [`composants.md`](../gcp/composants.md))
  — les 3 tables de matrices. Peu d'écritures, beaucoup de lecture/listing,
  potentiel d'analyse croisée plus tard ; upsert via `MERGE`.
- **`sa-berlue`** (service account) — identité utilisée pour lire/écrire,
  jamais la session humaine directement. Mécanisme d'authentification
  complet (impersonation locale vs Cloud Run) : [`auth.md`](../gcp/auth.md).

**Pourquoi pas l'authentification standard** : ni Firestore ni BigQuery ne
passent par l'Application Default Credentials habituelle d'une session
humaine sur ce projet — une politique de réauth ("Cloud session length",
Google Workspace) bloque spécifiquement leur rafraîchissement pour ces deux
APIs (Storage n'est pas concerné). La lib cliente Firestore échoue par
ailleurs avec `Invalid database id %28default%29` même avec des credentials
valides — bug non résolu de la lib, indépendant de l'auth, constaté en
conditions réelles. Contournement dans les deux cas : la session `gcloud`
CLI elle-même (non soumise à cette politique) :
- **BigQuery** : `google.cloud.bigquery.Client` avec des credentials
  personnalisées qui rafraîchissent via `gcloud`.
- **Firestore** : appels REST directs (`requests`) plutôt que la lib
  cliente officielle, pour contourner son bug.

Si l'admin Workspace lève la politique de réauth ADC et que le bug
Firestore est corrigé en amont, `GcpResultStore` peut repasser sur
`firestore.Client()`/`bigquery.Client()` avec les ADC standard — écart
documenté en tête de `gcp_result_store.py`.

Vérifier ce qui est déjà en cache (mêmes outils qu'en local, préfixés
`BERLUE_EVAL_STORE_TARGET=gcp`) :

```bash
# scopes déjà présents, par table de résultats
BERLUE_EVAL_STORE_TARGET=gcp make evaluate_explore_results

# idem pour les matrices
BERLUE_EVAL_STORE_TARGET=gcp make evaluate_explore_matrices

# index déjà en cache / manquants, pour un scope connu
BERLUE_EVAL_STORE_TARGET=gcp make evaluate_model_coverage DATASET=halueval MODEL_ID=llama3.1:8b
```

`list_*_scopes()` ne scanne jamais les collections de résultats
elles-mêmes sur Firestore (coûteux, 1 lecture facturée par document) — lit
un registre séparé (`_scope_registry`), tenu à jour par incréments
bufferisés en mémoire et envoyés par lots (`flush_registry()`, appelée
périodiquement et en fin de run, y compris sur Ctrl+C). Les matrices n'ont
pas besoin de cette indirection : peu de lignes, une par scope.

Inspecter le contenu brut — nécessite un accès direct (pas `sa-berlue`),
cf. [`share.md`](../gcp/share.md#consulter-les-données-directement--firestorebigquery) :

```bash
# BigQuery : la matrice stockée pour un scope précis
bq query --use_legacy_sql=false \
  "SELECT * FROM \`${GCP_PROJECT}.berlue.eval_matrices\` WHERE dataset='halueval' AND model_id='llama3.1:8b'"
```

Ou par la Console — pas de CLI de requête générique côté Firestore (pas
d'équivalent à `bq query`), la Console est le chemin normal pour les deux :

```
# BigQuery : Explorer > <projet> > berlue > eval_matrices, onglet "Preview"
https://console.cloud.google.com/bigquery?project=${GCP_PROJECT}

# Firestore : base (default) > collection eval_predictions, filtrer sur
# dataset/model_id dans la barre de requête
https://console.cloud.google.com/firestore/databases/-default-/data?project=${GCP_PROJECT}
```

Purger (mêmes filtres qu'en local) :

```bash
BERLUE_EVAL_STORE_TARGET=gcp make evaluate_model_purge DATASET=halueval MODEL_ID=llama3.1:8b
```

## Transfert local → GCP

`evaluate_push_to_gcp` pousse un scope (résultats mode 1 + les 3 matrices)
du store local vers GCP, pour partager un cache déjà rempli avec l'équipe
sans passer par une exécution GCP. Ne couvre pas encore le détail ligne à
ligne des 4 tables individuelles du mode 2 (pas de méthode de listing
complet pour elles aujourd'hui, seulement un résumé de comptage).

```bash
make evaluate_push_to_gcp DATASET=halueval MODEL_ID=llama3.1:8b
```

`PUSH_SCOPE=results|matrices|all` (défaut `all`) limite ce qui est poussé.
