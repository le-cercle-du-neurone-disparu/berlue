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

`GCP_PROJECT` configuré dans `.env` (cf.
[`local-setup.md`](local-setup.md)), puis :

```bash
make gcp_auth
```

```bash
make gcp_setup
```

Provisionne tout ce dont le projet Berlue a besoin :

- active les API Firestore, BigQuery et Cloud Run
- crée la base Firestore (mode Native) et le dataset BigQuery
- crée le compte de service `sa-berlue` et lui accorde ses droits
  Firestore/BigQuery, plus les droits nécessaires à votre compte pour le
  déployer et le tester par impersonation
- active l'observabilité des coûts Cloud Run

L'API Artifact Registry, elle, s'active toute seule au premier
`make artifact_registry_create` (dans `ARTIFACT_PROJECT`, potentiellement
différent de `GCP_PROJECT` — cf. section suivante).

Détail de chaque brique dans [`composants.md`](../gcp/composants.md).

Pour déployer un service (API, Job d'éval, service Ollama), voir
[`cloudrun.md`](../gcp/cloudrun.md).

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

Supprime les 3 services Cloud Run de l'API + le dépôt Artifact Registry
(et les images qu'il contient). Demande une confirmation explicite (taper
`oui`) avant d'agir — action irréversible. Ne touche à rien d'autre sur le
projet GCP (Firestore, BigQuery, buckets, VM, service Ollama, Job
d'éval...).
