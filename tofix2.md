# tofix2 — points restants

Reprise de l'audit initial après le refacto de la fusion, la campagne de mesures, l'analyse
manuelle de 30 exemples et une série de correctifs. **Ne contient que ce qui reste à faire** :
tout ce qui est corrigé a été retiré (récapitulatif en fin de document).

**Deux listes séparées, selon l'origine du point :**

- **Partie A — `AEx.`** : issus de l'**analyse manuelle des 30 exemples**
  (cf. `claude-doc/analyses/v1/analyse-pipeline.md`). Ce sont des défauts de conception des
  prompts et de la fusion, constatés trace à l'appui.
- **Partie B — `1.`, `2.`…** : reliquat de l'audit initial, ou défauts rencontrés en
  exploitation.

Dans chaque liste, l'ordre suit l'impact mesuré, et le niveau de priorité (`P0` à `P4`) est
indiqué sur chaque point pour qu'il reste comparable d'une liste à l'autre. Chaque point porte
la mesure qui le justifie.

---

# Partie A — issus de l'analyse des 30 exemples

## AEx1. [ ] *P0* — L'extraction perd la fausseté de la réponse

`berlue/prompts/extraction.py`, règle *CORE SYNTHESIS*

Sur 15 réponses fausses analysées, **4 voient leur fausseté disparaître à l'extraction** :

| réponse fausse | affirmation extraite |
|---|---|
| *Hot Rod was founded earlier.* | `Cooking Light was founded in 1987.` — tirée de la **question** |
| *Patrick Brontë was **born** in England.* | `...**spent most of his adult life** in England.` — **réécrite** en fait vrai |
| *No, **only** Patrick White was an author.* | `Patrick White was a writer.` — le `only` supprimé |
| *Disha Patani has **only** appeared in Hindi films.* | idem |

Le pipeline évalue alors une affirmation vraie et conclut « vraie » sur une réponse fausse.
**C'est la moitié des erreurs franches de l'échantillon**, et aucun étage en aval ne peut les
rattraper.

Cause : *CORE SYNTHESIS* s'applique au-delà de son domaine. Elle doit ne valoir que si la
réponse ne contient **aucune** affirmation propre (`yes`, `no`, un nom seul) — sinon elle écrase
la réponse avec la prémisse de la question, en violation de l'interdiction figurant trois lignes
plus haut dans le même prompt (« NEVER extract or repeat the `<question>` »).

À ajouter au prompt : ne jamais substituer le prédicat de la question à celui de la réponse ;
conserver les quantificateurs (`only`, `both`, `never`, `still`) ou produire la négation
correspondante ; traiter la négation d'une question « Do both A and B… ? » ; un fait vérifiable
par affirmation.

## AEx2. [ ] *P0* — Le RAG acquiesce au lieu de vérifier

`berlue/prompts/rag.py`

Démontré par paires, sur la même question posée avec sa réponse vraie et sa réponse fausse :

| affirmation A | verdict | affirmation B *(incompatible)* | verdict |
|---|---|---|---|
| série diffusée en **2006** | `LIKELY_TRUE 0,95` | diffusée en **2003** | `LIKELY_TRUE 0,95` |
| écrit pour **Make** | `LIKELY_TRUE 0,95` | écrit pour **Popular Science** | `LIKELY_TRUE 0,99` |

Il confirme les deux, et avec *plus* d'assurance sur la fausse dans le second cas. Distribution
sur 33 verdicts d'un jeu équilibré 50/50 : **63,6 % de `LIKELY_TRUE`** contre 15,2 % de
`LIKELY_FALSE`.

Le prompt présente l'affirmation puis demande de la juger : le modèle l'ancre et la confirme.
Correctif : **lui faire énoncer le fait avant de lui montrer l'affirmation**. Un modèle qui doit
produire « 2006 » avant de voir « 2003 » ne peut plus valider les deux.

## AEx3. [ ] *P0* — Un `I_DONT_KNOW` du RAG laisse SelfCheck trancher seul

`berlue/pipeline/fusion.py`, règle R3

Quand le RAG répond honnêtement « je ne sais pas », `rag_belief` vaut 0,5 : on tombe dans la
bande neutre et SelfCheck décide seul, jusqu'à produire un verdict tranché.

