# Dataset HaluEval

Dataset d'hallucinations générées automatiquement pour des paires
question/réponse — un des deux jeux utilisés pour l'évaluation offline
([`baseline.md`](../evaluation/baseline.md)), avec TruthfulQA
([`truthfulqa.md`](truthfulqa.md)).

## Ce que le projet en utilise

Chargé en JSON Lines (`question`, `right_answer`, `hallucinated_answer` par
ligne) — voir `berlue/evaluation/data.py`. Ce loader ramène HaluEval et
TruthfulQA à un même schéma normalisé ; [`baseline.md`](../evaluation/baseline.md)
décrit ce fonctionnement partagé (split train/test sans fuite de données, etc.).

## Pour aller plus loin

Exploration complète (structure détaillée, catégories d'hallucination,
statistiques, prétraitement) :
[`halueval_explication.md`](../../historique-etude-data/halueval_explication.md)
— matériel d'étude, pas la doc de référence de l'usage dans le repo.
