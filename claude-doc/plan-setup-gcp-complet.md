# Plan — `make gcp_setup` complet et rejouable sur un projet vierge

> **Statut : plan, rien d'implémenté.** Étude faite sur la branche
> `fixup-pipeline-make-targets` (01/09). Les points marqués **[vérifié]**
> l'ont été contre GCP le 01/09 (projets `gen-lang-client-0242212765` et
> `wagon-bootcamp-2327-xm`, compte `xav@tekio.org`) ; le reste est déduit
> du code. La validation complète sur un projet neuf reste à faire, cf.
> [Recette](#6-recette--valider-sur-un-projet-vierge).

Objectif : `make gcp_setup` met en place **toute** l'infra GCP dont Berlue a
besoin, sur un projet vierge, pour une personne qui n'a jamais rien lancé —
Artifact Registry compris. Hors périmètre volontaire : le build des images
et la création des services Cloud Run (`docker_build_*`/`docker_push_*`,
`cloudrun_*_deploy`), qui restent des étapes explicites et coûteuses.

Le problème n'est pas qu'il manque des commandes : elles existent presque
toutes. C'est qu'elles ne sont pas **enchaînées**, et que celles qui le sont
supposent un projet déjà à moitié configuré — l'état du poste de Xavier.
Chaque étape idempotente court-circuite chez lui (« déjà présent, création
sautée »), donc aucun des vrais pièges d'un projet neuf n'est jamais exercé.

---

## 1. L'existant, tel qu'il est aujourd'hui

### Ce que `gcp_setup` fait (`make/gcp.mk`)

```
gcp_setup: gcp_check_cli_auth
  firestore_enable_api          run.googleapis.com     ← cloudrun_enable_api
  bigquery_enable_api           firestore.googleapis.com
  cloudrun_enable_api           bigquery.googleapis.com
  gcp_enable_compute            compute.googleapis.com
  firestore_create_database     appoptimize.googleapis.com
  bigquery_create_dataset
  iam_setup_cloudrun_service_account
  gcp_enable_cost_observability
  rag_bucket_create
  rag_bucket_grant_sa
```

### Ce qu'il ne fait pas, alors que le projet en a besoin

| Brique | Cible existante | Appelée par `gcp_setup` ? |
|---|---|---|
| API Artifact Registry | `artifact_registry_enable_api` | ❌ |
| Dépôt Docker `berlue-repo` | `artifact_registry_create` | ❌ |
| Droit de push sur le dépôt (soi-même) | `artifact_registry_role` | ❌ |
| Auth Docker → `*-docker.pkg.dev` | `docker_auth` | ❌ |
| API `iamcredentials` / `iam` | *(aucune)* | ❌ (impact réel faible, cf. 2.4) |
| `gcloud config set project` | *(aucune)* | ❌ |
| Vérification facturation liée au projet | *(aucune)* | ❌ |
| Vérification finale des accès | `cloudrun_sa_test`, `*_test_read/write` | ❌ (manuel) |

`docs/setup/gcp.md` assume explicitement le trou Artifact Registry :
« L'API Artifact Registry, elle, s'active toute seule au premier
`make artifact_registry_create` » — c'est vrai, mais personne ne dit à un
nouvel arrivant de lancer cette commande avant son premier `docker_push`.

### Ce qui n'est *pas* nécessaire, et doit le rester

- **`gcs_create_bucket` / `BUCKET_NAME`** (bucket MLOps personnel) :
  `berlue/ml_logic/registry.py` lève `NotImplementedError` sur toutes les
  branches `MODEL_TARGET=gcs`, et `params.BUCKET_NAME` n'est lu nulle part
  ailleurs dans `berlue/`. Ce bucket ne sert à rien aujourd'hui → hors
  `gcp_setup`, on ne provisionne pas du mort.
- **`iam_setup_service_account` / `SA_NAME` (`berlue-vm-sa`)** : identité de
  la VM Compute Engine, créée à la demande par `vm_create`. Pas sur le
  chemin de l'API ni de l'éval → reste hors `gcp_setup`.
- **`vm_*`** : la VM n'est pas une dépendance du produit.

---

## 2. Où ça casse pour un nouvel arrivant, dans l'ordre

Parcours réel : nouveau compte, nouveau projet GCP, clone frais.

### 2.1 Blocage à l'amorçage — `gcp_check_cli_auth` exige une API pas encore activée **[vérifié]**

La cause racine du « ça marche chez moi ». `make/gcp.mk` :

```make
_gcp_check_cli_auth:
	@gcloud run services list --project=$(GCP_PROJECT) --region=$(GCP_REGION) >/dev/null 2>&1
```

Sur un projet où `run.googleapis.com` n'est pas activée, cette commande
échoue — pas parce que l'auth est mauvaise. Reproduit le 01/09 sur
`wagon-bootcamp-2327-xm`, session parfaitement valide :

```
API [run.googleapis.com] not enabled on project [wagon-bootcamp-2327-xm]. Would
you like to enable and retry (this will take a few minutes)? (y/N)?
ERROR: (gcloud.run.services.list) … Cloud Run Admin API has not been used in
project wagon-bootcamp-2327-xm before or it is disabled.
                                                    → code de sortie 1
```

Deux effets, le premier pire que le second :

1. **`gcloud` pose une question interactive.** La recette redirige
   `>/dev/null 2>&1` mais **pas `stdin`** : la question est invisible et le
   `make` **reste bloqué** en attendant une réponse que l'utilisateur ne
   voit pas. Pas un message d'erreur — un gel.
2. Stdin fermé (script, CI), la commande sort en `1`, et la chaîne se
   déroule à l'envers :
   - `gcp_check_cli_auth` → `exit 1` avec le message trompeur « CLI gcloud
     non authentifiée … Lancez `make gcp_auth` » ;
   - `gcp_auth` → relance `gcloud auth login` **alors que la session est
     bonne**, et échoue encore juste après ;
   - `gcp_setup` a `gcp_check_cli_auth` en prérequis → **il ne peut jamais
     tourner**, alors que c'est lui qui activerait l'API manquante.

Boucle fermée : la seule cible qui active Cloud Run exige Cloud Run activé.
Chez Xavier, l'API est activée depuis des semaines → jamais visible.
C'est le point à corriger en premier ; à lui seul il explique qu'une
install neuve ne démarre pas.

**Correctif** : un test d'auth qui ne dépend d'aucune API activable du
projet, et qui ne peut pas poser de question. Deux niveaux, pas un :

```make
_gcp_check_cli_auth:
	@gcloud auth print-access-token >/dev/null 2>&1        # la session est-elle valide/rafraîchissable ?

_gcp_check_project:
	@gcloud projects describe $(GCP_PROJECT) >/dev/null 2>&1   # cloudresourcemanager : activée par défaut
```

`print-access-token` échoue exactement dans le cas qui nous intéresse
(session expirée / réauth Workspace exigée) et réussit sur un projet
vierge. Le second niveau donne un message distinct et utile : « projet
inaccessible ou inexistant » ≠ « pas connecté ».

**Règle générale à appliquer partout dans `gcp_setup`** : toute commande
`gcloud`/`bq` lancée par une recette reçoit `</dev/null`. Une commande qui
attend une réponse doit échouer, jamais geler — c'est ça qui a rendu le
symptôme incompréhensible.

### 2.2 `GCP_PROJECT` vide ou projet gcloud non positionné

Aucune cible ne vérifie que `GCP_PROJECT` est renseigné. Vide, on passe
`--project=` à gcloud et on récolte des erreurs incompréhensibles.
`gcloud config set project` n'est jamais fait non plus, alors que
`scripts/setup_env.sh` propose `gcloud config get-value project` comme
valeur par défaut de `.env` — l'œuf et la poule pour qui n'a jamais
configuré gcloud.

### 2.3 Facturation non liée

Cloud Run, Artifact Registry et GCS refusent tout sur un projet sans compte
de facturation. L'erreur gcloud est explicite mais arrive au milieu de
`gcp_setup`, après des étapes réussies — état à moitié provisionné.
À vérifier **avant** d'agir.

### 2.4 API `iam`/`iamcredentials` jamais activées — *pas* le blocage attendu **[vérifié]**

Hypothèse de départ : l'impersonation, dont tout le runtime GCP dépend,
casserait faute d'`iamcredentials.googleapis.com`.
**Mesuré, c'est faux** — sur `gen-lang-client-0242212765`, les deux API
sont rapportées `DISABLED` par `gcloud services list`, et pourtant
l'impersonation de `sa-berlue` réussit, et `sa-berlue` a bien pu être créé
sans `iam.googleapis.com`. GCP les traite comme disponibles sans activation
explicite. Même constat pour `cloudresourcemanager` et `storage`, absentes
de la liste des API activées alors que les bindings IAM projet et les
buckets fonctionnent.

À retenir : les ajouter à `gcp_enable_apis` reste une assurance gratuite et
idempotente, **mais ce n'est pas le correctif qui débloque un nouvel
arrivant** — ne pas s'arrêter là en croyant le problème réglé. Le blocage
réel est 2.1.

Le contexte, qui reste utile à garder en tête :
`berlue/evaluation/gcp_result_store.py` s'authentifie **systématiquement**
par impersonation :

```python
cmd = ["gcloud", "auth", "print-access-token", "--impersonate-service-account", EVAL_SERVICE_ACCOUNT]
```

et `make/cloudrun.mk` fait pareil pour chaque appel
(`cloudrun_eval_service_invoke`, `gcp_up`, `gcp_verify_warm`,
`ollama_load_test_gcp` : `gcloud auth print-identity-token
--impersonate-service-account`). Ce chemin dépend de `sa-berlue` et du rôle
`serviceAccountTokenCreator` — ça, `gcp_setup` le pose déjà, et
`gcp_doctor` (Phase 4) doit le vérifier plutôt que le supposer.

### 2.5 Propagation : les créations neuves échouent là où les idempotentes passent

Deux fenêtres de cohérence éventuelle que le poste de Xavier n'exerce
jamais (tout existe déjà, chaque étape court-circuite) :

- **compte de service** : `gcloud iam service-accounts create` suivi
  immédiatement de `add-iam-policy-binding` sur ce même SA → régulièrement
  « Service account … does not exist » pendant quelques secondes.
  `iam_setup_cloudrun_service_account` enchaîne les deux sans attente.
- **activation d'API** : `firestore databases create` juste après
  `services enable firestore.googleapis.com` peut être refusé le temps que
  l'activation se propage.

**Correctif** : une petite fonction de retry (N tentatives espacées),
appliquée aux quelques commandes concernées — pas partout.

`docs/gcp/auth.md` documente déjà la propagation IAM (~1 min) côté
*accès accordé à une personne*. Même mécanique, autre symptôme.

### 2.6 `gcloud config get-value account` comme source d'identité

`iam_setup_cloudrun_service_account` et `artifact_registry_role` font :

```make
--member="user:$$(gcloud config get-value account)"
```

Si `core/account` n'est pas positionné, on envoie `user:` (ou
`user:(unset)`) et gcloud rejette. Plus robuste :
`gcloud auth list --filter=status:ACTIVE --format='value(account)'`, avec
échec explicite si vide.

