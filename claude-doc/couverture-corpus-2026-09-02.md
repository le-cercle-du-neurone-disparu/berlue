# Couverture du corpus FEVER pour halueval et truthfulqa

**Conclusion : le RAG inversé ne résoudra pas les problèmes mesurés sur halueval et
truthfulqa. FEVER ne couvre que 2,0 % des affirmations du premier et 5,5 % du second.**

Ce document mesure ce que le RAG a matériellement à sa disposition quand on l'évalue
sur ces deux datasets. Il ne juge ni le code du RAG ni la fusion — il constate que la
matière est absente, et que toute optimisation en aval de ce constat porte sur les 2 %.

---

## 1. Méthode

Mesurer une distance de récupération sans point de comparaison ne dit rien : « 0,87 »
n'est ni bon ni mauvais dans l'absolu. Il faut un **témoin**.

Le corpus FEVER contient 145 449 affirmations, dont **35 639 étiquetées
`NOT ENOUGH INFO`**. `indexer.build_index` ne garde que `SUPPORTS` et `REFUTES`, soit
109 810 vecteurs — exactement la taille de l'index en place. Les `NOT ENOUGH INFO`
sont donc des affirmations **du même corpus, du même domaine, de la même rédaction,
mais absentes de l'index**.

C'est le témoin idéal : leur distance de récupération définit ce que « FEVER couvre ce
sujet » veut dire numériquement.

| groupe | contenu | n |
|---|---|---|
| **Témoin** | affirmations FEVER `NOT ENOUGH INFO`, hors index | 200 |
| **halueval** | affirmations réellement extraites par le pipeline (cache `eval_signals`) | 200 |
| **truthfulqa** | affirmations extraites par le même extracteur (`qwen2.5:7b`) | 73 |

Même embedding (`all-mpnet-base-v2`), même index FAISS, distance au plus proche voisin.

## 2. Résultat

| groupe | n | min | q25 | **médiane** | q75 | max |
|---|---|---|---|---|---|---|
| **Témoin — FEVER hors index** | 200 | 0,00 | 0,17 | **0,31** | 0,44 | 0,78 |
| **halueval** | 200 | 0,07 | 0,74 | **0,87** | 0,97 | 1,28 |
| **truthfulqa** | 73 | 0,18 | 0,71 | **0,92** | 1,05 | 1,24 |

En prenant pour seuil de « couvert par FEVER » le q75 du témoin, soit **0,44** :

| groupe | affirmations couvertes |
|---|---|
| Témoin | 75,0 % *(par construction)* |
| **halueval** | **2,0 %** |
| **truthfulqa** | **5,5 %** |

Une affirmation de halueval est en moyenne **près de trois fois plus loin** de l'index
qu'une affirmation du domaine de FEVER. Ce n'est ni un problème de `top_k`, ni de
modèle d'embedding, ni de seuil : la matière n'est pas dans la base.

## 3. Confirmation par le comportement du pipeline

La mesure ci-dessus prédit ce qu'on observe en conditions réelles, sans l'avoir cherché :

- sur un run complet de 300 lignes halueval, **1 seule affirmation sur 346** a produit
  un verdict `FEVER_REFUTES`, et **aucune** un `FEVER_CONFIRMS` ;
- la règle R2 de la fusion — la branche « preuve », celle qui donne le fondement
  `PREUVE_FEVER` — se déclenche donc dans **0,3 %** des cas ;
- recherche littérale de « Anubis » dans les 145 449 entrées du corpus : **0 occurrence**,
  pour une question dont c'est le sujet central.

## 4. Ce que le RAG fait à la place

N'ayant rien de pertinent, `retrieve()` renvoie quand même ses `top_k` plus proches
voisins : `retrieve()` n'applique **aucun seuil de distance**, il rend toujours les plus
proches quels qu'ils soient. Le prompt reçoit
donc des extraits hors sujet, présentés comme la « FEVER KNOWLEDGE BASE ».

Exemple relevé, sur l'affirmation *« The Dutch-Belgian television series that 'House of
Anubis' was based on first aired in 2003 »* :

```
[0] dist 1.03  SUPPORTS  House of 1000 Corpses had a theatrical release in 2003.
[1] dist 1.06  REFUTES   Game of Thrones (season 3) was only broadcast in France.
[2] dist 1.06  SUPPORTS  2003 was the year when the House of 1000 Corpses had a...
```

Le modèle se rabat alors sur sa connaissance interne — et on a mesuré qu'il y
**acquiesce au lieu de vérifier** : sur 8 affirmations soumises avec leur version
contredite (année décalée), **5 reçoivent le même verdict**, à 0,95–0,99 de confiance
dans les deux cas.

## 5. Conséquences

**Le seuil de pertinence à ajouter à `retrieve()` a maintenant une valeur défendable :
0,44**, issue du témoin et non d'un réglage au jugé. Appliqué, il ferait dire au pipeline « rien en
base » dans 98 % des cas sur halueval — ce qui est la vérité, au lieu d'injecter des
extraits trompeurs.

