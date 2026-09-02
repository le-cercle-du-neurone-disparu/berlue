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

Dans la suite, `PROJET_SOURCE` désigne le projet qui héberge les données —
pour l'équipe, `gen-lang-client-0242212765`.

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
make gcp_config
```

Puis, dans votre `.env` :

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

## 5. Publier votre code et déployer

```bash
make gcp_deploy_shared
```

Enchaîne la vérification des images, la publication du code, celle des modèles,
puis le déploiement des trois services. C'est `gcp_deploy` sans le build.

**Le code doit être publié avant le déploiement** : les conteneurs le lisent
depuis votre bucket au démarrage, et un bucket vide donne un conteneur qui ne
boote pas. La cible s'en charge dans le bon ordre, et refuse de déployer si
l'index RAG, le code ou les modèles manquent — l'erreur arrive tout de suite, au
lieu d'être enfouie dans les logs Cloud Run quelques minutes plus tard.

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
