# Les 25 questions d'exemple, une par fichier

Chaque fichier porte l'origine de la question, la réponse du modèle évalué, le
tableau des verdicts, la **trace de debug complète** et sa lecture.

Le classement suit le comportement de **Berlue**, pas celui du modèle évalué :
une réponse fausse correctement contredite est un succès, une réponse juste
validée sans rien pour l'étayer est un échec.

## [`succes/`](succes) — 15 questions

Berlue a rendu le bon verdict, et pour la bonne raison.

Les plus instructifs : [`ex-09`](succes/ex-09.md), où la double négation d'un
extrait `REFUTES` est correctement traitée — à comparer avec `echecs/ex-07`, qui
échoue sur la même mécanique ; [`ex-16`](succes/ex-16.md) et
[`ex-17`](succes/ex-17.md), postérieurs au corpus, où aucune preuve FEVER
abusive n'est produite ; [`ex-22`](succes/ex-22.md), entité inventée
correctement contredite.

## [`echecs/`](echecs) — 10 questions

Deux marqués `❌`, où le verdict est franchement faux :

- [`ex-07`](echecs/ex-07.md) — **la double négation**. Une affirmation vraie est
  contredite à 0,99 avec preuve : l'extrait `REFUTES` est un mensonge, donc son
  contraire est vrai, mais le raisonnement conclut que l'affirmation « répète »
  l'extrait alors qu'elle le nie.
- [`ex-08`](echecs/ex-08.md) — **l'affirmation composite**. « La sortie de 2000
  de Titanic fut un succès » mêle un présupposé faux et un attribut vrai ; FEVER
  réfute la date à 0,376, le modèle retient l'extrait sur les recettes.

Huit marqués `⚠️`, plus discrets mais du même ordre : validations par conviction
sans appui documentaire ([`ex-12`](echecs/ex-12.md),
[`ex-21`](echecs/ex-21.md), [`ex-24`](echecs/ex-24.md), à des distances
supérieures à 0,8), contradiction douteuse d'un fait exact
([`ex-01`](echecs/ex-01.md)), ou preuve disponible dans le corpus mais non
retrouvée par la récupération ([`ex-02`](echecs/ex-02.md)).
