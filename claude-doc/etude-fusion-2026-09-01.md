# Fusion RAG + SelfCheck — étude de l'existant

Analyse du comportement actuel de `berlue/pipeline/fusion.py` et de l'intention des
développeurs, reconstituée depuis l'historique git. Document de constat : il ne
propose rien, il décrit.

La correction proposée fait l'objet d'un document distinct :
[`specification-fusion-2026-09-02.md`](specification-fusion-2026-09-02.md).

Couvre quatre défauts : la cohérence SelfCheck traitée comme une probabilité de
vérité, les pannes indiscernables d'une prédiction, la confiance qui mesure autre
chose que la confiance, et les poids de fusion que personne ne lit.

---

# 1. Ce que fait le code aujourd'hui

`berlue/pipeline/fusion.py`, fonction `do_fusion`.

## 1.1 Le fonctionnement actuel

Le pipeline calcule d'abord `coherence = 1 - divergence_selfcheck` (0.5 si SelfCheck
est absent), puis applique trois branches :

| cas RAG | verdict | confiance |
|---|---|---|
| `FEVER_CONFIRMS` | VALIDÉ | `0.7 * confiance_rag + 0.3 * coherence` |
| `FEVER_REFUTES` | CONTREDIT | `confiance_rag`, **+0.05** si `coherence > 0.7` |
| `LIKELY_*` / `I_DONT_KNOWN` | seuils sur un score combiné | dérivée du score |

Le score combiné de la troisième branche :

```
rag_belief = 0.5 + 0.5*conf   si LIKELY_TRUE
             0.5 - 0.5*conf   si LIKELY_FALSE
             0.5              si I_DONT_KNOWN

score = rag_belief * 0.5 + coherence * 0.5

score < 0.40 -> CONTREDIT (confiance = 1 - score)
score > 0.60 -> VALIDÉ    (confiance = score)
sinon        -> INDÉCIS   (confiance = 1 - 2*|score - 0.5|)
```

Deux cas particuliers : si SelfCheck est absent, `score = 0.5 + (rag_belief - 0.5) * 0.7` ;
si SelfCheck est absent **et** que le RAG dit `I_DONT_KNOWN`, le verdict est INDÉCIS
avec une confiance forfaitaire de 0.3.

**Il n'existe aucune notion de panne.** Un composant qui échoue produit un verdict
d'apparence normale.

## 1.2 Les quatre comportements problématiques, mesurés

Mesures faites en exécutant le vrai `do_fusion`, sans le modifier.

**a) `CONTREDIT` est mathématiquement inatteignable dès que le LLM est cohérent.**
Si `coherence >= 0.8`, alors `score = 0.4 + rag_belief*0.5 >= 0.4`, donc jamais sous
le seuil de 0.40 — **quelle que soit la confiance du RAG**. Balayage sur le pire cas
(`LIKELY_FALSE` à confiance 1.0, divergences de 0.00 à 0.20) : aucune valeur ne donne
CONTREDIT. Symétriquement, `coherence <= 0.2` rend `VALIDÉ` inatteignable.

**b) Une hallucination stable est validée sans aucune preuve.**
`I_DONT_KNOWN` (le RAG n'a rien) + divergence 0.05 (le LLM est très stable) ressort en
**VALIDÉ, confiance 0.72**. C'est exactement le cas d'usage que le projet existe pour
attraper.

**c) Une preuve FEVER est polluée par SelfCheck.**
`FEVER_CONFIRMS` à confiance 0.95 ressort à **0.95** si le LLM est cohérent, mais à
**0.71** s'il ne l'est pas — alors que la base a tranché et que la stabilité du modèle
qui a répondu n'a aucune pertinence sur la véracité du fait.

**d) « Aucune information nulle part » ressort avec une confiance de 1.00.**
La formule `1 - 2*|score - 0.5|` mesure la centralité du score, pas la confiance dans
le verdict. C'est ce champ qui alimente `fusion_score` dans l'API, l'UI, Firestore et
BigQuery : les valeurs ne sont pas comparables d'une branche à l'autre.

---

# 2. Ce que les développeurs cherchaient à faire

