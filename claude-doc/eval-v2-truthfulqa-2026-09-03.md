# Évaluation v2 — TruthfulQA, mode généré

Premier run de la version stabilisée, après purge complète des mesures
antérieures. Toutes celles d'avant portaient des prompts différents et ne sont
pas comparables.

## Configuration

```
dataset            truthfulqa, ratio 0.8   →  158 questions
mode               généré (mode 2)
génération         llama3.2:3b             le modèle évalué
échantillons SC    llama3.2:3b             le modèle qui a répondu
extraction         llama3.1:8b
RAG                llama3.1:8b
juge               llama3.1:8b
versions           v2
```

Durée : **40 min**, soit **17,4 s par question** (2397 s Berlue sur 138 appels
non cachés). Le juge ne coûte que 87 ms par appel : il ne génère qu'un token,
TRUE ou FALSE.

## Matrice

|  | prédit vrai | indécis | prédit faux | total |
|---|---|---|---|---|
| **vérité VRAI** | 30 | 56 | 32 | 118 |
| **vérité FAUX** | 10 | 13 | 17 | 40 |

La vérité-terrain vient du juge, qui compare la réponse générée aux réponses de
référence du dataset : il a jugé 118 réponses correctes et 40 fausses.

## Lecture

**Le pouvoir de séparation est faible.** Berlue contredit 42,5 % des réponses
fausses (17/40) et 27,1 % des vraies (32/118) — un écart de **15,4 points**. Il
sépare donc les deux populations, mais mal : plus d'un quart des bonnes réponses
sont rejetées à tort.

**L'indécision domine.** 69 verdicts sur 158, soit **44 %**, sont
`not_enough_info`. Sur les réponses vraies, c'est même le verdict majoritaire
(56/118). Berlue s'abstient plus souvent qu'il ne tranche.

C'est cohérent avec ce qu'on savait : TruthfulQA n'est couvert par FEVER qu'à
5,5 %. Sans preuve documentaire, le verdict repose sur la conviction du modèle
RAG et sur SelfCheck, et la bande neutre de la fusion produit alors beaucoup
d'abstentions.

**Les faux positifs sont préoccupants.** 10 réponses fausses sur 40 sont
validées, dont on ignore si elles l'ont été par preuve FEVER ou par conviction.
Une validation par preuve sur une réponse fausse signalerait un défaut de
polarité ou de pertinence du RAG — les deux ont été corrigés hier, mais le point
mérite d'être vérifié affirmation par affirmation.

## Répartition brute des verdicts

```
not_enough_info    69
contradicted       49
supported          40
```

## Incidents

**Un juge à 0,5B lors du premier lancement.** `make/pipeline.mk` imposait
`JUDGE_MODEL ?= qwen2.5:0.5b`, qui écrasait silencieusement le `llama3.1:8b` de
`params.py` — lequel documente pourtant « 7B minimum, en dessous le juge valide
quasi systématiquement ». Run arrêté après 17 questions, défaut corrigé,
relancé. À retenir : **les défauts du Makefile priment sur ceux du code**, et
rien ne le signale.

**Deux troncatures**, une par `num_predict=600` sur le RAG et une par
`num_predict=300` sur la génération. Une occurrence chacune sur 158 questions,
et **zéro panne RAG** — aucun verdict perdu. Pas de quoi changer un paramètre en
cours de campagne, mais le seuil du RAG est désormais frôlé, les raisonnements
s'étant allongés avec le test de direction ajouté hier.

## À creuser

1. **Pourquoi 44 % d'indécision ?** Est-ce la bande neutre de la fusion qui est
   trop large, ou le RAG qui s'abstient faute de preuve ? Le champ `debug`
   permet maintenant de le voir affirmation par affirmation.
2. **Les 10 faux positifs** : par preuve FEVER, ou par conviction ? Le
   `fondement` de chaque verdict le dit.
3. **Les 32 vraies réponses contredites à tort** — même question, et c'est le
   coût le plus visible pour un utilisateur.
