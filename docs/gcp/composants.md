# Composants GCP

Pour chaque brique : son rôle, l'API GCP dont elle dépend, et les
commandes pour la provisionner ou la déployer. Tout est provisionné en une
fois par `make gcp_setup` ([`setup/gcp.md`](../setup/gcp.md)) et vérifié par
`make gcp_doctor` ; les commandes unitaires ci-dessous servent à réparer un
point précis. Gestion des accès : [`share.md`](share.md).

## Firestore

Store des résultats de l'éval quand `EVAL_STORE_TARGET=gcp`. Une seule
base par projet, mode Native. Provisionné par `make gcp_setup` (cf.
[`setup/gcp.md`](../setup/gcp.md)).

## BigQuery

Dataset `berlue` du projet — matrices d'éval (`eval_matrices`,
`eval_matrices_generated_berlue`, `eval_matrices_generated_baseline`).
Provisionné par `make gcp_setup`.

## Compte de service Cloud Run (`sa-berlue`)

Identité attachée au service Cloud Run pour qu'il puisse lire/écrire
Firestore et BigQuery — évite de lui laisser le compte de service par
défaut du projet (souvent trop large). Créé par `make gcp_setup`, avec
ses droits Firestore/BigQuery. Détail de l'authentification et de
l'impersonation systématique : [`auth.md`](auth.md).

`cloudrun_deploy` attache `sa-berlue` par défaut
(`CLOUDRUN_SERVICE_ACCOUNT`, surchargeable — `CLOUDRUN_SERVICE_ACCOUNT=`
vide pour revenir au SA par défaut du projet).

Le Job et les services Cloud Run eux-mêmes (éval, Ollama, API) ont leur
propre page : [`cloudrun.md`](cloudrun.md).

## Artifact Registry

Dépôt d'images Docker (image API `:prod`, image d'éval, image Ollama).
Provisionné par `make gcp_setup` : API activée dans `ARTIFACT_PROJECT`,
dépôt créé, droit de push accordé à votre compte et authentification
Docker configurée. Les commandes unitaires restent utiles pour réparer un
point précis (ce que `gcp_doctor` indique le cas échéant) :

```bash
make artifact_registry_create
make artifact_registry_role
make docker_auth
```

Combien de projets GCP sont impliqués (1 à 3) et lequel héberge quoi :
[`setup/gcp.md`](../setup/gcp.md#projets-gcp-jusquà-3).

## Bucket de l'index RAG

Bucket GCS dédié (`RAG_BUCKET_NAME`), monté en volume GCS FUSE par
`cloudrun_deploy` — dédié plutôt que mélangé aux autres données, parce
qu'un volume GCS FUSE monte **tout** le contenu d'un bucket. Créé par
`make gcp_setup`, avec l'autorisation de lecture pour `sa-berlue`. Son
**contenu** est à part : `make build_fever_index` puis
`make rag_index_upload`, cf. [`cloudrun.md`](cloudrun.md).

## API GCP

Activées en un seul appel par `make gcp_setup` (cible `gcp_enable_apis`) :

| API | Ce qui en dépend |
|---|---|
| `run.googleapis.com` | les 5 services Cloud Run |
| `firestore.googleapis.com` | cache des résultats d'éval |
| `bigquery.googleapis.com` | matrices d'éval |
| `artifactregistry.googleapis.com` | dépôt d'images (dans `ARTIFACT_PROJECT`) |
| `compute.googleapis.com` | GPU L4 de `berlue-llm`, VM |
| `appoptimize.googleapis.com` | onglet « Cost » par service Cloud Run |
| `iam`, `iamcredentials`, `cloudresourcemanager`, `storage` | création du compte de service, impersonation, bindings IAM, buckets |

Les quatre dernières sont listées par principe : mesurées `DISABLED` sur un
projet où l'impersonation, la création de compte de service, les bindings
IAM et les buckets fonctionnent pourtant — GCP les traite comme disponibles
sans activation explicite. Les activer ne coûte rien et rend la dépendance
lisible ; n'en attendre aucun déblocage.

## Observabilité des coûts

Active l'onglet "Cost" par service dans la Console Cloud Run (délai de
facturation avant que les données apparaissent, pas temps réel).
Provisionné par `make gcp_setup` — du confort : son échec est un simple
avertissement, il n'interrompt pas le provisionnement.

Tout supprimer : [`setup/gcp.md`](../setup/gcp.md#tout-supprimer).
