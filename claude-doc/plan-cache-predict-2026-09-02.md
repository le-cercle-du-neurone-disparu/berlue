# Plan — cache des prédictions

Mettre en cache le résultat de `/predict`, pour que la même question posée
depuis Aletheia ne repaie pas six minutes de pipeline.

Document de conception : il fixe le fonctionnel avant d'écrire du code. Les
questions ouvertes sont regroupées en fin de document et demandent un
arbitrage.

## 1. Ce qu'on met en cache

La réponse complète de `/predict` : le texte produit par le modèle évalué, les
affirmations extraites, et leur verdict de fusion. Autrement dit un
`PredictOutput` entier, pas un fragment intermédiaire.

**On ne met en cache que ça.** Pas les signaux RAG, pas les scores SelfCheck,
aucun intermédiaire : seulement ce que l'API renvoie.

### Ce qui existait déjà, et pourquoi ce n'est pas la même chose

Le dépôt a déjà des caches, mais **tous du côté évaluation** :
`eval_predictions`, `eval_signals`, `llm_answers`, `judge_verdicts`. Ils sont
écrits par `run_eval.py`, `eval_service.py` et `fast_eval.py`.

Le chemin `/predict` n'en a **aucun** : `berlue/api/service.py` ne référence
pas le magasin. Chaque question posée dans Aletheia repart de zéro.

Les deux familles restent **séparées** — tables distinctes, règles distinctes,
purges distinctes :

| | caches d'éval (existants) | cache de prédiction (ce plan) |
|---|---|---|
| Alimenté par | les runs sur un jeu labellisé | les questions posées dans Aletheia |
| Contient | signaux, réponses, verdicts de juge — des intermédiaires | le retour d'API complet, rien d'autre |
| Règle sur le modèle | **modèle exact** — un scope, une identité | **taille seule**, avec relation d'ordre |
| Clé | `EvalScope` + question + réponse | question normalisée + tailles |

La différence de règle est voulue. Une évaluation compare des modèles : servir
le résultat d'un autre modèle ruinerait la mesure, donc l'identité exacte fait
partie du scope. Une démonstration cherche une réponse plausible vite : la
taille suffit.

## 2. La clé

### 2.1 Normalisation de la question

`question.strip().lower()`. « Quelle est la capitale de la France ? » et
« quelle est la capitale de la france ?  » désignent la même demande.

C'est volontairement grossier. On ne normalise ni la ponctuation, ni les
accents, ni les espaces internes : « la France? » et « la France ? » resteront
deux entrées distinctes. Aller plus loin — retirer la ponctuation finale,
replier les accents — augmente le taux de succès mais fait converger des
questions que le modèle traiterait différemment. À revoir si le taux de succès
observé est décevant, pas avant.

La question **normalisée sert de clé** ; la question **d'origine est stockée**
telle quelle dans la valeur, parce que c'est elle qu'on réaffiche.

### 2.2 Les modèles : la taille seule

Trois modèles interviennent :

| Rôle | Paramètre | Effet |
|---|---|---|
| générateur évalué | `payload.llm.name` | produit **la réponse** à vérifier |
| extraction | `EXTRACT_MODEL` | découpe la réponse en affirmations |
| RAG | `RAG_MODEL` | juge chaque affirmation |

Côté pipeline, **seule la taille compte, jamais la famille**. `mistral:7b` et
`gemma:7b` sont traités comme équivalents. La taille se lit dans le tag Ollama :
`llama3.2:3b` → 3, `llama3.1:8b` → 8, `phi3:14b` → 14.

La règle : si les tailles demandées sont **inférieures ou égales** à celles de
l'entrée en cache, on sert le cache ; sinon on recalcule et on remplace.

La comparaison porte sur le triplet (générateur, extraction, RAG). Il faut que
les trois soient ≤ pour servir le cache : si l'un est supérieur, on recalcule.

Inclure le générateur dans cette règle a une conséquence qui n'est pas
anodine — voir la question ouverte 2, la seule qui reste à trancher.

Un tag dont la taille est illisible — `phi3.5:latest`, un modèle personnalisé —
est traité comme une taille inconnue. Deux tags **identiques** restent égaux
quoi qu'il arrive : c'est le cas courant et il ne dépend d'aucune lecture du
nom. Deux tags différents dont aucune taille n'est lisible ne peuvent pas être
comparés : on recalcule.

### 2.3 La température

**La température fait partie de la clé, en égalité stricte.** Deux températures
donnent deux caches distincts pour la même question.

Elle n'admet pas de relation d'ordre : une réponse produite à 0,7 n'est ni
meilleure ni pire que celle produite à 0,0, elle est autre. C'est le curseur
même que l'utilisateur manipule pour observer comment la créativité du modèle
change ses réponses — les confondre viderait la manipulation de son sens.