Relevé sur les 30 exemples : **faux** deux fois (`CONTREDIT 0,79` et `SUPPORTED 0,77` sur des
réponses mal classées), **juste par accident** deux fois, et à **0,01 du seuil** une fois.

C'est le comportement le plus perturbant de l'analyse : **l'étage qui se comporte bien est
neutralisé, celui qui se trompe décide.** Un `I_DONT_KNOW` du RAG devrait plafonner le verdict
final à `INDÉCIS` plutôt que d'autoriser un `CONTREDIT` à 0,79.

## AEx4. [ ] *P1* — Le verdict du RAG contredit son propre raisonnement

`berlue/prompts/rag.py`, `berlue/llm/client.py`

Forme type, récurrente : « the claim **cannot be definitively confirmed or refuted** » suivi de
`LIKELY_TRUE 0.95`. Un cas annonce même `FEVER_REFUTES` — donc que la base tranche — sans citer
aucun extrait, alors que son raisonnement invoque la connaissance interne.

`ollama` accepte `format=<schéma JSON>` : le verdict serait contraint aux cinq valeurs et le
décodage garanti. Ne règle pas l'incohérence sémantique, mais supprime les valeurs hors
nomenclature et le parsing à la regex.

## AEx5. [ ] *P3* — Les exemples few-shot du prompt RAG contaminent la sortie

Un raisonnement portant sur *Titus Andronicus* mentionnait « the exact number of **blueberries
eaten by a random individual** » — recopié du 5ᵉ exemple du prompt.

---

# Partie B — audit initial et exploitation

## 1. [ ] *P0* — En mode dataset, SelfCheck échantillonne le mauvais modèle

`evaluation/run_eval.py` / `evaluation/berlue_pipeline.py`

La réponse vient du dataset, les échantillons d'un modèle qui ne l'a jamais produite : la
prémisse de SelfCheckGPT est violée.

Mesuré : sur la même question, divergence **1,00 pour la réponse vraie comme pour la fausse** —
pouvoir discriminant nul. Avec `llama3.2:1b`, la divergence médiane est de **0,95** sur
l'ensemble d'un run : une aiguille bloquée.

Deux issues : assumer que c'est une **sonde de connaissance** (et alors le modèle
d'échantillonnage est le levier — le passage `1b` → `3b` fait passer la médiane de 0,95 à 0,51),
ou retirer SelfCheck de ce mode.

## 2. [ ] *P1* — Aucun seuil de pertinence sur les extraits injectés

`berlue/rag/retriever.py`, `retrieve()`

`retrieve()` rend toujours les `top_k` plus proches voisins, quelle que soit la distance. Le
prompt reçoit donc des extraits hors sujet présentés comme la « FEVER KNOWLEDGE BASE » —
*House of 1000 Corpses* pour une série néerlandaise, le *quinoa* pour une question de botanique,
*Manchester City* pour Westfield Culver City.

**Le seuil est chiffré : 0,44**, issu du q75 d'un témoin (les affirmations FEVER hors index).
Ce n'est plus un réglage au jugé.

**Reproduit en test** : `tests/test_rag.py::test_verify_claim_ne_fabrique_pas_de_preuve_sur_une_
affirmation_hors_corpus` est marqué `xfail` non strict pour ce motif. Sur l'affirmation charabia
`Xyzzy qwerty plugh…`, le retriever a cité « Alphabet works in different fields » — distance
**1,21**, contre ~0,2 pour un vrai appariement — comme preuve d'un `FEVER_CONFIRMS` à confiance
**1,0**. Le test doit redevenir vert une fois le seuil posé.

**Décision préalable** : appliqué à halueval, il ferait dire « rien en base » dans 98 % des cas.
C'est la vérité, mais ça revient à assumer que le RAG inversé ne contribue quasiment plus —
cf. `claude-doc/couverture-corpus-2026-09-02.md`.

## 3. [ ] *P1* — Les pannes restent indétectables

`rag/retriever.py` (`except Exception`), `selfcheck/scorer.py`

