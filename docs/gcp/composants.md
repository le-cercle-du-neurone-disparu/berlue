# Composants GCP

Pour chaque brique : son rôle, l'API GCP dont elle dépend, et les
commandes pour la provisionner ou la déployer. Gestion des accès :
[`share.md`](share.md).

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
Une seule fois, avant le tout premier déploiement — active aussi
l'API Artifact Registry (dans `ARTIFACT_PROJECT`) au passage :

```bash
make artifact_registry_create
make docker_auth
```

Combien de projets GCP sont impliqués (1 à 3) et lequel héberge quoi :
[`setup/gcp.md`](../setup/gcp.md#projets-gcp-jusquà-3).

## Observabilité des coûts

Active l'onglet "Cost" par service dans la Console Cloud Run (délai de
facturation avant que les données apparaissent, pas temps réel).
Provisionné par `make gcp_setup`.

Tout supprimer : [`setup/gcp.md`](../setup/gcp.md#tout-supprimer).