Conséquence assumée : le cache se fragmente. Le curseur d'Aletheia va de 0 à 1
par pas de 0,05, donc jusqu'à vingt-et-une entrées pour une même question. En
pratique les utilisateurs restent sur quelques valeurs rondes, et une entrée
inutile ne coûte que de l'espace.

### 2.4 Ce qui ne fait pas partie de la clé

**Les paramètres de fusion `FUSION_*`, et les prompts.** Ils changent les
verdicts sans changer aucune des composantes de la clé : une entrée calculée
avec d'anciens seuils, ou d'anciens prompts, continue d'être servie. Les mettre
dans la clé supposerait de les versionner, ce qui alourdit pour un bénéfice
faible s'ils bougent rarement. La contrepartie est qu'**une purge est
obligatoire après toute modification de prompt ou de seuil** — sinon on
compare un correctif à une réponse d'avant le correctif. C'est le risque décrit
au §7.

## 3. Où c'est stocké

Une table `predict_cache` dans le magasin existant, aux côtés de
`eval_predictions` et `eval_signals` : `LocalResultStore` en SQLite pour le
développement, `GcpResultStore` en Firestore sur Cloud Run. Aucun mécanisme
nouveau, et la purge s'y branche naturellement.

Colonnes :

| Colonne | Rôle |
|---|---|
| `question_key` | question normalisée — clé |
| `temperature` | température demandée — clé, égalité stricte |
| `question` | question d'origine, réaffichée telle quelle |
| `generator_model` | modèle évalué, tag complet |
| `generator_size`, `extract_size`, `rag_size` | tailles, comparées par ordre |
| `extract_model`, `rag_model` | tags complets, pour le champ d'origine |
| `payload` | le `PredictOutput` sérialisé en JSON |
| `created_at` | date d'écriture |
| `format_version` | version du format sérialisé |

`format_version` reprend ce que fait déjà `signals.py` : un changement du
schéma de `PredictOutput` doit invalider les entrées, pas produire une erreur
de désérialisation en production.

La clé primaire est `(question_key, temperature)` — une entrée par couple
question/température. Quand des modèles plus gros recalculent, ils
**remplacent**. On ne conserve pas un
historique par modèle — ce serait un cache qui ne se vide jamais. Les tailles
stockées servent à décider si l'entrée satisfait la requête, pas à en
multiplier les variantes.

## 4. Le flux

À la réception d'un `/predict` :

1. Normaliser la question, lire l'entrée `(question_key, temperature)`.
2. Absente → pipeline complet, écriture, retour.
3. Présente → comparer les tailles, triplet contre triplet :
   - les trois demandées ≤ celles du cache → **servir le cache**
   - sinon → pipeline complet, **remplacer**, retour.

L'écriture ne doit jamais faire échouer une requête : une prédiction calculée
qu'on ne peut pas stocker reste une prédiction valide. On journalise et on
poursuit — c'est déjà la convention de `put_signals`.

### Signaler l'origine du résultat

Le `PredictOutput` gagne un champ disant si la réponse vient du cache et avec
quels modèles elle a été calculée. Sans ça, un verdict servi depuis le cache
est indiscernable d'un verdict frais, et le prochain diagnostic recommencera
les tâtonnements de la journée. Aletheia peut l'afficher discrètement.

## 5. La purge

`make predict_cache_purge`, avec des filtres facultatifs :

```
make predict_cache_purge                          # tout
make predict_cache_purge QUESTION="capitale..."   # une question, toutes températures
make predict_cache_purge MODEL=llama3.2:3b        # un générateur
make predict_cache_purge TEMPERATURE=0.3          # une température
```

Une purge sans filtre vide tout : c'est explicite et c'est le geste courant
après un changement de prompt ou de seuils de fusion.

Un scope `predict` s'ajoute aux scopes de purge existants (`results`,
`matrices`, `signals`, `fusion`, `all`). **Attention** : la garde qui protège
`purge()` doit couvrir cette table — un filtre qui ne s'applique à aucune de
ses colonnes ne doit pas s'y transformer en joker. C'est la faute qui a
déjà détruit 50 lignes de `llm_answers` et de `judge_verdicts`.

`make predict_cache_list` complète l'ensemble : voir ce qu'il contient sans
ouvrir la base.

## 6. Pousser le cache local vers GCP

Le magasin est choisi par `BERLUE_EVAL_STORE_TARGET` : SQLite en local, Firestore
sur Cloud Run. Les deux ne se parlent pas, et **aucune synchronisation n'existe
aujourd'hui**, pour aucun cache — ni d'éval, ni autre.

