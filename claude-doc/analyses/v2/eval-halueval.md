# Évaluation v2 — HaluEval, mode généré

Second run de la campagne v2, sur le jeu principal.

## Configuration et durée

```
dataset      halueval, ratio 0.90   →  1000 questions
mode         généré (mode 2)
génération   llama3.2:3b      extraction / RAG / juge : llama3.1:8b
versions     v2
```

**3 h 33** au total. La répartition du temps est sans appel :

```
Berlue        12 350 s     97 %      12,4 s par question
génération       310 s      2 %       0,31 s
juge              78 s      1 %       0,08 s
```

Le pipeline de vérification coûte quarante fois la génération qu'il vérifie.

## Matrice

|  | prédit vrai | indécis | prédit faux | total |
|---|---|---|---|---|
| **vérité VRAI** | 125 | 210 | 101 | 436 |
| **vérité FAUX** | 161 | 202 | 201 | 564 |

Vérité-terrain établie par le juge `llama3.1:8b`, qui compare la réponse générée
aux réponses de référence du dataset.

## Lecture

**Le pouvoir de séparation est faible : 12,4 points.** Berlue contredit 35,6 %
des réponses fausses (201/564) contre 23,2 % des vraies (101/436). Il sépare les
deux populations, mais l'écart est mince — et plus mince encore que sur
TruthfulQA, qui donnait 15,4 points sur 158 questions seulement.

**161 réponses fausses sont validées**, soit 28,5 % d'entre elles. C'est le
chiffre le plus gênant pour un usage produit : le voyant vert se trompe une fois
sur trois environ.

**L'indécision reste massive** — 412 sur 1000, 41 %, très proche des 44 % de
TruthfulQA malgré des couvertures documentaires différentes.

**Le modèle évalué se trompe majoritairement.** Le juge a classé 564 réponses
fausses sur 1000. HaluEval est bâti pour piéger, donc ce n'est pas une surprise,
mais ça donne le point de comparaison : un détecteur qui dirait « faux » à tout
aurait 56,4 % de raison.

Berlue, lui, ne contredit que 302 affirmations au total (201 justes + 101 à
tort). **Il tranche peu, et quand il tranche, il se trompe une fois sur trois.**

## À rapprocher de l'analyse des 25 questions

Deux défauts identifiés trace à l'appui expliquent une partie de ces chiffres,
et sont détaillés dans `analyse-25-questions-2026-09-03.md` :

- **la double négation d'un extrait REFUTES**, qui inverse le verdict ;
- **les affirmations composites**, où un présupposé faux est ignoré au profit
  d'un attribut vrai.

Les deux produisent des faux positifs, ce qui est exactement ce que montre la
ligne « vérité FAUX / prédit vrai ».

## Reproduire

```bash
make evaluate_model_generated_all \
  DATASET=halueval RATIO=0.90 MODEL_ID=llama3.2:3b JUDGE_MODEL=llama3.1:8b WARMUP=true
```

**Passer `JUDGE_MODEL` explicitement** : le défaut du Makefile a longtemps été
`qwen2.5:0.5b`, corrigé depuis, mais vérifier la ligne de commande effective
reste la seule garantie.