### 2.7 `bq` en première utilisation — précaution, pas un bug constaté **[vérifié]**

Piste écartée : `bq` déroulerait son assistant (« Welcome to BigQuery! … »)
sans `~/.bigqueryrc` et bloquerait la recette. **Testé** — `~/.bigqueryrc`
n'existe pas sur le poste de Xavier et `bq ls --project_id=…` répond
directement, sans question ni création de fichier. Les cibles passent déjà
`--project_id` partout, ce qui suffit.

Reste une précaution à coût nul, à appliquer par principe sur tout ce que
`gcp_setup` lance sans supervision : ajouter `--headless` aux invocations
`bq` (`bigquery_create_dataset`, `bigquery_test_*`,
`scripts/bigquery_dataset_access.py`) pour qu'une version future qui
poserait une question échoue au lieu de geler. Même raisonnement que 2.1,
dont le vrai dégât était le gel silencieux, pas l'erreur.

### 2.8 Aucune vérification finale

`gcp_setup` affiche « ✅ Infra GCP prête » sans avoir rien testé. Les
sondes existent pourtant (`cloudrun_sa_test`, `firestore_test_read/write`,
`bigquery_test_read/write`) mais restent manuelles et documentées ailleurs
(`docs/gcp/share.md`). Un `gcp_doctor` manque, et c'est lui qui transforme
« ça a l'air passé » en « c'est prêt ».

