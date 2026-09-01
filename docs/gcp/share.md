# Partage d'accès

Plusieurs accès bien distincts, à ne pas confondre — celui qui fait
tourner l'éval, et ceux qui servent seulement à regarder/déployer à la
main. Mécanisme d'authentification derrière chacun :
[`auth.md`](auth.md).

## Lancer l'éval — toujours via `sa-berlue`

**Que ce soit en local (`EVAL_STORE_TARGET=gcp`) ou une fois déployé sur
Cloud Run, l'éval lit et écrit Firestore/BigQuery en impersonant
`sa-berlue`, jamais en tant que vous** (cf. [`auth.md`](auth.md)). Donc
pour qu'une personne puisse lancer l'éval en local sur ce projet, ce qui
compte est son accès à **`sa-berlue` lui-même**, pas un accès direct à
Firestore/BigQuery (section suivante) :

```bash
make cloudrun_sa_grant USER=personne@example.com                       # CLOUDRUN_SA_ROLE=impersonate par défaut
make cloudrun_sa_revoke USER=personne@example.com
make cloudrun_sa_test                                                  # vérifie son propre accès
```

`CLOUDRUN_SA_ROLE=deploy` accorde/retire plutôt `serviceAccountUser`
(pouvoir déployer Cloud Run avec ce SA, pas lancer l'éval en local).

Conséquence pour le partage inter-projets : l'accès au projet d'une
personne doit être accordé à **son `sa-berlue`**
(`serviceAccount:sa-berlue@son-projet...`), pas à son compte humain.

## Consulter les données directement — Firestore/BigQuery

`bigquery_grant`/`firestore_grant` accordent un accès **en plus**, à
votre compte humain directement (pas à `sa-berlue`) — utile pour
parcourir les données depuis la console GCP ou une requête `bq`/`gcloud`
à la main, **inutile et non pris en compte par le code d'éval
lui-même** (qui n'authentifie jamais comme vous, cf.
[`auth.md`](auth.md)). En lecture seule ou lecture+écriture, limité au
dataset BigQuery et à la base Firestore de l'éval (pas au projet
entier).

```bash
make bigquery_grant USER=personne@example.com BQ_ROLE=reader          # ou writer
make firestore_grant USER=personne@example.com FIRESTORE_ROLE=reader  # ou writer
```

Retirer l'accès (`FIRESTORE_ROLE` doit correspondre à celui accordé) :

```bash
make bigquery_revoke USER=personne@example.com
make firestore_revoke USER=personne@example.com FIRESTORE_ROLE=reader
```

`bigquery_grant`/`revoke` passent par l'ACL classique du dataset (`bq
show`/`bq update`), pas par `bq add-iam-policy-binding` — cette commande
nécessite un allowlisting non actif sur ce projet. `firestore_grant`/
`revoke` posent un rôle IAM projet (`roles/datastore.viewer`/
`.user`) avec une condition qui le restreint à la base `(default)` —
Firestore n'a pas de binding IAM scopé nativement à une base précise.

Vérifier ses propres accès directs (chacun peut lancer ça sur son
compte, une fois `make gcp_auth` fait) :

```bash
make bigquery_test_read
make bigquery_test_write
make firestore_test_read
make firestore_test_write
```

Chaque test lit/écrit une ressource jetable (table ou document préfixé
`_access_probe`) et la supprime dans la foulée.

⚠️ Ces quatre cibles sondent **votre compte humain**, pas `sa-berlue`. Leur
résultat ne dit donc rien sur le fait que l'éval fonctionnera : elle
n'authentifie jamais comme vous. Pour vérifier ce qui compte au runtime,
c'est `make gcp_doctor`, qui refait les mêmes sondes **en impersonant
`sa-berlue`**. Un Owner de projet verra ✅ ici même si `sa-berlue` n'a aucun
droit, et quelqu'un sans accès direct verra ❌ alors que l'éval tournera
parfaitement.

## Artifact Registry

Accès scopé au dépôt d'images uniquement (pas le projet entier) :

```bash
make artifact_registry_grant  USER=personne@example.com ROLE=reader   # ou writer
make artifact_registry_revoke USER=personne@example.com ROLE=writer
```

`reader`/`writer` sont traduits en rôles IAM GCP
(`artifactregistry.reader`/`.writer`).

```bash
make artifact_registry_role
```

Sans personne ciblée : accorde à *vous-même* un accès writer sur tout le
projet Artifact Registry (bootstrap initial, plus large que
`artifact_registry_grant`).

## Buckets GCS

Accès scopé à un seul bucket (nom global, pas besoin de préciser de
projet) :

```bash
make gcs_grant  BUCKET=mon-bucket USER=personne@example.com BUCKET_ROLE=reader   # ou writer
make gcs_revoke BUCKET=mon-bucket USER=personne@example.com BUCKET_ROLE=writer
```

`reader`/`writer` sont traduits en rôles IAM GCP
(`storage.objectViewer`/`.objectAdmin`).
