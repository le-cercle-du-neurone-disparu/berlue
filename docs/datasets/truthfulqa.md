# Dataset TruthfulQA

Dataset de questions conçues pour piéger un modèle vers des réponses fausses
mais plausibles — le second jeu utilisé pour l'évaluation offline
([`baseline.md`](../evaluation/baseline.md)), avec HaluEval
([`halueval.md`](halueval.md)).

## Ce que le projet en utilise

Chargé en CSV (`Question`, `Best Answer`, `Incorrect Answers` — liste
séparée par `;`, seule la première entrée est retenue pour équilibrer avec
HaluEval) — voir `berlue/evaluation/data.py`. Ce loader ramène TruthfulQA et
HaluEval à un même schéma normalisé ; [`baseline.md`](../evaluation/baseline.md)
décrit ce fonctionnement partagé (split train/test sans fuite de données, etc.).

## Pour aller plus loin

Pas d'étude dédiée dans [`historique-etude-data/`](../../historique-etude-data/)
pour ce dataset (contrairement à HaluEval et FEVER).
