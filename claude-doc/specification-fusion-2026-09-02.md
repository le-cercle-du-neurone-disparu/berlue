# Fusion RAG + SelfCheck — spécification fonctionnelle

**Statut : à relire et valider. Aucune modification de code n'a été faite.**

Décrit ce que la fusion *doit* faire. Le code devra s'y conformer, pas l'inverse.

Le constat qui motive cette spécification — comportement actuel mesuré et intention
des développeurs reconstituée depuis git — fait l'objet d'un document distinct :
[`etude-fusion-2026-09-01.md`](etude-fusion-2026-09-01.md). Les renvois « point 1.2.x
de l'étude » pointent vers lui.

Ferme les points **3**, **9** et **20** de `tofix.md`, et définit l'état de panne du
point **7**.

---

# PARTIE 1 — Ce que la fusion doit faire

## 1.1 Ce que mesurent les deux signaux

| source | produit | mesure |
|---|---|---|
| RAG | un verdict parmi 5 + une confiance 0-1 | un jugement **sur le fait** : la base FEVER, ou à défaut la connaissance interne du modèle vérificateur |
| SelfCheck | un score de divergence 0-1 | un jugement **sur le comportement** du modèle qui a répondu : s'est-il contredit d'un échantillon à l'autre |

Tout le reste découle de cette distinction : **SelfCheck ne mesure pas la vérité, il
mesure la stabilité.**

### Pourquoi le signal SelfCheck est asymétrique

- **Divergence forte** — le modèle se contredit. Lecture principale : il ne sait pas.
- **Divergence faible** — le modèle est stable. Deux lectures possibles : soit il sait,
  soit il se trompe avec constance. **Une hallucination stable produit exactement la
  même signature qu'une connaissance solide.**

Une divergence faible ne discrimine donc rien, là où une divergence forte est
informative. D'où deux conséquences : SelfCheck **pèse plus quand il accuse que quand
il disculpe**, et il ne décide **seul** qu'aux valeurs extrêmes.

### Ce qu'une divergence forte ne prouve pas

Elle n'établit pas que l'affirmation est *fausse*, seulement qu'elle n'est pas
reproductible. Trois causes légitimes, vérifiées dans le code et le package :

1. **Le protocole fabrique de la variation.** Les K échantillons sont tirés à des
   températures étalées de 0.3 à 1.0 (`params.py`). Celui à 1.0 est *fait* pour diverger.
2. **Le NLI n'a pas de classe « neutre ».** `potsawee/deberta-v3-large-mnli` sort deux
   classes — le code du package le dit : *neutral is already removed* — et le score est
   `P(contradiction)`. Quand un échantillon ne *mentionne pas* le fait, le modèle est
   forcé de trancher entre confirme et contredit : une simple **omission** peut compter
   comme une contradiction partielle.
3. **Les questions à réponses multiples.** « Cite un film de X » : cinq réponses
   différentes, toutes vraies.

Ces causes produisent de la divergence **modérée**. Les seuils extrêmes de la règle R3
filtrent l'essentiel de ce bruit.

> ⚠️ **Risque résiduel** : le point 4 de `tofix.md` (affirmation en anglais comparée à
> des échantillons en français) produit une divergence qui est du bruit pur, et qui
> *peut* être extrême. À traiter **avant** toute calibration.

## 1.2 Preuve et conviction

Le verdict reste à **trois valeurs** (VALIDÉ / CONTREDIT / INDÉCIS) : la matrice de
confusion doit rester comparable à une vérité terrain vrai/faux, donc une conviction
« c'est faux » doit compter comme une prédiction « faux ». Réserver CONTREDIT aux seuls
cas FEVER reviendrait à ne plus mesurer que la couverture de la base.

Ce qui change, c'est qu'on ajoute à côté un **fondement** explicite :

| fondement | signification |
|---|---|
| `PREUVE_FEVER` | la base contient de quoi trancher. C'est une preuve. |
| `CONVICTION` | rien en base. Le verdict est une opinion argumentée, faillible. |
| `AUCUN` | rien à dire. |

L'éval lit le verdict, l'UI lit les deux. Aujourd'hui cette distinction existe déjà,
mais seulement de façon implicite : `evidence` n'est renseigné que dans les branches
FEVER, et rien ne documente ce champ comme portant cette signification.

