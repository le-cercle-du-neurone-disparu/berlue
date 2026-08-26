# Déploiement GCP

## Authentification

Deux credentials distincts sont nécessaires pour toucher à GCP : la session
CLI de `gcloud` (utilisée par les commandes `gcloud`/`make cloudrun_*`...) et
les Application Default Credentials — ADC (utilisées par les libs client
Python, ex. `google-cloud-storage`/`bigquery`). Elles expirent séparément.

```bash
make gcp_auth
```

Vérifie les deux via de **vrais appels GCP** (pas juste "un token existe") —
`gcloud run services list` pour la CLI, un appel réel `google-cloud-storage`
pour l'ADC — et ne relance le login interactif (ouvre le navigateur) que pour
celle qui échoue vraiment. Étant interactif, à lancer depuis votre propre
terminal, pas via un script non-interactif.

```bash
make gcp_check_auth
```

Vérification seule, sans fix : `exit 1` + message clair si pas connecté.
Prévue pour être mise en prérequis d'autres cibles (déjà le cas pour
`cloudrun_deploy`/`gcp_destroy`). Le résultat est mis en cache 10 min
(`/tmp/.berlue-gcp-auth-ok-<projet>`) pour ne pas refaire ces appels à chaque
cible d'un même enchaînement.

## Architecture : jusqu'à 3 projets GCP

- **`GCP_PROJECT`** (`.env`, personnel) — VM, BigQuery, buckets personnels,
  services Cloud Run test/staging/prod.
- **`ARTIFACT_PROJECT`** — projet qui héberge le dépôt Artifact Registry
  (images Docker). Défaut : `GCP_PROJECT`.
- **`BUCKET_PROJECT`** — projet qui héberge les buckets d'équipe (partagés,
  distincts des buckets personnels). Défaut : `GCP_PROJECT`.

Par défaut les 3 valent `GCP_PROJECT` : tout vit dans le projet personnel de
chacun, comportement actuel inchangé. Le jour où l'équipe crée des projets
partagés (pour centraliser images/buckets plutôt que dupliquer par
développeur), chacun ajoute dans son `.env` :

```bash
ARTIFACT_PROJECT=<id-du-projet-partagé>
BUCKET_PROJECT=<id-du-projet-partagé>
```

Rien d'autre à changer — toutes les cibles `docker_build_prod`/
`docker_push_prod`/`artifact_registry_*` utilisent déjà `ARTIFACT_PROJECT`
pour le registre. Le service Cloud Run, lui, tourne toujours dans
`GCP_PROJECT` (`--project` sur `cloudrun_deploy`) — seule l'image vient d'un
projet potentiellement différent.

## Déployer

3 environnements (test/staging/prod), 3 services Cloud Run
(`berlue-api-test`/`-staging`/`-prod`), une seule image `:prod` construite et
poussée une fois, puis promue progressivement sur les 3 :

```bash
make docker_build_prod
make docker_push_prod
make cloudrun_deploy CLOUDRUN_ENV=test
make cloudrun_deploy CLOUDRUN_ENV=staging
make cloudrun_deploy CLOUDRUN_ENV=prod
```

`make cloudrun_url CLOUDRUN_ENV=...` pour récupérer l'URL de chaque environnement.

Accès public par défaut, contrôlé par environnement dans `make/config.mk` :

```makefile
CLOUDRUN_PUBLIC_test = true
CLOUDRUN_PUBLIC_staging = true
CLOUDRUN_PUBLIC_prod = true
```

Repasser un flag à `false` + relancer `cloudrun_deploy` pour cet environnement
verrouille l'accès derrière IAM (`--no-allow-unauthenticated`).

Supprimer un seul environnement (sans toucher aux autres ni au dépôt Artifact
Registry — pour ça, voir « Tout supprimer » plus bas) :

```bash
make cloudrun_delete CLOUDRUN_ENV=test
```

## Gestion d'accès

Accès accordé/retiré par personne, scope = une seule ressource (pas le projet
entier) :

```bash
# Artifact Registry (le dépôt uniquement)
make artifact_registry_grant  USER=personne@example.com ROLE=reader   # ou writer
make artifact_registry_revoke USER=personne@example.com ROLE=writer

# Bucket GCS (un bucket précis — nom global, pas besoin de préciser de projet)
make gcs_grant  BUCKET=mon-bucket USER=personne@example.com BUCKET_ROLE=reader   # ou writer
make gcs_revoke BUCKET=mon-bucket USER=personne@example.com BUCKET_ROLE=writer
```

`reader`/`writer` sont traduits en rôles IAM GCP (`artifactregistry.reader`/
`.writer`, `storage.objectViewer`/`.objectAdmin`).

`artifact_registry_role` (sans personne ciblée) reste disponible à part :
accorde à *vous-même* un accès writer sur tout le projet Artifact Registry
(bootstrap initial, plus large que `artifact_registry_grant`).

## Tout supprimer

```bash
make gcp_destroy
```

Supprime les 3 services Cloud Run + le dépôt Artifact Registry (et les images
qu'il contient). Demande une confirmation explicite (taper `oui`) avant
d'agir — action irréversible. Ne touche à rien d'autre sur le projet GCP
(buckets, VM, autres services Cloud Run non-berlue...).
