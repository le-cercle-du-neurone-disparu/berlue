# Déployer Berlue sur son projet, sans rien reconstruire

Comment monter l'API et le service LLM sur **votre** projet GCP en réutilisant
les images, l'index RAG et les modèles d'un projet qui les héberge déjà.

Ce que ça vous épargne :

| Étape évitée | Coût habituel |
|---|---|
| build et push des deux images Docker | ~15 min, et un Docker qui marche |
| téléchargement de FEVER et calcul de l'index | 371 Mo puis 109 810 embeddings |
| téléchargement des poids HuggingFace | ~2,1 Go |

Ce qui reste à vous : votre infrastructure (buckets, base Firestore, compte de
service) et votre code. Tout tourne chez vous, sur votre facturation.

Dans la suite, `PROJET_SOURCE` désigne le projet qui héberge les images, l'index
et les modèles. Son propriétaire vous en donnera l'identifiant.

## 1. Ce que le propriétaire doit vous accorder

Deux autorisations, à lui demander une fois.

**Pour tirer les images.** Lancez chez vous :

```bash
make image_reader_request
```

Elle affiche la ligne exacte à lui envoyer. Il la lance de son côté.

Le compte à autoriser n'est pas celui qu'on croit : Cloud Run tire ses images
avec son **agent de service**, `service-<numéro>@serverless-robot-prod`, et non
avec le compte d'exécution du service. Et le numéro de projet n'est lisible que
depuis votre projet — d'où cette commande, qui évite un aller-retour.

**Pour lire l'index et les modèles**, il lance :

```bash
make data_buckets_grant USER=<votre email>
```

## 2. Votre configuration

```bash
make gcp_auth
```

Puis, dans votre `.env`, en plus de `GCP_PROJECT` qui doit désigner **votre**
projet :

```
IMAGE_SOURCE_PROJECT=<PROJET_SOURCE>
```

C'est la seule ligne qui change par rapport à une installation ordinaire. Elle
détourne les trois déploiements Cloud Run vers le dépôt d'images du projet
source, sans rien changer à l'endroit où **vous** poussez si vous construisez un
jour vos propres images.

## 3. Votre infrastructure

```bash
make gcp_setup
```

Crée chez vous les APIs, la base Firestore, le dataset BigQuery, le compte de
service et les trois buckets — RAG, code, modèles. Rejouable sans risque, et ne
crée aucun service Cloud Run : rien n'est facturé à cette étape.

## 4. Importer les données lourdes

```bash
make rag_index_import RAG_SOURCE_BUCKET=<PROJET_SOURCE>-berlue-rag
make models_import    MODELS_SOURCE_BUCKET=<PROJET_SOURCE>-berlue-models
```

La copie se fait **de bucket à bucket** : rien ne transite par votre poste, et
une petite machine suffit. C'est le remplaçant de
`download_fever_data_full && build_fever_index && rag_index_upload`, qui exige
de calculer 109 810 embeddings en local.

## 5. Publier votre code, puis déployer

**Les images ne contiennent pas le code de Berlue.** Elles n'embarquent que les
dépendances : au démarrage, chaque conteneur copie le code Python depuis *votre*
bucket, monté en volume. C'est ce qui permet de changer une ligne de Python sans
reconstruire d'image — et ça veut dire qu'un bucket de code vide donne un
conteneur qui ne démarre pas.

Le code doit donc être publié **avant** tout déploiement :

```bash
make code_push          # publie votre code dans gs://<votre-projet>-berlue-code
make gcp_deploy_shared  # vérifie les images, publie code et modèles, déploie
```

`gcp_deploy_shared` refait `code_push` de lui-même, donc l'appeler seul suffit —
la première commande est là pour que l'ordre soit clair, et parce qu'on la
relancera seule à chaque changement de Python (cf. `code_deploy`).

La cible enchaîne : vérification des images, publication du code, publication
des modèles, déploiement des trois services. C'est `gcp_deploy` sans le build.

Elle refuse de partir si `IMAGE_SOURCE_PROJECT` n'est pas configuré, et le
déploiement lui-même refuse si l'index RAG, le code ou les modèles manquent —
l'erreur arrive tout de suite, au lieu d'être enfouie dans les logs Cloud Run
quelques minutes plus tard.

## 6. Allumer, et éteindre

```bash
make gcp_up WARM_MODELS="llama3.2:3b llama3.1:8b"
```

Monte les services à `min-instances=1` et charge les modèles en VRAM. **Le GPU
L4 est facturé en continu** à partir de là.

```bash
make gcp_down
```

Le seul arrêt garanti de la facturation. À lancer dès que vous avez fini.

## En cas de problème

```bash
make image_source_check   # les images sont-elles lisibles depuis votre projet ?
make gcp_doctor           # l'infra est-elle complète et utilisable ?
make gcp_status           # que tourne-t-il, et qu'est-ce qui est facturé ?
```

`gcp_status` distingue deux choses qu'on confond volontiers : `min-instances`,
qui est une configuration, et le nombre d'instances réellement en vie, qui est
ce que vous payez. Repasser `min-instances` à 0 ne tue pas une instance déjà
démarrée.
