# Progression possible — améliorer le produit

Ce document ne liste pas des défauts à corriger (`tofix2.md` s'en charge) : il liste **ce qui
rendrait Berlue meilleur pour celui qui s'en sert**. L'axe est l'usage, pas la métrique
d'évaluation.

Chaque piste part d'une mesure. Les chiffres viennent de
`claude-doc/analyses/v1/analyse-pipeline.md` (30 exemples lus un par un),
`claude-doc/couverture-corpus-2026-09-02.md` (couverture du corpus de preuves) et
`docs/evaluation/result-version-2026-09-01.md` (runs d'évaluation).

---

# Ce que le produit rend aujourd'hui, honnêtement

Un utilisateur pose une question, reçoit une réponse d'un LLM, et Berlue lui rend pour chaque
affirmation extraite : **un verdict** (validé / contredit / indécis), **un score de confiance**,
**une source ou une explication**.

Voici l'état réel de chacun de ces trois éléments.

| ce qui est promis | ce qui est rendu aujourd'hui |
|---|---|
| une **preuve documentaire** | **2 %** des affirmations en obtiennent une ; les 98 % restants reposent sur la mémoire du modèle vérificateur |
| un **verdict fiable** | le vérificateur valide indifféremment une affirmation et son contraire, à confiance égale |
| une **explication** | le texte affiché contredit parfois le verdict qu'il justifie |

**C'est le cœur du sujet produit** : les trois promesses sont tenues sur le papier et fragiles à
l'usage. Ce qui suit vise à les tenir vraiment.

---

# 1. Définir sur quoi le produit sait répondre

**Le choix le plus structurant, et il n'est pas technique.**

**Constat.** Une affirmation issue de nos jeux de test est en moyenne trois fois plus loin de
l'index de preuves qu'une affirmation du domaine de ce corpus (médiane 0,87 contre 0,31, mesuré
avec témoin). Sur un run complet, **1 affirmation sur 346** a obtenu un verdict fondé sur une
preuve citée.

Vérifié en démonstration : **sur un sujet couvert par la base, la chaîne fonctionne
parfaitement.** *« Qui a écrit Titus Andronicus ? »* → réponse vraie validée à 1,00 avec preuve
citée, réponse fausse contredite à 0,99 avec la même preuve. Le produit fait exactement ce qu'il
promet — quand le sujet est dans sa base.

**Trois positionnements possibles, à trancher :**

- **Un produit de domaine.** On assume que Berlue vérifie *un périmètre annoncé* (ce que couvre
  la base), et on le dit à l'utilisateur. C'est honnête, démontrable, et immédiatement vendable.
- **Un produit généraliste.** Il faut alors une base qui couvre ce que les gens demandent —
  Wikipédia complet plutôt qu'un jeu d'affirmations, ou une recherche web.
- **Un produit sans base documentaire**, qui assume vérifier par la connaissance d'un modèle. Le
  discours change complètement : ce n'est plus « nous citons nos sources », c'est « nous
  demandons son avis à un second modèle ». La piste 2 devient alors tout le produit.

**Ce qui est en jeu pour l'utilisateur** : aujourd'hui il reçoit 98 % de verdicts sans source
tout en croyant utiliser un vérificateur documentaire.

---

# 2. Un verdict en qui on peut avoir confiance

**Constat, démontré par paires.** La même question posée avec sa réponse vraie puis sa réponse
fausse produit deux affirmations incompatibles — et le vérificateur confirme les deux :

| affirmation | verdict | affirmation contraire | verdict |
|---|---|---|---|
| diffusée en **2006** | validé, confiance 0,95 | diffusée en **2003** | validé, confiance 0,95 |
| écrit pour **Make** | validé, confiance 0,95 | écrit pour **Popular Science** | validé, confiance **0,99** |

Avec *plus* d'assurance sur la fausse dans le second cas. Sur un jeu équilibré moitié vrai moitié
faux, il répond « probablement vrai » dans **63,6 %** des cas.

**Pour l'utilisateur, c'est le pire défaut possible** : un vérificateur qui valide tout est pire
qu'aucun vérificateur, parce qu'il donne une caution.

**Piste principale** : lui faire **énoncer le fait avant de voir l'affirmation à juger**, au lieu
de lui présenter une thèse à confirmer. Un modèle qui doit produire « 2006 » avant de voir
« 2003 » ne peut plus valider les deux. C'est une réécriture de prompt, pas un chantier.

**Complément** : lui apprendre à s'abstenir. Le verdict « je ne sais pas » existe, mais aucun
exemple ne lui montre à quoi ressemble une bonne abstention — il n'a jamais vu le comportement
qu'on attend de lui.

---

# 3. Des explications qui tiennent debout

**Constat.** Le texte rendu à l'utilisateur est parfois incohérent avec le verdict qu'il
accompagne :

- *« the claim cannot be definitively confirmed or refuted »* → suivi d'un verdict **validé** à
  0,95 ;
- sur une réponse fausse : *« Excerpts 0, 1, and 2 SUPPORT the claim »* → puis conclusion inverse,
  correcte ;
- une source **inventée** pour étayer un verdict par ailleurs juste : une série néerlandaise qui
  n'existe pas, citée comme origine d'une autre ;
- un exemple **piochant dans les extraits hors sujet** : un film tamoul cité comme exemple de film
  hindi, parce qu'il traînait dans le contexte.

Le verdict peut être juste et l'explication fausse. **Un utilisateur qui lit l'explication perd
confiance, ou pire, la croit.**

**Pistes** : contraindre la sortie par schéma (le verdict ne peut plus sortir de sa nomenclature),
exiger que le raisonnement précède et justifie le verdict, et ne jamais afficher un extrait qui
n'a pas servi à la décision.

---

# 4. Dire à l'utilisateur *sur quoi* repose le verdict

Le produit distingue désormais une **preuve** (la base a tranché) d'une **conviction** (le modèle
pense, sans preuve). C'est acquis et c'est la bonne base. Deux questions restent ouvertes, et
elles sont d'interface autant que de code :

- **De qui est la conviction ?** Celle du modèle vérificateur puisant dans sa mémoire, ou celle
  déduite de la stabilité du modèle qui a répondu ? Deux choses très différentes, aujourd'hui
  sous la même étiquette.
- **Faut-il un état « non fiable », distinct de « faux » ?** Une réponse instable et sans preuve
  n'est pas fausse — elle n'est pas fiable. L'utilisateur a besoin de la nuance ; un drapeau
  orange « à vérifier » n'est pas un drapeau rouge « c'est faux ».

**Et la confiance affichée doit vouloir dire quelque chose.** Elle est désormais comparable d'un
verdict à l'autre, mais reste à décider si l'on montre le chiffre brut, une échelle à trois
crans, ou rien du tout quand il n'y a pas de preuve.

---

# 5. Ce que le produit devrait refuser de dire

Aujourd'hui il tranche même quand il n'a rien : sur une affirmation en charabia, il a rendu
« prouvé vrai » avec **confiance 1,0** en citant un extrait sans aucun rapport (distance 1,21,
contre ~0,2 pour un vrai appariement).

**Piste** : un seuil de pertinence sur les extraits — **la valeur est mesurée, 0,44**. Au-delà, on
n'injecte rien et on le dit.

**Mais il faut voir la conséquence produit** : avec ce seuil, sur nos jeux actuels, le produit
dirait « aucune preuve en base » dans 98 % des cas. C'est la vérité. Est-ce le produit qu'on veut
montrer ? La réponse dépend entièrement de la piste 1.

---

# 6. Élargir l'usage : les langues

Le moteur d'inférence est **anglophone uniquement**. Sur une question française, l'affirmation est
traduite en anglais et comparée à des échantillons restés en français : le signal produit est du
bruit. Le chemin est atteignable par l'API et par la démo — la question d'exemple de la CLI était
en français.

**Piste** : un modèle d'inférence multilingue. Sans lui, le produit est anglophone, et il faut
l'assumer explicitement plutôt que de le découvrir en démonstration.

---

# 7. Le temps de réponse

Une question coûte aujourd'hui environ **2,4 secondes en local**, et **7,96 secondes sur GCP** —
3,3× plus lent, parce que le service d'évaluation n'a pas de GPU et que l'inférence, l'embedding
et la recherche tournent sur CPU.

Pour un usage interactif, c'est la limite haute de l'acceptable, et ça croît avec le nombre
d'affirmations extraites. **Pistes** : un GPU sur le service applicatif, la parallélisation des
vérifications d'affirmations (aujourd'hui séquentielles), et le préchargement des poids dans
l'image — sans quoi le premier appel après une mise en veille paie ~1,3 Go de téléchargement.

