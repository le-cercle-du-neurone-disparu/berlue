# Analyses, par version du pipeline

Les mesures ne sont **comparables qu'à l'intérieur d'une version**. Changer un
prompt d'extraction ou de RAG change toutes les affirmations produites, donc
tous les verdicts : confronter un chiffre de v1 à un chiffre de v2 ne dit rien.

D'où ce classement par version plutôt que par date.

## v1 — jusqu'au 2 septembre 2026

Pipeline d'avant les correctifs de polarité, de troncature et de fenêtre de
contexte. Les prompts d'extraction et de RAG y ont changé trois fois en cours de
route, ce qui limite la portée des mesures.

- [`analyse-pipeline.md`](v1/analyse-pipeline.md) — synthèse de la lecture
  manuelle de 30 exemples, trace par trace
- [`exemples/`](v1/exemples) — les 30 analyses individuelles, une par fichier

## v2 — à partir du 3 septembre 2026

Première version stabilisée. Toutes les mesures antérieures ont été purgées
avant de lancer cette campagne : elles portaient des prompts différents.

Corrections qui la distinguent de v1 : polarité du RAG (une affirmation et sa
négation ne sont plus confondues), récupération des réponses tronquées, fenêtre
de contexte Ollama imposée, distinction entre panne et ignorance.

- [`eval-truthfulqa.md`](v2/eval-truthfulqa.md) — 158 questions, mode généré
- [`eval-halueval.md`](v2/eval-halueval.md) — 1000 questions, mode généré
- [`analyse-25-questions.md`](v2/analyse-25-questions.md) — les questions
  d'exemple passées à l'API, traces analysées une par une

### Résultats v2 en un coup d'œil

|  | séparation | faux positifs | indécis |
|---|---|---|---|
| TruthfulQA — Berlue | 15,4 pts | 25,0 % | 44 % |
| TruthfulQA — baseline | 12,8 pts | 7,5 % | 0 % |
| HaluEval — Berlue | 12,5 pts | 28,5 % | 41 % |
| HaluEval — baseline | **−26,5 pts** | 34,0 % | 0 % |

La séparation est l'écart entre le taux de contradiction des réponses fausses et
celui des réponses vraies. Négative, elle signifie que le détecteur contredit
**plus** les bonnes réponses que les mauvaises — c'est le cas de la baseline sur
HaluEval, où elle inverse le signal.
