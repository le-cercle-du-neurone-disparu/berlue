### 🎤 Script de présentation : Aletheia (5 minutes)

**[0:00 - 1:00] Introduction : Le mirage de l'IA**
« Bonjour à tous.
Aujourd'hui, l'Intelligence Artificielle générative est partout. Pour des raisons évidentes de confidentialité et de sécurité des données, beaucoup d'entreprises choisissent d'installer des **modèles locaux**. Vos données restent chez vous, sur vos serveurs. C'est la solution idéale.

Mais il y a un problème majeur. Ces intelligences artificielles ont un défaut troublant : elles ont un aplomb à toute épreuve. Qu'elles vous disent la stricte vérité ou qu'elles inventent totalement une information – ce qu'on appelle une "hallucination" – elles le font avec la même assurance. Face à un texte bien écrit, l'utilisateur n'a aucun moyen de savoir quelle phrase est vraie et quelle phrase est fausse.

Comment faire confiance à un outil qui peut mentir avec autant de conviction ? C'est pour répondre à ce défi que nous avons créé le moteur **Berlue**, et son interface : **Aletheia**, du nom de la déesse de la vérité. »

**[1:00 - 2:00] Lancement de la Démo**
« Laissez-moi vous montrer concrètement comment nous redonnons de la transparence à l'IA.
*[Action : Montrer l'interface Aletheia à l'écran]*
Ici, nous sommes sur notre interface. Nous avons sélectionné un modèle d'IA local, et nous allons lui poser une question volontairement un peu pointue : *"C'est quoi la musique Nice & Slow ?"*
*[Action : Lancer la requête]*

Le modèle nous répond. Le texte s'affiche. C'est fluide, c'est structuré, ça a l'air tout à fait crédible. Si je n'y connais rien, je prends cette information pour argent comptant. Et c'est là qu'Aletheia intervient.
*[Action : Cliquer sur le bouton d'analyse d'Aletheia]*

Je lance l'analyse. Alors, en conditions réelles, ce travail de détective prend quelques secondes. Pour la fluidité de cette présentation, nous avons mis le résultat en cache, mais laissez-moi vous expliquer ce qui se passe sous le capot à cet instant précis... »

**[2:00 - 3:30] Vulgarisation du fonctionnement (Le "Sous le capot")**
« Plutôt que de lire le texte en bloc, Aletheia va le découper en toutes petites phrases, qu'on appelle des affirmations factuelles. Et pour chaque phrase, elle mène une double enquête :

1. **Premièrement, la recherche de preuves :** Aletheia va fouiller dans une base de connaissances que nous lui avons fournie (une sorte d'encyclopédie interne de faits avérés) pour voir si elle trouve des preuves qui confirment ou contredisent la phrase de l'IA.
2. **Deuxièmement, le test de cohérence :** C'est un peu la technique de l'interrogatoire. Le système va forcer l'IA à répondre plusieurs fois à la même question en arrière-plan. Si l'IA a inventé un fait de toutes pièces, elle finira presque toujours par se contredire d'une version à l'autre.

Notre moteur compile ces deux enquêtes pour générer un score de confiance.
*[Action : Montrer le résultat coloré à l'écran]*
Et voici le résultat : le texte s'est coloré. En un coup d'œil, Aletheia nous pointe exactement où le modèle a "la berlue". »

**[3:30 - 4:15] Lecture des résultats**
« La lecture est hyper intuitive :
- **En vert :** C'est validé. L'information est factuelle.
- **En rouge :** C'est réfuté. L'outil a trouvé la preuve que l'IA hallucine.
- **En orange :** C'est incertain. L'outil n'a pas assez de preuves pour trancher, il vous invite à la prudence.

Et si on clique sur une phrase, Aletheia justifie son choix en nous donnant son score de confiance et la preuve exacte qu'elle a trouvée. On passe d'une IA "boîte noire" à une IA transparente. »

**[4:15 - 5:00] Preuve d'efficacité et Vision (Roadmap)**
« Mais on ne s'est pas arrêtés à une simple démonstration visuelle. Nous avons voulu prouver l'efficacité de notre moteur de façon statistique.

Nous avons donc confronté notre système à des jeux de données d'évaluation extrêmes. Ce sont des batteries de questions spécifiquement conçues pour être des "pièges" à IA, celles qui provoquent le plus d'hallucinations. Et les résultats sont excellents : **notre outil se révèle nettement supérieur à la baseline statistique classique**. Aletheia déjoue les pièges là où les autres se laissent avoir.

Et le plus beau, c'est que nous pouvons rendre ce système encore plus puissant. Pour le moment, notre outil se base sur une encyclopédie interne fixe. Pour améliorer encore ses scores demain, nous avons deux grandes pistes :
1. **Intégrer (ou "embedder") directement ces fameux jeux de données très complexes** dans notre base de connaissances pour entraîner notre outil sur les pires cas possibles.
2. **Connecter Aletheia au monde réel en temps direct**, en faisant des appels vers des API externes comme Wikipédia, pour que l'outil puisse vérifier la vérité sur des sujets d'actualité chaude.

En résumé : avec Aletheia, vous gardez la confidentialité totale de vos IA locales, mais vous n'êtes plus jamais aveugles face à leurs hallucinations. Vous lisez enfin la vérité.

Je vous remercie de votre attention, et je serais ravi de répondre à vos questions ! »