### 2.9 `.env` : ce que le script écrit ≠ ce que le projet lit

`scripts/setup_env.sh` écrit `TEST_ENV` — **lu par personne** (aucune
occurrence dans `berlue/`, `make/`, `tests/`, `docs/`). Et il n'écrit pas
`PORT`, `USE_MOCK`, `BERLUE_LOG_LEVEL`, `EXTRACT_MODEL`, présents dans
`.env.sample`. Troisième version encore ailleurs :
`tests/infrastructure/test_env.py` échoue en disant « Avez-vous lancé
`cp .env.sample .env` ? ». Trois sources de vérité pour un seul fichier.

### 2.10 `gcp_destroy` n'est pas le miroir de `gcp_setup`

Aujourd'hui il supprime les 3 Cloud Run `berlue-api-*`, le dépôt Artifact
Registry et le bucket RAG. Il ne touche pas à `berlue-eval-mocked-service`,
`berlue-llm`, Firestore, BigQuery, ni au compte de service — alors que
`gcp_setup` crée les trois derniers. Une fois `gcp_setup` élargi, l'écart
grandit encore.

---

## 3. Cible

```
make gcp_setup
  ├─ gcp_preflight              (nouveau) outils, .env, session, projet, facturation
  ├─ gcp_enable_apis            (nouveau) 1 seul appel, liste complète
  ├─ firestore_create_database  (+ retry)
  ├─ bigquery_create_dataset    (+ --headless)
  ├─ iam_setup_cloudrun_service_account   (+ retry SA, compte actif fiable)
  ├─ artifact_registry_create   (existant, jamais appelé jusqu'ici)
  ├─ artifact_registry_role     (existant, jamais appelé jusqu'ici)
  ├─ docker_auth                (existant, jamais appelé — sauté si pas de docker)
  ├─ rag_bucket_create
  ├─ rag_bucket_grant_sa
  ├─ gcp_enable_cost_observability
  └─ gcp_doctor                 (nouveau) vérifie, puis dit ce qui reste à faire à la main
```