## 1.3 Normalisation des deux signaux

Ramenés sur `[0, 1]`, neutres à `0.5` : 0 = franchement faux, 1 = franchement vrai.

```
rag_belief :  LIKELY_TRUE  -> 0.5 + 0.5 * confiance_rag
              LIKELY_FALSE -> 0.5 - 0.5 * confiance_rag
              I_DONT_KNOWN -> 0.5

d0 = FUSION_DIVERGENCE_NEUTRE

sc_belief  :  divergence <= d0 -> 0.5 + 0.5 * (d0 - divergence) / d0
              divergence >  d0 -> 0.5 - 0.5 * (divergence - d0) / (1 - d0)
```

Deux droites qui se rejoignent à `0.5` au point neutre `FUSION_DIVERGENCE_NEUTRE`. Avec `FUSION_DIVERGENCE_NEUTRE = 0.5` on
retombe sur `1 - divergence`, le comportement actuel : aucune régression cachée tant
que la calibration ne bouge pas ce paramètre.

## 1.4 Les cinq règles

| règle | condition | verdict | fondement |
|---|---|---|---|
| **R1** | RAG **ou** SelfCheck en panne | PANNE — aucun verdict | — |
| **R2** | RAG = `FEVER_CONFIRMS` / `FEVER_REFUTES` | VALIDÉ / CONTREDIT | `PREUVE_FEVER` |
| **R3** | `rag_belief` dans la bande neutre `[0.40, 0.60]` | SelfCheck décide **seul, aux extrêmes** | `CONVICTION` ou `AUCUN` |
| **R4** | RAG conclut, SelfCheck **du même sens** | le sens commun, acquis sans arbitrage | `CONVICTION` |
| **R5** | RAG conclut, SelfCheck **du sens opposé** ou neutre | seuils sur le score arbitré | `CONVICTION` |

### R1 — panne

Une panne n'est **pas** un « je ne sais pas ». `I_DONT_KNOWN` est une réponse légitime
du RAG et reste traitée par R3 ; la panne, c'est un composant qui a échoué (timeout
Ollama, service down, erreur non récupérable).

**Quel que soit le composant en panne, la réponse entière est en panne** : aucun
verdict n'est rendu pour aucune affirmation, et la question doit être **rejouée** pour
obtenir un résultat complet. Ces lignes doivent être **exclues** de la matrice de
confusion, jamais comptées comme des prédictions — c'est le fond du point 7, où une
panne d'infrastructure remplit aujourd'hui la matrice de faux `NOT_ENOUGH_INFO`
indiscernables de vraies prédictions.

### R2 — FEVER a tranché

La base prime. **SelfCheck n'entre ni dans le verdict, ni dans la confiance.** La
confiance rendue est celle du RAG, telle quelle. Corrige le point 1.2.c de l'étude.

### R3 — le RAG ne conclut pas

S'applique quand `rag_belief` tombe dans la bande neutre : soit `I_DONT_KNOWN`, soit
une conviction trop faible pour être exploitable (un `LIKELY_TRUE` à confiance 0.15
donne `rag_belief = 0.575` — il n'est pas plus concluant qu'un « je ne sais pas »).

SelfCheck décide alors seul, **mais uniquement si son signal est franc** :

```
sc_belief > FUSION_SELFCHECK_SEUIL_HAUT (0.80)  -> VALIDÉ,    fondement CONVICTION
sc_belief < FUSION_SELFCHECK_SEUIL_BAS  (0.20)  -> CONTREDIT, fondement CONVICTION
sinon                                           -> INDÉCIS,   fondement AUCUN
```

La confiance est **décotée** : `0.5 + |sc_belief - 0.5| * FUSION_DECOTE_SIGNAL_SEUL`. Sans cette décote,
une conviction issue d'un seul signal ressortait *plus* confiante qu'une conviction
corroborée par le RAG — et la confiance finale *baissait* quand le RAG devenait plus
convaincu (mesuré : 0.90 à `conf_rag = 0.20`, puis 0.72 à `conf_rag = 0.21`). La
décote ne change **que** le nombre rapporté, jamais le verdict.

### R4 — accord

