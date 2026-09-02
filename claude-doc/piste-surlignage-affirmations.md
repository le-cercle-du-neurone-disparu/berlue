# Piste — relier chaque affirmation au passage qui l'a produite

Objectif : surligner dans la réponse du modèle les passages correspondant à
chaque affirmation, avec une couleur par verdict.

**Non planifié.** Ce document existe pour que l'analyse ne soit pas à refaire ;
rien n'est engagé.

## Pourquoi ce n'est pas possible aujourd'hui

`Claim` ne porte que `source_answer`, la réponse entière. Aucune position, aucun
extrait. Et trois transformations séparent l'affirmation de son texte d'origine.

**La traduction.** La règle 3 du prompt d'extraction impose l'anglais, parce que
le corpus FEVER est anglais. Une réponse en français produit donc des
affirmations anglaises : rien ne relie « the law of gravity » à « la loi de la
gravité » sans un alignement supplémentaire.

**La synthèse.** La règle 1 fabrique une première affirmation qui énonce le fait
global, en résolvant les pronoms. Cette phrase n'existe nulle part dans la
réponse — elle est construite, pas citée.

**Le recouvrement.** Les règles 1 et 2 s'appliquent au même texte sans que rien
n'interdise leur chevauchement. Observé sur une réponse d'UNE phrase :

```
réponse    : « ...la loi de la gravité qui ne s'applique pas à l'énergie,
               mais à l'âge d'or. »
affirmation 1 : Einstein's theory of relativity explains that the law of gravity
                is a law of gravity that does not apply to energy, but to the
                age of gold.          ← la phrase entière
affirmation 2 : The law of gravity in Einstein's theory of relativity does not
                apply to energy.      ← un fragment de la même phrase
```

Un même passage correspond alors à deux affirmations, donc à deux couleurs sur
les mêmes mots.

## Trois voies, par coût croissant

### 1. Citation verbatim — recommandée

L'extraction rend, avec chaque affirmation, l'extrait **exact** de la réponse
dont elle provient, **dans la langue d'origine** et non traduit. Le serveur
localise cet extrait par recherche de chaîne, calcule les positions, et le
frontend surligne des intervalles.

Le format de sortie de l'extraction passe d'un tableau de chaînes à un tableau
d'objets — c'est le vrai coût du changement, avec le prompt et le parseur.

Mérite secondaire : **le recouvrement devient visible**. Deux affirmations
issues du même passage produiraient des intervalles qui se chevauchent, et le
défaut sauterait aux yeux dans l'interface au lieu de rester enfoui dans le
champ `debug`.

Le calcul des positions doit vivre côté serveur, pas dans le frontend : c'est
là qu'il peut être testé, et là qu'il ne sera écrit qu'une fois si un second
client apparaît. Un extrait introuvable ne donne aucun surlignage — jamais un
surlignage approximatif, qui désignerait le mauvais passage.

### 2. Découpage par phrase d'abord

Segmenter la réponse en phrases de façon déterministe, puis extraire
phrase par phrase en conservant l'indice. L'appariement devient exact, sans
recherche de chaîne.

Deux inconvénients : on perd la synthèse globale, qui traverse justement
plusieurs phrases ; et le coût monte, avec un appel d'extraction par phrase sur
un étage déjà lent.

### 3. Alignement sémantique après coup

Un second modèle relie chaque affirmation anglaise à un passage français.
Coûteux, faillible, et il ajoute un étage à déboguer. Déconseillé.

## Ce qu'il faudrait trancher avant de commencer

**L'affirmation de synthèse n'a pas de passage propre.** Elle est fabriquée.
Soit elle couvre toute la réponse, soit elle est marquée « globale » et n'est
pas surlignée.

**Le recouvrement doit être corrigé en même temps**, sans quoi deux couleurs se
disputeront les mêmes mots. La consigne manquante : les affirmations atomiques
ne répètent rien de la synthèse, et une réponse d'une seule phrase ne produit
qu'une affirmation.

**Le cache et les comparaisons seront invalidés.** Changer le prompt
d'extraction change toutes les affirmations produites, donc les verdicts. Une
purge s'impose, et toute mesure antérieure devient incomparable.

## Ce qui existe déjà et servira

Le champ `debug` de `/predict` porte le détail par affirmation, et le cache le
conserve. Il faudra y ajouter les positions, mais la plomberie est en place.
