# Infra GCP

Berlue s'appuie sur GCP pour l'API en production et pour l'évaluation du
pipeline (stockage des résultats, génération LLM). Cette page est le point
d'entrée ; le détail par sujet est dans [`docs/gcp/`](../gcp/) :

- [`composants.md`](../gcp/composants.md) — Firestore, BigQuery,
  Artifact Registry, le compte de service `sa-berlue`... leur rôle,
  l'API dont ils dépendent, les commandes pour les provisionner.
- [`cloudrun.md`](../gcp/cloudrun.md) — les services Cloud Run (éval,
  Ollama, API) : déploiement, coût, usage de chacun.
- [`auth.md`](../gcp/auth.md) — la session `gcloud` CLI à gérer soi-même,
  et l'impersonation systématique de `sa-berlue` au runtime (local comme
  Cloud Run).
- [`share.md`](../gcp/share.md) — donner ou retirer l'accès à une
  personne (lancer l'éval, déployer, ou juste consulter les données à la
  main).

## Démarrage rapide

### Prérequis (à faire une fois, à la main)

1. Un **projet GCP** (le vôtre — chacun le sien, cf. section suivante) et un
   **compte de facturation lié** : sans lui, Cloud Run, Artifact Registry et
   GCS refusent tout. `gcp_setup` s'arrête d'emblée en le signalant.
2. Le **Google Cloud SDK** installé (`gcloud` + `bq`) :
   <https://cloud.google.com/sdk/docs/install>.
3. `GCP_PROJECT` renseigné dans `.env` — créé par `make local_setup`, cf.
   [`local-setup.md`](local-setup.md).

### Puis

```bash
make gcp_auth
```

```bash
make gcp_setup
```

Provisionne **tout ce dont Berlue a besoin** sur le projet, et rien qui
coûte en continu :

- active les API (Cloud Run, Firestore, BigQuery, Compute, Artifact
  Registry, et les API IAM/Storage par principe)
- crée la base Firestore (mode Native) et le dataset BigQuery
- crée le compte de service `sa-berlue` et lui accorde ses droits
  Firestore/BigQuery, plus les droits nécessaires à votre compte pour le
  déployer et le tester par impersonation
- crée le dépôt Artifact Registry, vous accorde le droit d'y pousser et
  configure l'authentification Docker
- crée le bucket de l'index RAG et autorise `sa-berlue` à le lire
- active l'observabilité des coûts Cloud Run
- termine par `make gcp_doctor`

`gcp_setup` est **rejouable** : relancé, il saute ce qui existe déjà et ne
provoque aucune erreur. C'est le bon réflexe après avoir changé de projet
ou en cas de doute.

Détail de chaque brique dans [`composants.md`](../gcp/composants.md).

### Vérifier

```bash
make gcp_doctor
```

Contrôle brique par brique que l'infra est réellement **utilisable** (pas
seulement créée) : API activées, lecture/écriture Firestore et BigQuery,
impersonation de `sa-berlue`, dépôt d'images et authentification Docker,
bucket RAG. Ne s'arrête pas à la première erreur — on veut la liste
complète de ce qui manque — et nomme pour chaque ligne la commande qui
répare.

## Ce que `gcp_setup` ne fait pas

Volontairement : ce sont les étapes coûteuses ou lentes, à déclencher en
connaissance de cause. `gcp_doctor` les rappelle à chaque exécution.

1. **Demander le quota GPU.** Un projet neuf a **0** en « Total Nvidia L4 GPU
   allocation, per project per region » (europe-west1) :
   `cloudrun_llm_deploy` échouera tant que la demande n'est pas accordée
   (console GCP, délai possible de plusieurs heures). À demander tôt.
2. **Build/push des images et création des services Cloud Run** —
   `make gcp_deploy` (cf. ci-dessous). Les services créés sont à
   `min-instances=0` : c'est `gcp_up`/`gcp_eval_up` qui déclenchent le coût, cf.
   [`cloudrun.md`](../gcp/cloudrun.md).
3. **Remplir le bucket RAG** — `download_fever_data_full`,
   `build_fever_index`, `rag_index_upload` (le bucket est créé, son contenu
   non).