Le RAG conclut et SelfCheck va dans le même sens : verdict acquis sans arbitrage. Deux
signaux indépendants qui concordent valent mieux que l'un des deux seul.

### R5 — désaccord

Moyenne pondérée, puis seuils :

```
w_sc = FUSION_WEIGHT_SELFCHECK_CHARGE     si sc_belief < 0.5   (SelfCheck accuse)
       FUSION_WEIGHT_SELFCHECK_DECHARGE   sinon                (SelfCheck disculpe)

score = (FUSION_WEIGHT_RAG * rag_belief + w_sc * sc_belief) / (FUSION_WEIGHT_RAG + w_sc)
```

Le RAG pèse plus que SelfCheck parce qu'il juge le fait, là où SelfCheck ne juge que le
modèle. Et SelfCheck pèse plus à charge qu'à décharge, pour la raison exposée en 1.1.

## 1.5 Classification et confiance

```
score < FUSION_SEUIL_FAUX (0.40)  ->  CONTREDIT,  confiance = 1 - score
score > FUSION_SEUIL_VRAI (0.60)  ->  VALIDÉ,     confiance = score
entre les deux                    ->  INDÉCIS,    confiance = 0.00
```

La confiance est toujours la **confiance dans le verdict rendu**. Un `INDÉCIS`
n'affirme rien : il n'y a rien dont être confiant, donc 0.00. Corrige le point 1.2.d de l'étude.

## 1.6 Paramètres et calibration

| nom | valeur de départ | statut |
|---|---|---|
| `FUSION_WEIGHT_RAG` | 0.60 | déjà déclaré dans `params.py`, jamais lu (point 20) |
| `FUSION_WEIGHT_SELFCHECK_CHARGE` | 0.55 | remplace `FUSION_WEIGHT_SELFCHECK` — SelfCheck accuse |
| `FUSION_WEIGHT_SELFCHECK_DECHARGE` | 0.30 | remplace `FUSION_WEIGHT_SELFCHECK` — SelfCheck disculpe |
| `FUSION_DIVERGENCE_NEUTRE` | 0.50 | **à calibrer** — notée `d0` dans les formules |
| `FUSION_BANDE_RAG_MIN` / `FUSION_BANDE_RAG_MAX` | 0.40 / 0.60 | à calibrer |
| `FUSION_SELFCHECK_SEUIL_HAUT` / `FUSION_SELFCHECK_SEUIL_BAS` | 0.80 / 0.20 | à calibrer |
| `FUSION_DECOTE_SIGNAL_SEUL` | 0.60 | choisi pour supprimer l'inversion au raccord R3 / R4-R5 |
| `FUSION_SEUIL_FAUX` / `FUSION_SEUIL_VRAI` | 0.40 / 0.60 | inchangés |

**Méthode de calibration retenue :** mettre en cache les sorties du RAG et de SelfCheck
par affirmation, pour pouvoir **rejouer la fusion seule** en faisant varier ces
paramètres, sans relancer le pipeline complet. Chantier distinct, à faire après la mise
en conformité du code.

---

# PARTIE 2 — Tableau comparatif : actuel → cible

Comportement actuel **mesuré** en exécutant le vrai `do_fusion`, comportement cible
calculé depuis la partie 1. ⚠️ marque un changement de verdict.
Chaque ligne deviendra un test unitaire — signaux synthétiques, aucun appel à Ollama ni
à FAISS, donc rejouable en CI.

