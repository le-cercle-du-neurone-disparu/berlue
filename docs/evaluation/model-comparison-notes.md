# Comparaison de modèles

Résultats d'exploration manuelle sur un mini jeu de test (5 questions
HaluEval, choisies pour avoir à la fois une réponse de référence correcte et
incorrecte — cf. `evaluation.run_eval.group_examples_by_question`), comparant
plusieurs modèles Ollama comme générateur de réponse et comme juge (mode 2,
cf. [`api.md`](api.md)). Échantillon volontairement petit (exploration
qualitative, pas une mesure statistique) — chaque verdict a été vérifié à la
main contre la vérité-terrain réelle, pas seulement lu depuis la matrice de
confusion.

Modèles testés (locaux via Ollama) :

| Famille | Modèles |
|---|---|
| Meta Llama | `llama3.2:3b`, `llama3.1:8b` |
| Alibaba Qwen | `qwen2.5:3b`, `qwen2.5:7b`, `qwen2.5:14b`, `qwen3:8b` |
| Microsoft Phi | `phi3:3.8b`, `phi3:14b` |
| Mistral AI | `mistral:7b` |
| Google Gemma | `gemma2:9b` |
| DeepSeek | `deepseek-r1:8b` (modèle de raisonnement) |

## Générateur — justesse factuelle

Vérité-terrain établie à la main sur les 5 questions, indépendamment du
verdict du juge.

| Modèle | Taille | Correct / 5 |
|---|---|---|
| `llama3.2:3b` | 3B | 1 (refuse plutôt que d'inventer) |
| `qwen2.5:3b` | 3B | 2 |
| `phi3:3.8b` | 3.8B | 3 |
| `mistral:7b` | 7B | 2 |
| `qwen2.5:7b` | 7B | 2 |
| `qwen3:8b` | 8B | 1 |
| `llama3.1:8b` | 8B | 3 |
| `deepseek-r1:8b` | 8B | 2 |
| `gemma2:9b` | 9B | 3 |
| `qwen2.5:14b` | 14B | 2 |
| `phi3:14b` | 14B | 3 |

Aucun modèle ne dépasse 3/5, y compris à 14B — pas de tendance monotone avec
la taille (`qwen3:8b` fait pire que `qwen2.5:3b` ; les 14B ne battent pas les
8-9B). Les 2 questions systématiquement ratées portent sur des faits rares
("longue traîne" — année d'ouverture d'un centre commercial, nom d'un
responsable de candidature sportive peu connu) : chaque modèle y invente une
réponse différente et confiante plutôt que d'exprimer une incertitude.
`llama3.2:3b` est le seul à refuser plutôt qu'inventer, ce qui limite ses
erreurs en valeur absolue sans le rendre plus juste.

## Juge — fiabilité

Vérifié sur les 5 réponses de `llama3.1:8b` (vérité-terrain connue :
TRUE, TRUE, FALSE, TRUE, FALSE), puis élargi à 30 verdicts (6 générateurs ×
5 questions) pour `llama3.1:8b` comme juge.

| Modèle | Taille | Score |
|---|---|---|
| `llama3.2:3b` | 3B | 3/5 — répond TRUE par défaut, aucune discrimination |
| `qwen2.5:3b` | 3B | 4/5 — un faux négatif sur une réponse pourtant correcte |
| `phi3:3.8b` | 3.8B | 4/5 |
| `mistral:7b` | 7B | 4/5 |
| `gemma2:9b` | 9B | 4/5 |
| `qwen2.5:14b` | 14B | 4/5 |
| `llama3.1:8b` | 8B | 5/5 sur l'échantillon initial, 26/30 (~87%) sur l'échantillon élargi |
| `qwen2.5:7b` | 7B | 5/5 |
| `qwen3:8b` | 8B | 5/5 |
| `deepseek-r1:8b` | 8B | 5/5 |
| `phi3:14b` | 14B | 5/5 |

`llama3.2:3b` est le seul juge franchement inutilisable — il valide TRUE
quasi systématiquement, y compris des refus explicites du générateur
("je n'ai pas trouvé d'information..."). Tous les modèles ≥3.8B franchissent
un palier net. Défaut récurrent observé même chez les bons juges : ne pas
pénaliser un refus/non-réponse comme FALSE (le confondre avec un TRUE par
absence de contradiction explicite), et se faire piéger par une réponse
auto-contradictoire ("No, ... ne sont pas des documentaires" suivi d'une
description qui en confirme un comme documentaire).

## Latence

Mesurée à chaud (modèle déjà chargé), `llama3.2:3b` vs `llama3.1:8b`,
10 appels par rôle :

| Rôle | `llama3.2:3b` | `llama3.1:8b` |
|---|---|---|
| Générateur (3-5 phrases) | 0.63s moyenne | 0.79s moyenne |
| Juge (1 mot) | 0.05s moyenne | 0.08s moyenne |

Le rôle compte plus que la taille du modèle — juger (sortie ~1 token) est
~10× plus rapide que générer, quelle que soit la taille testée ici (3B-8B).
Le juge à 8B ne coûte donc quasiment rien en pratique par rapport au 3B.

## Décisions découlant de ces résultats

- Prompt du juge passé en anglais (le dataset l'est), avec chaque champ
  entre guillemets — un prompt mêlant français et contenu anglais, ou
  juxtaposant une référence correcte très courte à une référence incorrecte
  reformulée en phrase complète, dégradait fortement la fiabilité du juge
  (cf. [`judge.py`](../../berlue/evaluation/judge.py)).
- `_parse_verdict` ne lit que la première ligne de la réponse — un modèle
  qui ignore la consigne "un seul mot" peut continuer à générer après sa
  réponse et halluciner un second échange contenant le mot TRUE, ce qui
  inversait un FALSE réellement répondu (observé avec `phi3:14b`).
- `JUDGE_MODEL` (`params.py`) reste à évaluer entre `llama3.1:8b` et les
  autres candidats à 5/5 sur cet échantillon — décision à confirmer sur un
  échantillon plus large avant de changer le défaut en production.
