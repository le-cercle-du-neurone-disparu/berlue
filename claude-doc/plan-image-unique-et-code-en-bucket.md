# Plan — une seule image, et le code dans un bucket

> Branche `refacto-berlu-images`, clone dédié `/opt/wagon/src/refacto-berlu-images`
> (fork de `feat-fix`). Chantier parallèle au refacto/bugfix en cours sur
> `berlue` — aucun fichier applicatif (`berlue/**`) n'est modifié ici, pour que
> les deux branches ne se marchent pas dessus.

## Le problème

Deux constats, indépendants dans leurs causes, communs dans leur effet :
chaque changement d'une ligne de Python coûte un build + un push de ~10 Go.

1. **`Dockerfile` (API) et `Dockerfile.eval-service` sont le même fichier.**
   Mêmes `requirements.txt`, mêmes `COPY berlue`, même `pip install .`. Ne
   diffèrent que par le `WORKDIR`, un `RUN python -m berlue.nli_baseline.train`
   et le module servi par `uvicorn`. On maintient et on pousse deux fois la
   même chose.
2. **Le code est dans l'image.** Or le code pèse 1 Mo et les dépendances
   ~6,5 Go. Changer le code invalide la couche `COPY berlue` — donc le
   `pip install .` qui suit — et impose un nouveau push complet. Mesuré le
   01/09 : ~131 s rien que pour l'export des couches, plusieurs minutes pour
   le push, et la marge disque locale qui sature à 93 %.

## La cible

**Une image unique `berlue-runtime`, sans code, avec seulement les
dépendances.** Le code vit dans un bucket GCS monté en volume par Cloud Run.
Déployer une nouvelle version de code = pousser le bucket + forcer une
nouvelle révision. Aucun build, aucun push d'image.

```
        AVANT                                 APRÈS
  berlue-api    (10 Go, code dedans)     berlue-runtime (deps seules)
  berlue-eval   (10 Go, code dedans)       ├─ berlue-api-<env>  BERLUE_APP_MODULE=berlue.api.fast:app
  berlue-llm    (Ollama, inchangé)         └─ berlue-eval       BERLUE_APP_MODULE=berlue.api.eval_service:app
                                         berlue-llm     (inchangé)

  make gcp_deploy  ~15 min                gs://<projet>-berlue-code/<version>/
  à chaque ligne de Python                  berlue/ models/ data/
                                         make code_deploy  ~1 min
```

### 1. Image unique

`Dockerfile` devient le seul Dockerfile applicatif ; `Dockerfile.eval-service`
disparaît. L'image contient : les dépendances de `requirements.txt`, et un
`entrypoint.sh`. Rien d'autre.

Ce qui distinguait les deux images est déplacé en configuration Cloud Run :

| Différence | Avant | Après |
|---|---|---|
| module servi | `CMD` figé dans chaque Dockerfile | `BERLUE_APP_MODULE` (défaut `berlue.api.fast:app`) |
| `WORKDIR` | `/api` vs `/eval` | `/app` pour les deux |
| baseline NLI | `RUN python -m berlue.nli_baseline.train` au build | `models/*.joblib` poussé dans le bucket de code |
| `PYTHONUNBUFFERED` | seulement côté éval | dans l'image, pour les deux |

Le package n'est plus `pip install .` — il est importé depuis `/app` via
`PYTHONPATH`. Vérifié : rien dans `berlue/` ne lit de métadonnée
d'installation (`importlib.metadata`, `pkg_resources`) et `setup.py` ne
déclare aucun `console_scripts`. Rien ne dépend donc de l'installation.

### 2. Le code dans un bucket

Nouveau bucket dédié `CODE_BUCKET_NAME = $(GCP_PROJECT)-berlue-code`, monté en
volume GCS FUSE sur `/mnt/code` — même motif que l'index RAG
(`RAG_BUCKET_NAME`), qui marche déjà en production. Dédié pour la même raison
qu'expliquée dans `config.mk` : un volume GCS FUSE monte *tout* le bucket.

Arborescence, versionnée par un premier niveau de dossier :

```
gs://<projet>-berlue-code/
  current/            <- CODE_VERSION, défaut
    berlue/**         (le package, ~1 Mo)
    models/nli_tfidf_logreg.joblib
    data/halueval/  data/truthfulqa/     (~6 Mo, évite un téléchargement au boot)
  <sha-git>/          <- une version figée, si on veut épingler
```

`BERLUE_CODE_DIR=/mnt/code/<CODE_VERSION>` dit au conteneur où regarder.

