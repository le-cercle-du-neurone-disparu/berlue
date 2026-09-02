# IAM à appliquer

Les cibles make existent et sont vérifiées ; **les droits eux-mêmes n'ont pas
été posés**. L'exécution a été bloquée par le contrôle de sécurité de la
session, pas par une erreur.

Projet : `gen-lang-client-0242212765`.

## 1. Accès Console pour l'équipe

Trois personnes ont déjà `roles/run.developer`, `roles/datastore.viewer` (avec
condition) et `artifactregistry.reader` au niveau du dépôt. Il leur manque de
quoi **voir les logs et lister les ressources** : sans ça, on ne peut ouvrir un
bucket, un dataset ou une base qu'en connaissant son URL exacte.

```bash
for U in lionelbos@gmail.com maximedrs1@gmail.com mouhamadtop@gmail.com; do
  make console_grant USER=$U
  make firestore_grant USER=$U FIRESTORE_ROLE=reader
done
```

`console_grant` pose trois rôles de projet, en lecture seule :

| Rôle | Débloque |
|---|---|
| `roles/logging.viewer` | les logs des services Cloud Run |
| `roles/storage.bucketViewer` | la liste des buckets |
| `roles/bigquery.metadataViewer` | la liste des datasets et des tables |

Chacun a été vérifié dans l'IAM réel — permissions listées, pas devinées.

**Pourquoi `firestore_grant` figure aussi dans la boucle.** Les collègues ont
déjà `datastore.viewer`, mais assorti d'une condition
`resource.name == ".../databases/(default)"`. Or `datastore.databases.list`
s'évalue sur le **projet**, jamais sur une base : la condition ne peut pas
correspondre, et le listing est refusé même à qui a le droit de lire. La cible
corrigée n'applique plus la condition qu'à l'écriture, et relancer le grant en
`reader` pose le binding sans condition.

Vérification attendue, depuis un des comptes concernés : les logs d'un service
Cloud Run s'affichent, et les trois listings répondent.

## 2. Compte de service d'un autre projet

À lancer quand l'adresse du compte sera connue :

```bash
make gcp_share_with_sa sa-berlue@<autre-projet>.iam.gserviceaccount.com
```

Donne la lecture du dépôt d'images, et l'**écriture** sur Firestore —
conditionnée à `(default)` — et sur BigQuery via `dataEditor` plus `jobUser`.
Ce dernier n'est pas décoratif : sans lui, `dataEditor` seul ne permet pas de
lancer une requête.

La cible refuse une adresse qui n'est pas un compte de service et renvoie vers
`gcp_share_with`.

## 3. Laisser un collègue déployer sur NOS images

Objectif : son Cloud Run tire nos images sans jamais les reconstruire — plus de
build de quinze minutes chez lui.

Il faut **deux autorisations distinctes**, et c'est le piège de cette
configuration.

**L'agent de service Cloud Run de son projet**, pour tirer l'image. Cloud Run
n'utilise PAS le compte d'exécution du service pour cette étape : il passe par
`service-<numéro-de-projet>@serverless-robot-prod.iam.gserviceaccount.com`.
N'autoriser que `sa-berlue@son-projet` laisse le déploiement échouer sur une
image introuvable.

```bash
make image_reader_grant CONSUMER_PROJECT=<id ou numéro de son projet>
```

La cible résout le numéro de projet toute seule à partir de l'identifiant. S'il
ne nous a donné qu'un numéro, elle l'accepte aussi. En cas de doute, il peut le
lire lui-même :

```bash
gcloud projects describe <son-projet> --format='value(projectNumber)'
```

**Son compte d'exécution**, s'il doit aussi lire ou écrire nos données :

```bash
make gcp_share_with_sa sa-berlue@<son-projet>.iam.gserviceaccount.com
```

### De son côté

Une ligne dans son `.env`, et plus aucun build :

```
IMAGE_SOURCE_PROJECT=gen-lang-client-0242212765
```

Puis `make image_source_check` pour vérifier que les images sont lisibles avant
de déployer — sans quoi l'échec arrive tard, sur une erreur de permission peu
parlante.

### Vérification

Notre dépôt n'autorise aujourd'hui que trois humains en lecture. Aucun agent de
service externe n'y figure : la configuration reste entièrement à poser.

## 4. Image tirée d'un autre projet (le cas inverse)

Seulement si on branche `IMAGE_SOURCE_PROJECT` sur un projet tiers. À lancer
**par quelqu'un ayant les droits sur le projet source**, pas depuis le nôtre :

```bash
make image_source_grant     # autorise notre SA Cloud Run à lire le dépôt distant
make image_source_check     # vérifie que les images existent et sont lisibles
```

Sans ce grant, le déploiement échoue tard, sur une erreur de permission peu
parlante.

## Après application

Retirer les accès se fait par les cibles symétriques : `console_revoke`,
`gcp_unshare_with` (qui appelle désormais `console_revoke`), et
`gcp_unshare_with_sa`.

Deux branches distantes fusionnées traînent encore côté serveur, sans rapport
avec l'IAM mais à nettoyer un jour :
`feat-reorganize-gcp-setup-deploy-run-down-destroy` (PR #91) et
`feat_modif_score_fusion` (PR #95, branche d'un collègue).
