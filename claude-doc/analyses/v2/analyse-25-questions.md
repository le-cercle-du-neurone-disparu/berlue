# Analyse des 25 questions d'exemple — pipeline v2

Passage des 25 questions de `questions-exemples.md` à l'API locale avec
`debug: true`, après les deux évaluations de la nuit. Objectif : trouver ce qui
peut être amélioré, trace à l'appui.

**8 minutes** pour les 25 questions, 17,3 s de moyenne, 92 affirmations
extraites. Réponses brutes conservées dans le répertoire de travail de la
session.

## Vue d'ensemble

| Verdict | Fondement | Nombre |
|---|---|---|
| SUPPORTED | conviction | 42 |
| SUPPORTED | preuve FEVER | 32 |
| NOT_ENOUGH_INFO | conviction | 15 |
| CONTRADICTED | preuve FEVER | 4 |
| CONTRADICTED | conviction | 4 |

**Un tiers des verdicts s'appuie sur une preuve documentaire** (36/97), ce qui
est cohérent avec la construction du jeu : dix questions sur vingt-cinq visent
des affirmations présentes dans FEVER.

## Les sept pièges à présupposé faux : 5 réussites, 2 échecs

| # | Piège | Le modèle | Berlue |
|---|---|---|---|
| 7 | Buddy Holly aux Beatles | refuse ✓ | **❌ contredit une affirmation vraie** |
| 8 | Titanic sorti en 2000 | **tombe dedans** | **❌ valide l'erreur** |
| 9 | Macbeth comédie | refuse ✓ | ✓ |
| 10 | Apollo 11 en avril | refuse ✓ | ✓ |
| 23 | Einstein refuse le Nobel | tombe dedans | ✓ contredit |
| 24 | Lovelace et l'ENIAC | refuse ✓ | ✓ |
| 25 | trois langues au Brésil | tombe dedans | ✓ contredit |

Sur les trois cas où le générateur s'est trompé, Berlue en a rattrapé deux.

## Défaut 1 — la double négation d'un extrait REFUTES

**Le plus grave, et il inverse le verdict.**

```
affirmation : Buddy Holly did not join The Beatles.        ← VRAIE
extrait [0] : Buddy Holly was a member of The Beatles.  REFUTES  d=0.406
verdict     : FEVER_REFUTES · CONTRADICTED · confiance 0.99
raisonnement: « ...its label is REFUTES, meaning this statement is a lie.
               The claim repeats the false statement from Excerpt 0. »
```

L'affirmation ne **répète** pas l'extrait, elle en énonce **le contraire**. Le
raisonnement exige une double négation — l'extrait est faux, donc son contraire
est vrai, donc l'affirmation qui *est* ce contraire est vraie — et le modèle la
saute.

La règle actuelle du prompt l'y invite :

> If the claim repeats a "REFUTES" statement, the claim is therefore FALSE.

Elle ne dit rien du cas où l'affirmation **nie** l'extrait. Et la question 9
montre que le modèle y arrive parfois : le défaut est intermittent, donc c'est
une ambiguïté du prompt, pas une incapacité du modèle.

**Correctif proposé.** Rendre la double négation explicite :

```
A REFUTES excerpt is FALSE, so its OPPOSITE is true.
Compare the claim to the OPPOSITE of the excerpt:
- the claim says the SAME as the excerpt      → the claim is FALSE
- the claim says the OPPOSITE of the excerpt  → the claim is TRUE
"X did not join Y" is the OPPOSITE of "X was a member of Y", not a repetition.
```

## Défaut 2 — les affirmations composites

```
affirmation : The 2000 release of the film Titanic was successful.
extrait [0] : Titanic was released in 2000.        REFUTES   d=0.376
extrait [1] : Titanic had record-setting sales.    SUPPORTS  d=0.500
verdict     : FEVER_CONFIRMS par l'extrait [1] · SUPPORTED · confiance 1.0
```

L'affirmation en contient deux : qu'une sortie a eu lieu en 2000, et qu'elle fut
un succès. La première est fausse et FEVER la réfute explicitement ; la seconde
est vraie. Le modèle a retenu celle qu'il pouvait confirmer et **ignoré la
réfutation du présupposé**.

La cause est en amont, dans l'extraction : la règle 1 du prompt fabrique une
affirmation de synthèse qui reprend la question telle quelle, présupposé compris.
Une affirmation atomique aurait donné deux énoncés vérifiables séparément.

**Deux correctifs possibles**, l'un traitant le symptôme, l'autre la cause :

- côté RAG : une réfutation d'un élément de l'affirmation prime sur la
  confirmation d'un autre — un présupposé faux suffit à rendre l'ensemble faux ;
- côté extraction : rendre la synthèse réellement atomique, ce qui est le
  correctif de fond mais invalide le cache et les comparaisons.

## Défaut 3 — validation d'entités inventées

La question 21 porte sur « la République de Sanmarco », qui n'existe pas. Deux
affirmations sur trois sont **validées par conviction**. La question 24 en valide
trois sur quatre.

Le RAG ne trouve rien — les distances vont de 0,81 à 0,92 — et la fusion se
rabat sur la conviction du modèle, qui invente. Aucun garde-fou ne dit que
l'absence totale d'appariement devrait faire douter plutôt que valider.

C'est le même angle mort que le seuil de distance manquant dans `retrieve()`
(test `xfail` en attente) : une distance de 0,9 n'est pas une preuve d'absence,
mais elle devrait au moins retirer de la confiance.

## Défaut 4 — l'indécision par défaut

15 verdicts sur 97 sont `NOT_ENOUGH_INFO`, tous par conviction. Sur les deux
évaluations de la nuit, la proportion est bien plus lourde — **41 % sur HaluEval,
44 % sur TruthfulQA**. Le pipeline s'abstient massivement.

Sur ce jeu de 25 questions, choisi pour être couvert par FEVER, l'indécision
reste modérée. L'écart entre les deux mesures dit que **le taux d'abstention
dépend surtout de la couverture documentaire**, pas des seuils de fusion.

## Ce qui fonctionne bien, et qu'il ne faut pas casser

**La récupération FEVER est excellente quand le sujet est couvert.** Distances de
0,000 sur « Macbeth is a tragedy », 0,007 sur le Nobel de 1979, 0,017 sur le Nil,
0,023 sur Buddy Holly. Le corpus répond quand il contient la réponse.

**Le test de pertinence tient.** Aucune des questions postérieures au corpus —
Coupe du monde 2022, JO 2020, James Webb — ne reçoit de preuve FEVER abusive.
Elles sont toutes traitées en conviction, ce qui est le comportement voulu.

**Le rattrapage fonctionne** sur deux des trois erreurs du générateur.

## Ordre de traitement suggéré

1. **La double négation** (défaut 1) — inverse le verdict, correctif de prompt
   local, testable sur le cas Buddy Holly.
2. **Les affirmations composites** (défaut 2) — commencer par le correctif RAG,
   moins invasif que la refonte de l'extraction.
3. **Le seuil de distance** (défaut 3) — déjà identifié, test `xfail` en attente.
4. **L'indécision** (défaut 4) — ne rien changer avant d'avoir mesuré l'effet
   des trois premiers : elle en dépend directement.