| # | RAG | conf | div. | règle | verdict **actuel** | conf. | verdict **cible** | conf. | fondement |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `FEVER_CONFIRMS` | 0.95 | 0.05 | R2 | **VALIDÉ** | 0.95 | **VALIDÉ** | 0.95 | PREUVE_FEVER |
| 2 | `FEVER_CONFIRMS` | 0.95 | 0.85 | R2 | **VALIDÉ** | 0.71 | **VALIDÉ** | 0.95 | PREUVE_FEVER |
| 3 | `FEVER_REFUTES` | 0.99 | 0.85 | R2 | **CONTREDIT** | 0.99 | **CONTREDIT** | 0.99 | PREUVE_FEVER |
| 4 | `I_DONT_KNOWN` | 0.00 | 0.05 | R3 | **VALIDÉ** | 0.72 | **VALIDÉ** | 0.77 | CONVICTION |
| 5 | `I_DONT_KNOWN` | 0.00 | 0.15 | R3 | **VALIDÉ** | 0.68 | **VALIDÉ** | 0.71 | CONVICTION |
| 6 | `I_DONT_KNOWN` | 0.00 | 0.25 | R3 | **VALIDÉ** ⚠️ | 0.62 | **INDÉCIS** | 0.00 | AUCUN |
| 7 | `I_DONT_KNOWN` | 0.00 | 0.50 | R3 | **INDÉCIS** | 1.00 | **INDÉCIS** | 0.00 | AUCUN |
| 8 | `I_DONT_KNOWN` | 0.00 | 0.75 | R3 | **CONTREDIT** ⚠️ | 0.62 | **INDÉCIS** | 0.00 | AUCUN |
| 9 | `I_DONT_KNOWN` | 0.00 | 0.85 | R3 | **CONTREDIT** | 0.68 | **CONTREDIT** | 0.71 | CONVICTION |
| 10 | `I_DONT_KNOWN` | 0.00 | 0.95 | R3 | **CONTREDIT** | 0.72 | **CONTREDIT** | 0.77 | CONVICTION |
| 11 | `LIKELY_TRUE` | 0.10 | 0.10 | R3 | **VALIDÉ** | 0.73 | **VALIDÉ** | 0.74 | CONVICTION |
| 12 | `LIKELY_TRUE` | 0.10 | 0.50 | R3 | **INDÉCIS** | 0.95 | **INDÉCIS** | 0.00 | AUCUN |
| 13 | `LIKELY_FALSE` | 0.10 | 0.90 | R3 | **CONTREDIT** | 0.72 | **CONTREDIT** | 0.74 | CONVICTION |
| 14 | `LIKELY_TRUE` | 1.00 | 0.05 | R4 | **VALIDÉ** | 0.97 | **VALIDÉ** | 0.98 | CONVICTION |
| 15 | `LIKELY_TRUE` | 1.00 | 0.50 | R5 | **VALIDÉ** | 0.75 | **VALIDÉ** | 0.83 | CONVICTION |
| 16 | `LIKELY_TRUE` | 1.00 | 0.90 | R5 | **INDÉCIS** | 0.90 | **INDÉCIS** | 0.00 | CONVICTION |
| 17 | `LIKELY_TRUE` | 0.60 | 0.90 | R5 | **INDÉCIS** | 0.90 | **INDÉCIS** | 0.00 | CONVICTION |
| 18 | `LIKELY_FALSE` | 1.00 | 0.90 | R4 | **CONTREDIT** | 0.95 | **CONTREDIT** | 0.95 | CONVICTION |
| 19 | `LIKELY_FALSE` | 1.00 | 0.05 | R5 | **INDÉCIS** ⚠️ | 0.95 | **CONTREDIT** | 0.68 | CONVICTION |
| 20 | `LIKELY_FALSE` | 0.50 | 0.05 | R5 | **INDÉCIS** | 0.80 | **INDÉCIS** | 0.00 | CONVICTION |
| 21 | _panne SelfCheck_ | 1.00 | — | R1 | **VALIDÉ** ⚠️ | 0.85 | **PANNE** | — | — |
| 22 | _panne RAG_ | — | 0.90 | R1 | **CONTREDIT** ⚠️ | 0.70 | **PANNE** | — | — |

## 2.1 Lecture du tableau

**Six verdicts changent sur vingt-deux.** L'essentiel de la correction porte donc moins
sur les verdicts que sur **les confiances** — qui deviennent comparables entre branches —
et sur l'apparition de l'état PANNE.

- **Lignes 21-22** — les deux plus importantes. Aujourd'hui, une panne SelfCheck sort en
  `VALIDÉ 0.85` et une panne RAG en `CONTREDIT 0.70` : des prédictions d'apparence
  parfaitement normale, indiscernables de vraies, qui polluent silencieusement les
  matrices d'éval. Elles deviennent PANNE.
- **Ligne 19** — `LIKELY_FALSE` catégorique + LLM très cohérent, l'hallucination stable
  par excellence : `INDÉCIS` aujourd'hui, `CONTREDIT 0.68` en cible. C'est le poids
  asymétrique qui la débloque.