L'usage visé : préparer des questions en local, où chaque essai est gratuit,
puis publier le résultat pour que la démonstration déployée réponde
instantanément. Les vingt-cinq questions d'exemple sont exactement ce cas.

```
make predict_cache_push                          # tout le cache local
make predict_cache_push QUESTION="capitale..."   # une seule entrée
```

### Ce que la commande fait

Elle lit `predict_cache` dans le magasin local et écrit chaque entrée dans le
magasin GCP. Un sens unique : local vers GCP, jamais l'inverse. Rapatrier le
cache de production sur un poste de développement n'a pas d'usage, et
l'ajouter doublerait la surface d'erreur.

### La règle de collision

Une entrée peut déjà exister côté GCP pour la même clé. On applique **la règle
du cache** plutôt qu'un écrasement systématique : l'entrée locale ne remplace
la distante que si ses tailles de modèles sont **supérieures ou égales**.

Le raisonnement : une entrée produite sur un poste de développement l'a
souvent été avec de petits modèles, faute de GPU. Écraser sans condition
dégraderait le cache de production avec des verdicts de moindre qualité. La
règle de comparaison est donc la même qu'au §2.2 — écrite une fois, utilisée
aux deux endroits.

`--force` passe outre, pour le cas où on veut délibérément publier un résultat
recalculé après un changement de prompt.

### Ce qu'elle affiche

Le nombre d'entrées poussées, ignorées (distante meilleure), et remplacées.
Sans ce décompte, une commande qui n'écrit rien à cause de la règle de
collision serait indiscernable d'une commande qui a tout publié.

### Prérequis

Les mêmes que pour l'éval sur GCP : identifiants valides et droits d'écriture
Firestore. La commande doit échouer tôt et clairement si le magasin distant
est inaccessible, pas au milieu d'un parcours de deux cents entrées.

## 7. Ce que ce cache ne fait pas

**Il ne réduit pas la latence de la première question.** Six minutes restent
six minutes pour une question neuve. Le cache sert les répétitions : les démos,
les questions d'exemple, les tests successifs sur la même formulation.

**Il ne remplace pas la parallélisation.** Le coût dominant du pipeline est
l'inférence NLI sur CPU, mesurée à plus de cinq minutes sur six. Le cache
l'évite quand il frappe, il ne le réduit jamais.

**Il fige les défauts.** Une réponse erronée mise en cache le reste jusqu'à la
purge. Pendant une phase de correction active des prompts, c'est un risque
réel : on peut croire qu'un correctif n'a rien changé alors qu'on relit une
entrée périmée. D'où l'importance du champ d'origine et de la purge.

## 8. Questions ouvertes

**1. Le taux de succès justifie-t-il la normalisation minimale ?**
`strip().lower()` ne rattrape ni la ponctuation ni les accents. Faut-il aller
plus loin dès le départ, ou mesurer d'abord ?

**2. ~~La règle de taille vaut-elle aussi pour le générateur ?~~ — tranché**
Oui, pour les trois : générateur compris, seule la taille compte.

La conséquence est assumée et doit rester visible : si le cache contient une
réponse de `phi3:14b` et qu'on demande `llama3.2:3b`, on affichera la réponse
du 14b sous l'étiquette du 3b — un résultat plus flatteur que ce que le 3b
aurait produit. Le champ d'origine (§4) doit donc nommer les modèles réellement
utilisés, pas ceux demandés. C'est la seule chose qui rende l'écart lisible.

**3. Faut-il borner le nombre de températures mises en cache ?**
Tranché : la température est dans la clé, en égalité stricte. Reste à savoir si
on accepte les vingt-et-une valeurs du curseur ou si on arrondit — au dixième,
par exemple — pour limiter la fragmentation. À décider seulement si le cache
grossit trop.

**4. Faut-il une durée de vie ?**
Une entrée d'il y a trois mois porte des prompts et des seuils qui n'existent
plus. Une expiration éviterait de servir indéfiniment du périmé, au prix d'un
paramètre de plus.

## 9. Découpage proposé

1. La table et ses accès (`get_prediction`, `put_prediction_cache`) dans les
   deux magasins, avec la sérialisation versionnée.
2. La comparaison de modèles, isolée et testée seule — c'est la partie où une
   erreur sert silencieusement un mauvais résultat.
3. Le branchement dans `BerlueService.predict`, avec le champ d'origine.
4. La purge, le scope, et les cibles make.
5. La publication `predict_cache_push`, qui réutilise la comparaison de l'étape 2.
6. L'affichage de l'origine dans Aletheia.

Les étapes 1 et 2 sont indépendantes et testables sans pipeline.
