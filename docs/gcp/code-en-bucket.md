# Le code en bucket, l'image sans le code

Une seule image applicative, `berlue-runtime`, sert l'API **et** le service
d'éval. Elle ne contient que les dépendances de `requirements.txt` : le code
de `berlue/` vit dans un bucket GCS, monté en volume par Cloud Run.

Conséquence pratique : **changer une ligne de Python ne rebuilde plus
d'image.**

| | commande | quand | durée |
|---|---|---|---|
| changement de code | `make code_deploy` | tous les jours | ~1 min |
| changement de dépendance ou de `Dockerfile` | `make gcp_deploy` | rarement | ~15 min |

## Pourquoi

Le code pèse 1 Mo, les dépendances ~6,5 Go. Tant que les deux étaient dans la
même image, toucher au code invalidait la couche `COPY berlue`, donc le
`pip install .` qui suivait, donc imposait un push complet — pour 1 Mo de
différence réelle. Et comme `Dockerfile` et `Dockerfile.eval-service` ne
différaient que par le module servi par `uvicorn`, ce coût était payé deux
fois.

## Comment ça marche

```
gs://<projet>-berlue-code/
  current/                            <- CODE_VERSION
    berlue/**                         le package
    models/nli_tfidf_logreg.joblib    la baseline NLI
    data/halueval/ data/truthfulqa/   les jeux labellisés
```

Le bucket est monté sur `/mnt/code`. Au démarrage, `docker/entrypoint.sh`
copie `$BERLUE_CODE_DIR` (= `/mnt/code/$(CODE_VERSION)`) vers `/app`, puis
lance `uvicorn $BERLUE_APP_MODULE`.

Copie plutôt qu'import direct depuis le montage : 7 Mo, une fraction de
seconde, et ça évite trois ennuis — la latence GCS FUSE payée à chaque
import, un `/app` non inscriptible (`__pycache__`, cache SQLite du store
local), et surtout les chemins relatifs codés en dur dans `params.py`
(`data/halueval/raw/qa_data.json`, `./models/nli_tfidf_logreg.joblib`) qui
continuent de résoudre depuis un `WORKDIR` contenant le code, exactement
comme avant. Le montage distribue, `/app` exécute.

Les jeux de données accompagnent le code parce que sinon
`berlue.evaluation.data` les retéléchargerait à chaque démarrage à froid.
`data/fever/` en est exclu (371 Mo) : l'index FAISS a son propre bucket,
`RAG_BUCKET_NAME`.

### Ce qui distingue les deux services

Rien, sauf deux variables d'environnement posées au déploiement :

| | `berlue-api-<env>` | `berlue-eval` |
|---|---|---|
| `BERLUE_APP_MODULE` | `berlue.api.fast:app` | `berlue.api.eval_service:app` |
| volumes | code + RAG | code |

## Le cycle courant

```bash
# après avoir changé du Python
make code_deploy          # = code_push + code_reload
```

`code_push` publie le code local dans `gs://<bucket>/<CODE_VERSION>/`
(`gcloud storage rsync`, les fichiers supprimés le sont aussi côté bucket).

`code_reload` pousse une nouvelle révision de chaque service applicatif
déployé. **La nouvelle révision est indispensable, pas un confort** : un
process Python déjà démarré ne relit pas ses imports, et GCS FUSE cache ses
métadonnées. C'est une instance neuve qui recopie le code.

Les services non déployés sont sautés avec un avertissement, pas une erreur.
`code_reload` ne change aucun `min-instances` : il ne rallume rien qui était
éteint, et ne coupe rien qui tournait.

## Versions

`CODE_VERSION` (défaut `current`) est le premier niveau de dossier du bucket.
Le flux courant réécrit `current`. Pour épingler une version à côté, sans
toucher à `current` :

```bash
make code_push   CODE_VERSION=$(git rev-parse --short HEAD)
make code_reload CODE_VERSION=$(git rev-parse --short HEAD)
make code_versions        # ce que contient le bucket
```

Un déploiement (`cloudrun_deploy`, `cloudrun_eval_service_deploy`) refuse de
partir si la `CODE_VERSION` visée est absente du bucket — même garde-fou que
pour l'index RAG, et pour la même raison : sans lui, le conteneur ne boote
pas et l'erreur reste enfouie dans les logs Cloud Run.

## En local

L'image est la même, le code n'en vient simplement pas du bucket : il est
bind-monté dans `/app`, ce que l'entrypoint détecte et respecte.

```bash
make docker_build_local                                     # build
make docker_run_local                                       # API
make docker_run_local BERLUE_APP_MODULE=berlue.api.eval_service:app   # éval
make compose_up                                             # API + rechargement à chaud
```

## Ce qui n'a pas changé

Les noms des services Cloud Run, donc leurs URLs — rien à reconfigurer côté
Aletheia. Le bucket RAG et `RAG_CORPUS_VERSION`. `gcp_up` / `gcp_eval_up` /
`gcp_down` / `gcp_status`, garde-fous budget compris. `Dockerfile.llm` et
`berlue-llm`, qui ne contiennent aucun code Berlue.