**Le conteneur copie le code du montage vers `/app` au démarrage** plutôt que
de l'importer directement depuis `/mnt/code`. 7 Mo, une fraction de seconde,
et ça achète trois choses : les imports Python ne paient pas la latence GCS
FUSE fichier par fichier, `/app` reste inscriptible (`__pycache__`, et
`data/mlops/*.db` du store local), et surtout les chemins relatifs du code
(`data/halueval/raw/qa_data.json`, `./models/nli_tfidf_logreg.joblib` — codés
en dur dans `params.py`, pas tous surchargeables par variable
d'environnement) continuent de résoudre exactement comme avant, depuis un
`WORKDIR` qui contient le code. Le montage reste donc le mécanisme de
distribution ; `/app` reste l'environnement d'exécution.

L'entrypoint saute la copie si `/app/berlue` existe déjà — c'est le cas en
développement local, où l'on bind-monte le code directement (`docker-compose`,
`docker_run_local`). Même image dans les deux cas.

### 3. Le cycle de déploiement

```
make gcp_deploy      # rare : build + push de berlue-runtime et berlue-llm, puis les 3 services
make code_deploy     # courant : push du code dans le bucket + nouvelle révision
```

`code_deploy` = `code_push` + `code_reload`. `code_reload` pousse une
nouvelle révision de chaque service déployé (`--update-env-vars` d'un
marqueur horodaté) : Cloud Run redémarre des instances neuves, qui recopient
le code du bucket. Il faut bien une nouvelle révision — un processus Python
déjà démarré ne relit pas ses imports, et GCS FUSE cache ses métadonnées.

## Ce qui ne change pas

- `Dockerfile.llm` / `berlue-llm` : hors sujet, image Ollama sans code Berlue.
- Les noms des services Cloud Run (`berlue-api-<env>`, `berlue-eval`,
  `berlue-llm`), donc leurs URLs, donc rien à reconfigurer côté Aletheia.
- Le bucket RAG, son montage, `RAG_CORPUS_VERSION`.
- `gcp_up` / `gcp_eval_up` / `gcp_down` / `gcp_status` : mêmes cibles, mêmes
  garde-fous budget.
- Aucun fichier de `berlue/**` n'est touché.

## Hors périmètre, volontairement

La roue CPU de `torch` (`claude-doc/plan-optimisation-images-docker.md`,
~10 Go → ~5 Go) est complémentaire et attaquerait le même symptôme, mais
c'est un chantier distinct qui a son propre plan et ses propres
vérifications. Les deux se composent : une image deux fois plus légère
qu'on ne rebuild presque plus.

## Étapes

1. `Dockerfile` unique + `docker/entrypoint.sh` ; suppression de
   `Dockerfile.eval-service`.
2. `make/config.mk` : `GAR_RUNTIME_IMAGE`, `CODE_BUCKET_NAME`, `CODE_VERSION`.
3. `make/docker.mk` : une seule paire build/push applicative.
4. `make/code.mk` (nouveau) : `code_bucket_create`, `code_bucket_grant_sa`,
   `code_bucket_delete`, `code_push`, `code_reload`, `code_deploy`,
   `code_versions`.
5. `make/cloudrun.mk` : les deux déploiements pointent la même image et
   montent le bucket de code.
6. `make/gcp.mk` : `gcp_setup` crée le bucket, `gcp_deploy` pousse le code,
   `gcp_destroy` supprime le bucket.
7. Local : `docker-compose.yml`, `docker_run_local`.
8. Docs : `docs/gcp/cloudrun.md`, `docs/setup/gcp.md`, `docs/gcp/composants.md`,
   `README.md`, et une page dédiée `docs/gcp/code-en-bucket.md`.

## Vérifications sur GCP réel

Projet `gen-lang-client-0242212765`. À l'état initial : aucun service Cloud Run
déployé, bucket RAG présent (`full-145k`, `small-2000`), `sa-berlue` présente.

1. `make test_fast` passe (aucune régression sur l'existant).
2. L'image `berlue-runtime` build et démarre en local sur les deux modules.
3. `make code_push` remplit le bucket.
4. `make cloudrun_deploy_all` : les 3 services montent, `berlue-api-test`
   répond sur `/`, `berlue-eval` sur `/health`.
5. Un `/predict` réel et un `/invoke` réel aboutissent.
6. **La vérification qui compte** : modifier une ligne de Python,
   `make code_deploy`, et constater le changement en ligne — chronométré,
   sans aucun build ni push d'image.
7. `make gcp_down` puis `gcp_status` : plus rien de facturé. **Non
   négociable** — `berlue-llm` est un GPU L4 à ~0,67 $/h.