- **Lignes 6 et 8** — la zone intermédiaire (divergence entre 0.2 et 0.8) cesse de
  produire des verdicts fermes sur la seule foi de SelfCheck.
- **Ligne 7** — même verdict, mais la confiance passe de `1.00` à `0.00` : « aucune
  information nulle part » cesse d'être le résultat le plus confiant du système.
- **Ligne 2** — une preuve FEVER n'est plus décotée par l'instabilité du modèle
  (0.71 → 0.95).

## 2.2 Réserve à porter au débat

**Le cas « hallucination stable » n'est pas éliminé, il est restreint.** Lignes 4 et 5 :
`I_DONT_KNOWN` + LLM très stable ressort toujours en **VALIDÉ**, aujourd'hui comme en
cible. Ce qui change, c'est la fenêtre et l'étiquetage :

| | aujourd'hui | cible |
|---|---|---|
| validé sans aucune preuve tant que | `divergence < 0.30` | `divergence < 0.20` |
| confiance affichée | 0.72 | 0.77, **décotée** |
| fondement | *(inexistant)* | `CONVICTION`, jamais `PREUVE_FEVER` |

C'est la conséquence assumée de la règle « SelfCheck est décisif aux extrêmes ». Mais
il faut le dire explicitement plutôt que de le laisser découvrir : le système continue
de valider des affirmations sans la moindre preuve, sur la seule stabilité du modèle.

**Piste si on veut resserrer**, cohérente avec le principe d'asymétrie déjà retenu :
rendre les deux seuils de R3 **asymétriques** — par exemple `FUSION_SELFCHECK_SEUIL_HAUT = 0.90` et
`FUSION_SELFCHECK_SEUIL_BAS = 0.25`. Il devient alors plus difficile de valider que d'accuser, ce qui
est exactement ce que dit le principe. À trancher, ou à laisser décider par la
calibration.

---

# PARTIE 3 — Points restant ouverts

1. **Seuils de R3 symétriques ou asymétriques ?** Cf. 2.2. Seul point de la spec qui
   demande encore un arbitrage avant écriture du code.
2. **De qui est la conviction ?** En R4/R5 elle vient de la connaissance interne du
   modèle RAG ; en R3 de la stabilité du modèle qui a répondu. Deux choses différentes
   sous la même étiquette `CONVICTION`. Reporté à la refonte du schéma de sortie de
   l'API, pour décider comment le présenter.
3. **Calibration** — cf. 1.6, chantier distinct (cache des sorties RAG/SelfCheck pour
   rejouer la fusion seule).
4. **Point 4 de `tofix.md`** (langue des échantillons) à traiter avant de calibrer :
   tant qu'il est là, une partie des divergences mesurées est du bruit pur.

# Ce que cette spec ferme dans `tofix.md`

| point | comment |
|---|---|
| **3** — cohérence traitée comme une probabilité de vérité | asymétrie restaurée (R3/R4/R5) |
| **9** — `final_conf` mesure la centralité | confiance = confiance dans le verdict, 0.00 si INDÉCIS |
| **20** — poids de fusion non câblés | `FUSION_WEIGHT_RAG` lu depuis `params.py`, poids SelfCheck ajoutés |
| **19** — prints de debug dans `fusion.py` | disparaissent avec la réécriture |
| **7** — pannes indiscernables | partiellement : R1 définit l'état ; **la détection reste à faire** dans `rag/retriever.py` et `selfcheck/scorer.py` |

> ⚠️ **Prérequis : le point 2.** Tant que `rag/retriever.py:133-141` écrase les verdicts
> `LIKELY_TRUE` / `LIKELY_FALSE`, la fusion ne reçoit que des `I_DONT_KNOWN` à confiance
> `0.0` — donc `rag_belief = 0.5`, donc toujours la bande neutre, donc toujours **R3**.
> Les règles **R4** et **R5** ne se déclencheraient quasiment jamais. Appliquer cette
> spécification sans corriger le point 2 produit un système correct sur le papier dont
> deux règles sur cinq sont mortes en production.

Analyse complète des dépendances et des dettes induites : section 3 de
[`etude-fusion-2026-09-01.md`](etude-fusion-2026-09-01.md).
