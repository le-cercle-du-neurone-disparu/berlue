# Authentification GCP

La session CLI de `gcloud` est le seul credential à gérer soi-même —
utilisée par les commandes `gcloud`/`bq`/`make cloudrun_*`... Expire
séparément d'un éventuel login navigateur déjà ouvert ailleurs.

```bash
make gcp_auth
```

Vérifie que la session est réellement utilisable
(`gcloud auth print-access-token`, qui échoue bien quand le token a expiré
ou qu'une réauth est exigée) et ne relance le login interactif (ouvre le
navigateur) que si nécessaire. Étant interactif, à lancer depuis votre
propre terminal, pas via un script non-interactif.

Ce test ne touche **volontairement aucune API du projet**. L'ancienne
version interrogeait Cloud Run : sur un projet où `run.googleapis.com`
n'est pas encore activée — donc exactement le projet neuf que `gcp_setup`
doit provisionner — elle échouait en accusant l'authentification, `gcloud`
proposait d'activer l'API de façon interactive, et la recette gelait sur
une question invisible. Corollaire tenu partout depuis : toute commande
`gcloud`/`bq` lancée par une recette reçoit `</dev/null`, pour qu'une
question fasse échouer plutôt que bloquer.

L'accessibilité du **projet** est un second test, distinct (« projet
inaccessible » n'est pas « pas connecté ») : `make gcp_preflight` enchaîne
les deux, plus la présence des outils, `GCP_PROJECT` et la facturation.

```bash
make gcp_check_cli_auth
```

Vérification seule, sans fix : `exit 1` + message clair si pas connecté.
Prévue pour être mise en prérequis d'autres cibles (`cloudrun_deploy`,
`gcp_setup`, `gcp_destroy`, les cibles Firestore...). Résultat mis en
cache 10 min (`/tmp/.berlue-gcp-cli-auth-ok-<projet>`).

## Au runtime : impersonation systématique de `sa-berlue`

`GcpResultStore` (`EVAL_STORE_TARGET=gcp`) s'authentifie toujours comme le
compte de service `sa-berlue` :

- **En local** : impersonation explicite de `sa-berlue` via la session
  `gcloud` CLI — nécessite `roles/iam.serviceAccountTokenCreator` sur ce
  SA, accordé automatiquement à soi-même par `make gcp_setup`.
- **Sur Cloud Run** (service ou job attaché à `sa-berlue`) : l'identité
  est déjà `sa-berlue`, pas besoin d'impersonation.

Dans les deux cas, **jamais la session humaine directement** — décidé
pour la cohérence local/prod : ce qui tourne en local est borné aux
mêmes permissions que ce qui tournera une fois déployé, jamais plus
large. Rôles du SA lui-même :
[`composants.md`](composants.md#compte-de-service-cloud-run-sa-berlue).

Tester les droits du SA sans déployer, par impersonation (chemin local) —
confirmé en conditions réelles (écriture/lecture Firestore, requête
BigQuery) :

```bash
# gcloud (et curl, avec le token qu'il imprime) : --impersonate-service-account
gcloud auth print-access-token --impersonate-service-account=sa-berlue@${GCP_PROJECT}.iam.gserviceaccount.com
```

```bash
# bq : pas de flag d'impersonation direct sur toutes les versions du CLI —
# passer par la config gcloud active, à annuler après usage
gcloud config set auth/impersonate_service_account sa-berlue@${GCP_PROJECT}.iam.gserviceaccount.com
bq query --use_legacy_sql=false "SELECT 1"
gcloud config unset auth/impersonate_service_account
```

Diagnostic complet des accès — `gcp_doctor` sonde Firestore et BigQuery **en
impersonant `sa-berlue`**, comme le fait le runtime, et non avec votre compte
humain dont les droits ne préjugent de rien :

```bash
make gcp_doctor
```

L'octroi **et** le retrait d'un accès (`cloudrun_sa_grant`/`_revoke`,
`bigquery_grant`/`firestore_grant`, ou `iam_setup_cloudrun_service_account`
— cf. [`share.md`](share.md)) mettent jusqu'à ~1 minute à se propager
(vérifié en conditions réelles) — un `PERMISSION_DENIED` juste après ou
une impersonation qui réussit encore juste après une révocation ne sont
pas forcément un vrai problème, réessayer avant de creuser.