---

# 8. Savoir si l'on progresse

**Sans ça, aucune des pistes ci-dessus ne sera démontrable.**

Deux runs du **même code** donnent des résultats qui diffèrent de 3,3 points — davantage que
l'effet de la plupart des améliorations visées. Deux causes mesurées : le tirage des échantillons,
non fixé, et le modèle lui-même (sur 5 affirmations soumises 6 fois à température 0, **1 sur 5**
change de verdict).

**Pistes** : fixer une graine de génération, répéter et moyenner plutôt que comparer deux runs
uniques, et — déjà en place — rejouer la décision depuis les signaux mis en cache, ce qui la teste
en quelques secondes sur des données identiques, donc sans bruit.

---

# Dans quel ordre

1. **Trancher le positionnement** (piste 1) : produit de domaine, généraliste, ou sans base. Tout
   le reste en découle, y compris ce qu'on affiche à l'utilisateur.
2. **Réparer la complaisance du vérificateur** (piste 2). C'est le défaut qui coûte le plus cher
   en confiance, et le moins cher à corriger.
3. **Fiabiliser la mesure** (piste 8), sinon on ne saura pas si le reste marche.
4. **Les explications** (piste 3) et **le vocabulaire du verdict** (piste 4) : c'est ce que
   l'utilisateur lit, et aujourd'hui ça ne tient pas toujours.
5. Le seuil de pertinence (piste 5), les langues (piste 6), le temps de réponse (piste 7).