L'historique de `do_fusion` montre **quatre versions successives**. Elles convergent
toutes vers la même idée, et la dernière la perd par accident.

### V1 — `43b4c29`, 29 août, Lionel Bos

Un arbre de décision : **le RAG décide du verdict, SelfCheck ne module que la
confiance.** Quand le RAG n'a rien :

```python
if coherence < 0.5:
    final_verdict = Verdict.CONTRADICTED      # le LLM se contredit
else:
    final_verdict = Verdict.NOT_ENOUGH_INFO   # cohérent, mais zéro preuve
```

**Jamais `SUPPORTED`.** L'asymétrie est là dès le premier jour : la cohérence seule ne
valide rien.

### V2 — `6f3dd90`, 1er sept., Lionel Bos

Étend l'arbre aux 5 catégories `RagJudgment`, et pousse l'idée plus loin : pour
`LIKELY_FALSE`, le terme SelfCheck est **retourné** —
`final_conf = conf_rag * w + (1 - coherence) * w_sc` — avec le commentaire
« une faible cohérence renforce l'idée que c'est faux ». C'est le principe du
« même sens », déjà présent.

### V3 — `e3c83eb`, 1er sept., Maxime d'ERSU

La version **la plus prudente des quatre**. Introduit `llm_self_consistent` et un
seuil de cohérence explicite, et surtout force `LIKELY_TRUE` à ne jamais produire un
VALIDÉ, avec le commentaire dans le code :

```python
final_verdict = Verdict.NOT_ENOUGH_INFO  # jamais SUPPORTED sans preuve en base
```

et, sur la branche FEVER_REFUTES :

```python
# LLM confiant à tort = signal d'hallucination supplémentaire, jamais un facteur d'atténuation
```

Cette phrase est la formulation exacte du principe que la présente spec reprend.

### V4 — `6d6868d`, 1er sept., Maxime d'ERSU — « changement de label_verdict »

C'est la version actuelle, et **c'est là qu'est la régression**. Le diff retire
`llm_self_consistent`, retire le garde-fou « jamais SUPPORTED sans preuve en base », et
remplace l'arbre de décision par le score pondéré **symétrique** :

```python
score = (rag_belief * weight_rag_unproven) + (coherence * weight_selfcheck_unproven)
```

## 2.1 Où ça a dérapé, et pourquoi ce n'est reprochable à personne

Le message de commit est « changement de label_verdict ». Le but visible était de
faire passer le code aux nouveaux libellés `RagJudgment` — **pas** de changer la
logique de décision. Le passage au score pondéré semble être un dommage collatéral de
ce renommage : personne n'a décidé de valider les hallucinations stables, c'est tombé
d'un refactor.

Et V4 apportait deux vraies améliorations, qu'il faut garder :

1. **La confiance du RAG entre enfin dans la direction du verdict.** En V1-V3, un
   `LIKELY_FALSE` à confiance 0.1 tranchait aussi durement qu'à 1.0.
2. **Une zone d'indécision existe pour les `LIKELY_*`.** En V1-V3, tout était forcé
   vers VALIDÉ ou CONTREDIT, sans milieu.

**La spécification qui en découle ne réinvente donc rien : elle restaure l'asymétrie de V1-V3 et
garde la gradation de V4.**

---

---

# 3. Les défauts liés à ce refactor

## 3.1 Ce que la correction ferme complètement

| défaut | comment |
|---|---|
| la cohérence SelfCheck traitée comme une probabilité de vérité | objet même du refactor : l'asymétrie est restaurée, `CONTREDIT` redevient atteignable |
| `final_conf` mesure la centralité, pas la confiance | la confiance devient la confiance *dans le verdict rendu*, `0.00` pour un INDÉCIS |
| prints de debug dans `fusion.py` | les trois disparaissent avec la réécriture |
| poids de fusion câblés nulle part | `FUSION_WEIGHT_RAG` enfin lu depuis `params.py`, et tous les seuils y sont déclarés |

Deux défauts mineurs suivent :

