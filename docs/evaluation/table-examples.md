# Exemple de contenu des tables locales

Une ligne d'exemple par table du cache local SQLite — schéma et rôle de
chaque table dans [`storage.md`](storage.md), ce que chaque mode
mesure dans [`modes.md`](modes.md). Toutes les lignes ci-dessous viennent
d'un run réel minimal (`model_id="demo-new-schema"`, pipeline mock
`RandomBerluePipeline`, génération et jugement réels via Ollama
`llama3.1:8b`) sur 3 questions de HaluEval.

## Mode 1

### `eval_predictions`

```
dataset             : "halueval"
ratio               : 0.8
model_id            : "demo-new-schema"
pipeline_version    : "v1"
eval_version        : "v1"
question_hash       : "07ce787bc6d87a79fbdfa0f3c2f3e3c1d7fe56cfb04fe58675d030503fb54be2"
answer_hash         : "aff64e4fd520bd185cb01adab98d2d20060f621c62d5cad5204712cfa2294ef7"
question            : " \"The Twentieth Century is Almost Over\" was re-recorded five years later by Cash and Waylon Jennings, Kris Kristofferson, and Willie Nelson, one of the most recognized artists in what type of music?"
answer               : "country"
ground_truth_label  : 1
verdict              : "not_enough_info"
computed_at          : "2026-08-29T01:08:11.079717+00:00"
```

### `eval_matrices`

Même run minimal (6 lignes — 3 questions × réponse vraie/fausse). Le vrai
split de test officiel HaluEval@0.8 fait 4000 lignes — `dataset_test_size`
le montre, distinct de `n_examples` : ce résultat est un run **partiel**, pas
le vrai chiffre du modèle sur le dataset complet.

```
dataset                                : "halueval"
ratio                                   : 0.8
model_id                                : "demo-new-schema"
pipeline_version                        : "v1"
eval_version                            : "v1"
ground_truth_true_predicted_true        : 0
ground_truth_true_predicted_undecided   : 2
ground_truth_true_predicted_false       : 1
ground_truth_false_predicted_true       : 1
ground_truth_false_predicted_undecided  : 1
ground_truth_false_predicted_false      : 1
n_examples                              : 6
dataset_test_size                       : 4000
computed_at                             : "2026-08-29T06:34:35.089102+00:00"
```

## Mode 2

### `llm_answers`

```
model_id           : "demo-new-schema"
generation_version : "v1"
question_hash       : "07ce787bc6d87a79fbdfa0f3c2f3e3c1d7fe56cfb04fe58675d030503fb54be2"
question            : " \"The Twentieth Century is Almost Over\" was re-recorded five years later by Cash and Waylon Jennings, Kris Kristofferson, and Willie Nelson, one of the most recognized artists in what type of music?"
answer               : "Willie Nelson is one of the most recognized artists in country music. He is a legendary singer, songwriter, and musician known for his distinctive voice and style, which has been a staple of the country music genre for decades. Nelson's music often incorporates elements of folk, blues, and Americana, but country music is his primary genre."
computed_at          : "2026-08-29T01:08:11.938688+00:00"
```

### `judge_verdicts`

```
model_id           : "demo-new-schema"
generation_version : "v1"
judge_model         : "llama3.1:8b"
eval_version        : "v1"
question_hash       : "07ce787bc6d87a79fbdfa0f3c2f3e3c1d7fe56cfb04fe58675d030503fb54be2"
question            : " \"The Twentieth Century is Almost Over\" was re-recorded five years later by Cash and Waylon Jennings, Kris Kristofferson, and Willie Nelson, one of the most recognized artists in what type of music?"
verdict              : "supported"
computed_at          : "2026-08-29T01:08:12.054771+00:00"
```

### `eval_berlue_generated`

Verdict issu du pipeline mock (`RandomBerluePipeline`, tiré au hasard) tant
que le vrai `HurluBerlu` n'est pas branché sur ce mode — non représentatif,
cf. [`modes.md`](modes.md).

```
dataset             : "halueval"
ratio               : 0.8
model_id            : "demo-new-schema"
pipeline_version    : "v1"
generation_version  : "v1"
eval_version        : "v1"
question_hash       : "07ce787bc6d87a79fbdfa0f3c2f3e3c1d7fe56cfb04fe58675d030503fb54be2"
question            : " \"The Twentieth Century is Almost Over\" was re-recorded five years later by Cash and Waylon Jennings, Kris Kristofferson, and Willie Nelson, one of the most recognized artists in what type of music?"
verdict             : "not_enough_info"
computed_at         : "2026-08-29T01:08:11.943426+00:00"
```

### `eval_baseline_generated`

```
dataset             : "halueval"
ratio               : 0.8
model_id            : "demo-new-schema"
generation_version  : "v1"
eval_version        : "v1"
question_hash       : "07ce787bc6d87a79fbdfa0f3c2f3e3c1d7fe56cfb04fe58675d030503fb54be2"
question            : " \"The Twentieth Century is Almost Over\" was re-recorded five years later by Cash and Waylon Jennings, Kris Kristofferson, and Willie Nelson, one of the most recognized artists in what type of music?"
verdict             : "contradicted"
computed_at         : "2026-08-29T01:08:11.946752+00:00"
```

### `eval_matrices_generated_berlue`

Même réserve que `eval_berlue_generated` — pipeline mock, matrice non
représentative. Même run minimal (3 questions) — 2000 questions valides dans
le vrai split HaluEval@0.8, donc `dataset_test_size` marque bien ce résultat
comme partiel :

```
dataset                                : "halueval"
ratio                                   : 0.8
model_id                                : "demo-new-schema"
pipeline_version                        : "v1"
generation_version                      : "v1"
eval_version                            : "v1"
ground_truth_true_predicted_true        : 0
ground_truth_true_predicted_undecided   : 2
ground_truth_true_predicted_false       : 0
ground_truth_false_predicted_true       : 0
ground_truth_false_predicted_undecided  : 0
ground_truth_false_predicted_false      : 1
n_examples                              : 3
dataset_test_size                       : 2000
computed_at                             : "2026-08-29T06:34:37.553773+00:00"
```

### `eval_matrices_generated_baseline`

Même run minimal, baseline NLI réelle vs juge réel :

```
dataset                                : "halueval"
ratio                                   : 0.8
model_id                                : "demo-new-schema"
generation_version                      : "v1"
eval_version                            : "v1"
ground_truth_true_predicted_true        : 0
ground_truth_true_predicted_undecided   : 0
ground_truth_true_predicted_false       : 2
ground_truth_false_predicted_true       : 0
ground_truth_false_predicted_undecided  : 0
ground_truth_false_predicted_false      : 1
n_examples                              : 3
dataset_test_size                       : 2000
computed_at                             : "2026-08-29T06:34:37.557466+00:00"
```