**Mais il faut voir ce que ça implique** : avec ce seuil, le RAG inversé ne contribue
plus à 98 % des verdicts. Le produit devient un vérificateur par **connaissance interne
du modèle**, et c'est alors le prompt RAG — pas la base — qui est le cœur du système.

**Trois orientations possibles, à trancher en équipe :**

1. **Changer de corpus de preuves** pour un corpus qui couvre le domaine des questions
   évaluées. FEVER vérifie des phrases Wikipédia isolées ; halueval pose des questions
   multi-sauts. Ce sont deux espaces de faits différents.
2. **Changer de dataset d'évaluation** pour un jeu dont les affirmations tombent dans le
   domaine de FEVER — ce qui mesurerait le RAG dans les conditions où il peut fonctionner.
3. **Assumer le repli sur la connaissance interne** comme étant le produit, et alors
   investir sur le prompt RAG et sur une sortie contrainte par schéma JSON plutôt que sur
   la base.

Ce qu'il ne faut pas faire, c'est continuer à régler la fusion : une calibration par
descente par coordonnées sur six paramètres a produit un gain de **+0,0 point** en
validation, précisément parce qu'il n'y a pas de signal à mieux pondérer.

---

# Annexe — halueval et truthfulqa se couvrent-ils l'un l'autre ?

Question posée après le constat ci-dessus : à défaut de FEVER, l'un des deux datasets
pourrait-il servir de base de preuves à l'autre ?

**Réponse : non.** Chacun couvre l'autre environ deux fois moins bien qu'il ne se
couvre lui-même.

## A.1 Précaution indispensable : la taille de l'index domine la distance

Une distance au plus proche voisin dépend d'abord du nombre de vecteurs dans l'index.
Vérifié en rejouant le témoin FEVER sur des index de tailles décroissantes, **données
et embedding identiques, seule la taille change** :

| taille de l'index | q25 | médiane | q75 |
|---|---|---|---|
| 174 | 1,03 | **1,18** | 1,31 |
| 1 000 | 0,81 | 0,98 | 1,08 |
| 10 000 | 0,42 | 0,59 | 0,74 |
| 109 810 (index réel) | 0,17 | **0,31** | 0,44 |

Les mêmes affirmations passent de 0,31 à 1,18 de médiane. **Les chiffres de cette
annexe ne sont donc pas comparables à ceux de la partie 2** : les index y font 174 et
144 vecteurs, contre 109 810 pour FEVER. Seule la comparaison témoin / autre dataset,
faite sur le même index, est interprétable.

## A.2 Protocole

Pour chaque direction : l'index est bâti sur la moitié des questions du dataset source,
et interrogé par (a) l'autre moitié — le témoin — et (b) le dataset cible, avec le même
nombre de requêtes. Le découpage se fait **par question et jamais par affirmation** :
les réponses vraie et fausse d'une même question produisent des affirmations quasi
identiques, qui fuiteraient d'un côté à l'autre et gonfleraient le témoin.

Matière : 346 affirmations halueval (150 questions), 269 affirmations truthfulqa
(205 questions), extraites par le même extracteur que les runs (`qwen2.5:7b`).

## A.3 Résultat

**Index bâti sur halueval (174 affirmations)**

| requêtes | n | q25 | médiane | q75 | sous le seuil |
|---|---|---|---|---|---|
| **Témoin** — halueval, moitié non indexée | 172 | 1,16 | 1,29 | 1,43 | 75,0 % |
| **truthfulqa** | 172 | 1,36 | 1,49 | 1,59 | **41,3 %** |

**Index bâti sur truthfulqa (144 affirmations)**

| requêtes | n | q25 | médiane | q75 | sous le seuil |
|---|---|---|---|---|---|
| **Témoin** — truthfulqa, moitié non indexée | 125 | 1,09 | 1,25 | 1,39 | 75,2 % |
| **halueval** | 125 | 1,34 | 1,43 | 1,53 | **34,4 %** |

*(seuil = q75 du témoin de chaque panneau, donc 75 % par construction pour le témoin)*

## A.4 Lecture

Le recoupement est **environ deux fois plus faible que le témoin** dans les deux sens
(41,3 % et 34,4 % contre 75 %). Aucun des deux datasets ne peut servir de base de
preuves à l'autre.

Et un constat plus fondamental apparaît en passant : à taille d'index égale, le témoin
*interne* de halueval (1,29) est déjà un peu moins bon que celui de FEVER (1,18). Ces
deux datasets sont des jeux de questions-réponses portant chacune sur un sujet
différent — ils n'ont quasiment aucune redondance interne à exploiter. **Ce ne sont pas
des corpus de preuves, et aucun aménagement n'en fera.**

La recherche d'un corpus couvrant réellement le domaine des questions évaluées reste
donc entière.