- la branche `else` qui laissait `evidence` à `None` devient une **décision assumée**
  (seule une preuve FEVER porte une `evidence`) au lieu d'un oubli ;
- `do_fusion` devient **idempotente** — mais `evaluate_selfcheck` et `evaluate_rag`
  continuent d'`append` sans vider, donc celui-ci n'est réglé qu'au tiers.

## 3.2 Défini ici, mais à détecter ailleurs — les pannes

La spécification **définit** l'état de panne (règle R1 : quel que soit le composant en
panne, aucun verdict, la question est à rejouer). La **détection**, elle, reste
entièrement à faire, et pas dans `fusion.py` :

- le `except Exception` de `rag/retriever.py:163` avale les `TimeoutError` et
  `RuntimeError` levés par `OllamaClient.generate` ;
- le `ValueError` de `compute_divergence` n'est rattrapé nulle part.

Tant que ces erreurs ne remontent pas, `result.panne` ne sera jamais renseigné et la
règle R1 ne se déclenchera jamais. **La détection des pannes n'est donc pas réglée par
ce refactor, elle est seulement rendue possible.**

## 3.3 Prérequis — sans la levée de la garde du retriever, deux règles sur cinq sont mortes

C'est la dépendance la plus importante, et elle n'est pas évidente à la lecture.

`rag/retriever.py:133-141` force `verdict = "NOT ENOUGH INFO"` et `confidence = 0.0`
dès que `used_evidence_index` vaut `null`. Or `prompts/rag.py:26` **impose** `null`
pour `LIKELY_TRUE`, `LIKELY_FALSE` et `I_DONT_KNOW`.

Donc chaque fois que le modèle **respecte** la consigne, la fusion reçoit
`I_DONT_KNOWN` avec une confiance de `0.0`. Ce qui donne :

```
rag_belief = 0.5   ->   toujours dans la bande neutre [0.40, 0.60]   ->   toujours R3
```

Les règles **R4** (accord) et **R5** (arbitrage pondéré) ne se déclencheraient
quasiment jamais, et le verdict final serait décidé par SelfCheck seul, aux extrêmes.
Autrement dit : réécrire la fusion sans lever cette garde donne un système correct sur
le papier dont **deux règles sur cinq sont mortes en production**.

Lever cette garde est donc un prérequis, pas une étape suivante. Le correctif est petit :
elle ne doit annuler que `final_evidence`, pas le verdict — sauf pour `FEVER_CONFIRMS` et
`FEVER_REFUTES`, qui exigent une preuve citée. Un défaut voisin vit dans les trois mêmes
lignes de `verify_claim` : les retours anticipés y sont typés `Verdict` au lieu de
`RagJudgment`, deux énumérations qui ne sont jamais égales.

## 3.4 Dettes induites par le refactor

Ajouter une valeur de verdict `PANNE` n'est pas neutre. Deux conséquences obligatoires,
sans lesquelles le refactor **aggrave** le problème des pannes au lieu de l'améliorer :

- `evaluation/metrics.py` doit **exclure** les lignes en panne de la matrice de
  confusion. Une nouvelle valeur de verdict comptée silencieusement comme une
  prédiction serait exactement le problème qu'on cherche à supprimer.
- `api/schemas.py` : le `status` green/orange/red a besoin d'une quatrième valeur, et
  le mapping verdict → couleur est dupliqué entre `api/service.py` et
  `evaluation/berlue_pipeline.py` — les deux doivent bouger ensemble.

---

# 4. Ce qu'il faut en retenir

Quatre versions, une intention constante — **la cohérence interne du modèle ne vaut
pas une preuve** — et une régression introduite sans intention par un commit dont le
but affiché était un renommage.

La spécification reprend cette intention d'origine et lui ajoute ce que V4 avait
apporté de bon. Voir
[`specification-fusion-2026-09-02.md`](specification-fusion-2026-09-02.md).

Périmètre réaliste du chantier : **la réécriture de la fusion, la levée de la garde du
retriever et le typage de ses retours anticipés, ensemble** — ils partagent le même flux
de données. Ça règle au passage la confiance, les prints de debug et les poids non
câblés, et rend les pannes détectables.