Hors périmètre aussi, parce que le code ne s'en sert pas aujourd'hui : le
bucket MLOps `BUCKET_NAME` (`gcs_create_bucket`) et le compte de service de
la VM (`iam_setup_service_account`, créé à la demande par `vm_create`).

## Les quatre barreaux, dans l'ordre

```bash
make gcp_setup                            # l'infra : gratuit, rejouable, une fois
make gcp_deploy                           # les images + les 3 services (CLOUDRUN_ENV=test)

# puis, selon l'usage — À PARTIR D'ICI ÇA COÛTE (GPU L4 dans les deux cas) :
make gcp_up       WARM_MODELS="llama3.1:8b"   # produit    : berlue-api-<env> + berlue-llm
make gcp_eval_up  WARM_MODELS="llama3.1:8b"   # évaluation : berlue-eval      + berlue-llm

make gcp_down                             # éteint les 3, en fin de session
```

`gcp_deploy` = `docker_build_push_all` (les 3 images) puis
`cloudrun_deploy_all` (les 3 services, dans l'ordre imposé : `berlue-llm`
d'abord, parce que le déploiement de l'API lit son URL pour câbler
`BERLUE_OLLAMA_HOST`). Les services créés sont à `min-instances=0` — ils
existent, ils ne coûtent rien tant qu'aucune requête n'arrive et tant que
`gcp_up`/`gcp_eval_up` n'ont pas forcé une instance chaude. Ces deux-là
montent chacun `berlue-llm` (le GPU) en plus de leur service : détail et
répartition dans [`cloudrun.md`](../gcp/cloudrun.md).

Seule l'API est déclinée par environnement (`berlue-api-test/staging/prod`) :
le service d'éval et le service Ollama sont **uniques pour le projet** et
partagés par les trois. Promouvoir l'API d'un environnement à l'autre ne
rebuilde rien — c'est la même image `:prod` redéployée ailleurs :

```bash
make cloudrun_deploy CLOUDRUN_ENV=staging
```

## Projets GCP (jusqu'à 3)

- **`GCP_PROJECT`** (`.env`, personnel) — VM, BigQuery, buckets
  personnels, services Cloud Run test/staging/prod. Firestore et BigQuery
  de l'éval y vivent toujours, pas d'override possible.
- **`ARTIFACT_PROJECT`** — projet qui héberge le dépôt Artifact Registry
  (images Docker : API, éval, Ollama). Défaut : `GCP_PROJECT`.
- **`BUCKET_PROJECT`** — projet qui héberge les buckets d'équipe
  (partagés, distincts des buckets personnels). Défaut : `GCP_PROJECT`.

Par défaut les 3 valent `GCP_PROJECT` : tout vit dans le projet personnel
de chacun. Le jour où l'équipe crée des projets partagés (pour centraliser
images/buckets plutôt que dupliquer par développeur), chacun ajoute dans
son `.env` :

```bash
ARTIFACT_PROJECT=<id-du-projet-partagé>
BUCKET_PROJECT=<id-du-projet-partagé>
```

Rien d'autre à changer — les cibles `docker_build_*`/`docker_push_*`/
`artifact_registry_*` utilisent déjà `ARTIFACT_PROJECT` pour le registre.
Le service Cloud Run, lui, tourne toujours dans `GCP_PROJECT`
(`--project` sur `cloudrun_deploy`) — seule l'image vient d'un projet
potentiellement différent.

## Tout supprimer

```bash
make gcp_destroy
```

Supprime tout ce qui est **déployé** : les 5 services Cloud Run
(`berlue-api-test/staging/prod`, `berlue-eval-mocked-service`,
`berlue-llm`), le dépôt Artifact Registry et ses images, le bucket RAG.
Demande une confirmation explicite (taper `oui`). **Conserve** Firestore,
BigQuery et `sa-berlue` — donc les données d'éval.

```bash
make gcp_destroy_all
```

En plus : la base Firestore, le dataset BigQuery et `sa-berlue` — c'est
l'inverse exact de `gcp_setup`, et ça **détruit toutes les données
d'éval**, irrécupérables. Confirmation par l'ID du projet.