L'état `PANNE` existe dans le contrat et la fusion le traite, mais **rien ne le renseigne** : le
`except Exception` avale toujours les `TimeoutError` et `RuntimeError`, et le `ValueError` de
`compute_divergence` n'est rattrapé nulle part. Tant que ces erreurs ne remontent pas, la règle
correspondante ne se déclenchera jamais.

À trancher : quelles erreurs sont des pannes d'infrastructure (à faire remonter) et lesquelles
sont des erreurs de contenu (à rattraper localement).

## 4. [ ] *P1* — Deux appels identiques à température 0 rendent des verdicts différents

**Mesuré** : sur 5 affirmations soumises 6 fois chacune au RAG, à température 0 et à contexte
identique, **1 sur 5 change de verdict** — `LIKELY_TRUE 0.75` cinq fois, `I_DONT_KNOW 0.0` une
fois. Les quatre autres sont parfaitement stables. L'instabilité est donc réelle mais pas
universelle : elle frappe les cas où le modèle hésite déjà.

Affecte toute mesure comparative, et s'ajoute au bruit de tirage : **deux runs du même code
donnent +6,7 et +10,0** de séparation, un écart de 3,3 points là où la documentation annonçait
±2.

`ollama` accepte une option `seed`, non utilisée aujourd'hui. La poser rendrait les runs
reproductibles — mais c'est un changement de comportement, donc à décider : les mesures
existantes ne seraient plus comparables aux nouvelles.

## 5. [ ] *P2* — `compute_divergence` lève une `ValueError` qui tue le run

`selfcheck/scorer.py`, non rattrapée. Une seule réponse vide d'Ollama fait tomber un run de
plusieurs milliers de questions. **Lié au point 4** : le traitement dépend du contrat de panne
retenu.

## 6. [ ] *P2* — SelfCheck compare une affirmation anglaise à des échantillons non anglais

Sans effet sur halueval (tout est anglais), mais le chemin est atteignable par l'API et la démo
CLI. À traiter avant toute calibration sur un jeu multilingue.

## 7. [ ] *P2* — Typo `sentenses` dans le prompt d'échantillonnage

`prompts/ollama.py` — correctif d'une ligne, **mais ce n'est pas cosmétique** : modifier ce
prompt change les échantillons, donc les divergences SelfCheck, donc la comparabilité avec les
runs de référence et la validité du cache de signaux. À appliquer au moment où l'on accepte de
rejouer la baseline, pas dans un lot de nettoyage.

---

# Hors périmètre correctif — une décision d'équipe

**FEVER ne couvre que 2,0 % des affirmations halueval et 5,5 % de truthfulqa** (mesure avec
témoin, cf. `claude-doc/couverture-corpus-2026-09-02.md`). Aucun des deux datasets ne couvre
l'autre non plus.

Ce n'est pas un point à corriger, c'est un choix à faire : changer de corpus de preuves, changer
de dataset d'évaluation, ou assumer que le produit vérifie par connaissance interne — et alors
c'est le prompt RAG (AEx2), pas la base, qui est le cœur du système.

---

# Déjà corrigé

Retiré de cette liste, conservé ici pour ne pas rouvrir ce qui est clos.

**Refacto de la fusion** — verdicts `LIKELY_*` écrasés par la garde du retriever · cohérence
SelfCheck traitée comme une probabilité de vérité · retours anticipés typés `Verdict` ·
`final_conf` mesurant la centralité · prints de debug · poids de fusion non câblés · `evidence`
absent de la branche `else` · `do_fusion` non idempotente · mapping verdict → couleur dupliqué ·
`tests/test_rag.py` rouge.

**Série de correctifs unitaires** — la purge effaçait des tables qu'aucun filtre ne visait ·
température du constructeur jamais lue · `retrieve()` acceptait l'index `-1` de FAISS · singleton
SelfCheckNLI sans verrou · sortie LLM inattendue arrêtant le run · `evaluate_selfcheck` et
`evaluate_rag` non idempotentes · `num_predict` fixé nulle part · options CLI rejetées · ligne RAG toujours identique ·
`if gt is True` · `Claim.id` non reproductible · `status` non contraint · indexation d'`evidence_url` sans garde · `similarity_score` recevant la
confiance du LLM · `FEVER_LABEL_TO_VERDICT` mal nommé.