Invariants à tenir :

- **rejouable** — deuxième `gcp_setup` = aucune erreur, aucun effet de bord
  (déjà l'esprit de `48ede29`, à étendre aux nouvelles étapes) ;
- **échoue tôt et clairement** — un préflight qui nomme la cause plutôt
  qu'une erreur gcloud au milieu du parcours ;
- **ne crée rien de facturé en continu** — pas de Cloud Run, pas de GPU, pas
  de `min-instances`. Un dépôt Artifact Registry vide, un bucket vide, une
  base Firestore vide, un dataset BigQuery vide : gratuit ou négligeable.

---

## 4. Phases

### Phase 1 — Débloquer l'amorçage *(sans ça, rien d'autre ne sert)*

1. `_gcp_check_cli_auth` → `gcloud auth print-access-token` (2.1).
2. Nouveau `_gcp_check_project` → `gcloud projects describe`, message
   distinct.
3. `gcp_auth` : ne relance `gcloud auth login` que sur un vrai échec de
   session ; si la session est bonne mais le projet inaccessible, le dire
   au lieu de relancer un login qui n'y changera rien.
4. Nouveau `gcp_preflight` (prérequis de `gcp_setup`) :
   - `gcloud` et `bq` présents dans le `PATH` ;
   - `GCP_PROJECT` non vide (sinon : « renseignez `GCP_PROJECT` dans `.env`
     — cf. `make local_setup` ») ;
   - session valide + projet accessible (points 1-2) ;
   - compte actif récupéré via `gcloud auth list` et exporté pour les
     bindings IAM (2.6) ;
   - **facturation** : `gcloud beta billing projects describe $(GCP_PROJECT)
     --format="value(billingEnabled)"` → `True` **[vérifié : la commande
     répond bien sur le projet de Xavier]**, sinon échec avec le lien
     console (2.3). Un compte sans droit de facturation ne peut pas lire
     cette information : traiter l'absence de réponse comme un
     avertissement non bloquant, jamais comme un échec ;
   - `gcloud config set project $(GCP_PROJECT)` si non positionné (2.2) —
     à faire ici, une fois, plutôt que dans chaque cible.

Nouvelle cible `gcp_check_cli_auth` conservée sous le même nom (elle est en
prérequis d'une quinzaine de cibles, y compris hors setup) : on change son
implémentation, pas son contrat ni son cache 10 min.

### Phase 2 — Activer les API en une fois

Remplacer les 5 appels séquentiels par un seul `gcloud services enable`
(nettement plus rapide, une seule opération à attendre) :

| API | Pourquoi |
|---|---|
| `run.googleapis.com` | Cloud Run (API, éval, LLM) |
| `firestore.googleapis.com` | cache des résultats d'éval |
| `bigquery.googleapis.com` | matrices d'éval |
| `artifactregistry.googleapis.com` | dépôt d'images — **manquant, vrai trou** |
| `compute.googleapis.com` | GPU L4 de `berlue-llm`, VM |
| `appoptimize.googleapis.com` | onglet « Cost » par service |
| `iam` / `iamcredentials` / `cloudresourcemanager` / `storage` | assurance seulement : mesurées `DISABLED` sur le projet de Xavier alors que tout fonctionne (2.4) — les activer ne coûte rien et rend l'intention lisible, mais ne rien en attendre |

Les cibles unitaires (`firestore_enable_api`, `cloudrun_enable_api`,
`gcp_enable_compute`…) restent pour un usage chirurgical et parce que la
doc y renvoie ; `gcp_setup` n'appelle plus que `gcp_enable_apis`.

⚠️ `artifactregistry` doit être activée dans **`ARTIFACT_PROJECT`** (défaut
`GCP_PROJECT`, mais surchargeable) — `artifact_registry_enable_api` le fait
déjà correctement, garder cette distinction dans `gcp_enable_apis`.

### Phase 3 — Ressources, dans le bon ordre, avec les retries qu'il faut

Ordre imposé par les dépendances réelles :

```
APIs
 ├─ Firestore (base (default), retry post-activation)
 ├─ BigQuery  (dataset berlue, bq --headless)
 ├─ sa-berlue ──── attendre son existence ──── bindings (datastore.user conditionné,
 │                                             bigquery.dataEditor + jobUser,
 │                                             serviceAccountUser + TokenCreator pour soi)
 ├─ Artifact Registry (dépôt berlue-repo dans ARTIFACT_PROJECT)
 │    ├─ artifactregistry.writer pour soi
 │    └─ docker_auth (sauté avec avertissement si docker absent)
 └─ bucket RAG ──── objectViewer pour sa-berlue
```

Points d'attention :

- `rag_bucket_grant_sa` doit venir **après** la création du SA (c'est déjà
  le cas dans l'ordre actuel — le préserver) ;
- `docker_auth` ne doit pas faire échouer un setup sur une machine sans
  Docker (poste qui ne fait que lancer l'éval) : avertir, continuer,
  et le redire dans `gcp_doctor` ;
- les tables BigQuery ne sont pas à créer : `GcpResultStore._ensure_bq_tables()`
  fait `create_table(..., exists_ok=True)` au premier usage ;
- pas d'index composite Firestore à provisionner : les requêtes de
  `gcp_result_store.py` sont en égalité seule, sans `orderBy`.

### Phase 4 — `gcp_doctor`, la preuve que c'est prêt

Nouvelle cible, appelée en fin de `gcp_setup` et lançable seule. Une ligne
✅/❌ par brique, **sans jamais s'arrêter à la première erreur**, et un
récapitulatif final :

- API activées (une passe `gcloud services list --enabled`) ;
- base Firestore présente + `firestore_test_read` / `firestore_test_write` ;
- dataset BigQuery présent + `bigquery_test_read` / `bigquery_test_write` ;
- `sa-berlue` présent, ses rôles posés, et **impersonation OK**
  (`cloudrun_sa_test`, avec quelques retries : ~1 min de propagation
  documentée dans `docs/gcp/auth.md`) ;
- dépôt Artifact Registry présent, droit de push effectif, `docker_auth`
  configuré — l'entrée `europe-west1-docker.pkg.dev` dans les `credHelpers`
  de `~/.docker/config.json` **[vérifié : c'est bien la forme posée par
  `docker_auth` sur le poste de Xavier]** ;
- bucket RAG présent et lisible par `sa-berlue`.

Puis la liste explicite de **ce qui reste et n'est pas automatisable** :

1. **quota GPU L4** — un projet neuf a 0 en « Total Nvidia L4 GPU allocation,
   per project per region » (europe-west1) : demande manuelle dans la
   console, délai possible de plusieurs heures. `cloudrun_llm_deploy`
   échouera tant que ce n'est pas accordé. Rien dans la doc actuelle ne le
   mentionne — c'est le genre de blocage qui coûte une journée à un
   nouveau ;
2. build + push des images (`docker_build_prod`/`docker_push_prod`,
   `docker_build_eval_service`/`…_llm`) ;
3. déploiement des services (`cloudrun_deploy`,
   `cloudrun_eval_service_deploy`, `cloudrun_llm_deploy`) ;
4. index RAG : `make download_fever_data_full` → `build_fever_index` →
   `rag_index_upload` (le bucket est créé par `gcp_setup`, son contenu non).

### Phase 5 — Remettre `gcp_destroy` en miroir

Deux niveaux plutôt qu'un :

- `gcp_destroy` (actuel, élargi) : **les 5 services Cloud Run**
  (`berlue-api-{test,staging,prod}`, `berlue-eval-mocked-service`,
  `berlue-llm` — les deux derniers manquent aujourd'hui, et `berlue-llm`
  est le seul poste GPU), le dépôt Artifact Registry, le bucket RAG.
  C'est « je rends le projet propre côté facturation ».
- `gcp_destroy_all` (nouveau, confirmation renforcée) : en plus, Firestore,
  le dataset BigQuery et `sa-berlue`. C'est « j'annule `gcp_setup` » — et ça
  **détruit les données d'éval**, d'où la séparation.

### Phase 6 — Une seule source de vérité pour `.env`

1. Supprimer `TEST_ENV` de `scripts/setup_env.sh` (mort, 2.9).
2. Aligner le script sur `.env.sample` : `GCP_PROJECT`,
   `GOOGLE_APPLICATION_CREDENTIALS` (optionnel), `BUCKET_SUFFIX`, `RUN_ENV`,
   `PORT`, `DATA_SIZE`, `USE_MOCK`, `NOTIFY_BASE_URL`, `BERLUE_LOG_LEVEL`,
   `EXTRACT_MODEL`.
3. Corriger le message de `tests/infrastructure/test_env.py` : renvoyer vers
   `make local_setup` (le vrai chemin), pas vers `cp .env.sample .env`.
4. Ne pas mettre `.env` sous la responsabilité de `gcp_setup` : `gcp_preflight`
   se contente d'exiger `GCP_PROJECT` et de renvoyer vers `make local_setup`.

---

## 5. Documentation à reprendre

La doc décrit l'état d'avant ces changements et, sur deux points, un état
déjà faux aujourd'hui. À corriger dans la même PR que le code.

| Fichier | Ce qui change |
|---|---|
| `docs/setup/gcp.md` | Réécrire « Démarrage rapide » : **prérequis manuels** (créer le projet, lier la facturation, `gcloud auth login`, `make local_setup` pour `.env`), puis `make gcp_setup`. Nouvelle liste de ce qui est provisionné (Artifact Registry inclus). **Supprimer** « L'API Artifact Registry s'active toute seule au premier `make artifact_registry_create` » — faux dès que `gcp_setup` s'en charge. Ajouter une section « Ce que `gcp_setup` ne fait pas » (build/push, déploiements, quota GPU, index RAG) et documenter `gcp_doctor`. Mettre à jour « Tout supprimer » avec `gcp_destroy` / `gcp_destroy_all`. |
| `docs/gcp/composants.md` | Section Artifact Registry : « une seule fois avant le premier déploiement » → provisionné par `gcp_setup`. Ajouter un tableau des API activées et de leur usage (notamment `iamcredentials`, invisible mais critique). Vérifier la formulation Firestore/BigQuery/SA (« Provisionné par `make gcp_setup` » reste juste). |
| `docs/gcp/cloudrun.md` | **Corriger une affirmation déjà fausse** : « Nécessite l'API Compute Engine, pas incluse dans `gcp_setup` » — `gcp_enable_compute` est appelé par `gcp_setup` depuis un moment. Ajouter le **quota GPU L4** comme prérequis manuel de `cloudrun_llm_deploy`. |
| `docs/gcp/auth.md` | Décrire le nouveau test d'auth (`print-access-token` + `projects describe`) et pourquoi il ne dépend d'aucune API du projet. Mentionner `iamcredentials.googleapis.com` comme condition de l'impersonation. Renvoyer vers `gcp_doctor` pour le diagnostic. |
| `docs/gcp/share.md` | Les sondes `*_test_read/write` et `cloudrun_sa_test` sont désormais aussi enchaînées par `gcp_doctor` — le dire, garder l'usage unitaire. |
| `docs/setup/local-setup.md` | Ajouter les **prérequis outillage** (gcloud+bq, docker, pyenv, direnv, shellcheck) et la liste exacte des clés écrites dans `.env` après la Phase 6. Enchaîner explicitement vers `docs/setup/gcp.md`. |
| `README.md` | « Démarrage rapide » ne parle que de local+Ollama. Ajouter le chemin GCP en trois commandes ordonnées (`make local_setup` → `make gcp_auth` → `make gcp_setup`) avec le lien vers `docs/setup/gcp.md`. |
| `.env.sample` | Faire foi ; le seul endroit qui décrit chaque clé. Vérifier qu'aucune clé décrite n'est morte (comme l'était `TEST_ENV`). |

---

## 6. Recette — valider sur un projet vierge

Le seul test qui compte : **un projet GCP neuf**, pas celui de Xavier.
Un projet jetable créé pour l'occasion, détruit après.

Raccourci pour le point le plus important (2.1), sans rien créer :
`wagon-bootcamp-2327-xm` existe déjà sur le compte de Xavier et
`run.googleapis.com` y est désactivée — `GCP_PROJECT=wagon-bootcamp-2327-xm
make gcp_check_cli_auth` reproduit le gel aujourd'hui et doit passer après
la Phase 1. Il ne remplace pas le test complet (facturation, quotas,
ressources à créer) mais valide le correctif clé en quelques secondes.

```bash
gcloud projects create berlue-setup-check-$(date +%s)   # + lier la facturation (console)
git clone … && cd berlue && make local_setup            # .env, GCP_PROJECT = le projet neuf
make gcp_auth
make gcp_setup                                          # doit passer d'un bout à l'autre
make gcp_setup                                          # 2e passage : zéro erreur, zéro effet de bord
make gcp_doctor                                         # tout ✅
```

Points à observer précisément, parce qu'ils sont invisibles ailleurs :

- `gcp_setup` ne gèle pas et ne demande **jamais** de relogin alors que la
  session est bonne (2.1 — le test décisif : lancer `make gcp_setup` sur un
  projet dont `run.googleapis.com` est encore désactivée) ;
- l'enchaînement création de SA → binding passe sans « does not exist »
  (2.5) ;
- aucune commande `bq` ne s'arrête sur une question interactive (2.7) ;
- `docker push` fonctionne ensuite **sans** aucune commande Artifact
  Registry manuelle — c'est la demande initiale ;
- lancer une éval en local contre ce projet
  (`BERLUE_EVAL_STORE_TARGET=gcp make evaluate_model`) écrit bien dans
  Firestore/BigQuery : c'est le test de bout en bout de l'impersonation,
  donc d'`iamcredentials` (2.4).

Puis, sur le poste de Xavier : `make gcp_setup` sur le projet existant doit
rester silencieux et sans effet (tout « déjà présent »), et `gcp_doctor`
tout vert.

---

## 7. Découpage en commits

1. `fix(gcp)` : test d'auth indépendant des API du projet + `</dev/null`
   partout + `gcp_preflight` (Phase 1) — **le déblocage réel** (2.1),
   isolable et testable seul.
2. `feat(gcp)` : `gcp_enable_apis` (Phase 2).
3. `feat(gcp)` : Artifact Registry + `docker_auth` dans `gcp_setup`, retries
   de propagation, `bq --headless`, compte actif fiable (Phase 3).
4. `feat(gcp)` : `gcp_doctor` (Phase 4).
5. `feat(gcp)` : `gcp_destroy` élargi + `gcp_destroy_all` (Phase 5).
6. `fix(env)` : `setup_env.sh` aligné sur `.env.sample`, message de test
   corrigé (Phase 6).
7. `docs(gcp)` : toute la Phase 5 doc, y compris les deux corrections
   d'affirmations aujourd'hui fausses.

Les commits 1 à 3 sont ceux qui rendent l'install possible pour un nouvel
arrivant ; 4 à 7 sont ce qui empêche la situation de se reformer.
