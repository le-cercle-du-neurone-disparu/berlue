> **Statut : validé de bout en bout contre GCP** (31/08, branche
> `feat-berlu-sur-gcp`, projet `gen-lang-client-0242212765`) — `gcp_setup`
> exécuté (bucket RAG créé, IAM `sa-berlue`), index `small-2000` uploadé,
> `berlue-api-test` déployé et câblé sur `berlue-llm` déjà en place,
> `/predict` répond 200 avec des verdicts cohérents après le passage à
> `GAR_MEMORY=8Gi`/`GAR_CPU=2` (2Gi puis 4Gi ont d'abord échoué en
> conditions réelles, cf. Phase 2). `gcp_down` relancé après le test.
> Reste : re-tester avec le corpus `full-145k`, promouvoir
> staging/prod (Phase 5).

# Plan — déploiement GCP de l'API Berlue (hors éval)

Objectif : faire tourner le pipeline `/predict` (celui qu'Aletheia appelle,
distinct de l'éval déjà avancée) sur GCP — deux Cloud Run, `berlue-api-<env>`
(CPU) et `berlue-llm` (GPU, Ollama), Aletheia restant en local et pointant
dessus.

```
Aletheia (Streamlit, local)  →  berlue-api-<env> (Cloud Run, CPU)  →  berlue-llm (Cloud Run, GPU L4, Ollama)
                                        ↓
                                  FAISS/FEVER (RAG, en process)
```

## Ce qui se réutilise tel quel

- **`berlue-llm`** : image (`Dockerfile.llm`), déploiement GPU L4, IAM
  (`run.invoker` pour `sa-berlue`), dimensionnement — même service que celui
  utilisé par l'éval, cf. [`docs/gcp/cloudrun.md`](../docs/gcp/cloudrun.md) et
  [`docs/gcp/infra-gpu.md`](../docs/gcp/infra-gpu.md).
- **`OllamaClient`** (`berlue/llm/client.py`) : gère déjà l'auth OIDC vers un
  Cloud Run privé de façon générique (`_cloud_run_auth_headers`, activée par
  la détection `K_SERVICE`) — pas spécifique à l'éval, le pipeline principal
  en profite automatiquement dès que `BERLUE_OLLAMA_HOST` pointe vers
  `berlue-llm`.
- **`berlue-api-<env>`** : `Dockerfile`, cible `cloudrun_deploy`
  (test/staging/prod), promotion progressive d'une seule image `:prod` — le
  mécanisme de déploiement existe déjà.
- **SA `sa-berlue`** : attaché par défaut par `cloudrun_deploy`, déjà
  autorisé à appeler `berlue-llm`.

## Quatre trous à corriger avant tout déploiement

1. **L'index FAISS n'est pas dans l'image de prod.** `data/` est exclu par
   `.dockerignore`. `RagRetriever` est instancié au démarrage
   (`lifespan()` dans `berlue/api/fast.py`), pas à la demande → le
   conteneur crash au boot sur Cloud Run, faute d'index. Ne pas corriger ça
   en embarquant l'index dans l'image (cf. section suivante) : l'étape
   d'indexation doit tourner après `pip install .`, donc après `COPY
   berlue` — tout changement de code invaliderait cette couche Docker et
   forcerait un re-téléchargement FEVER + un ré-embedding complet à chaque
   build, coûteux sur le corpus complet (contrairement à la baseline NLI de
   `Dockerfile.eval-service`, rapide à réentraîner).
2. **`RAG_VECTOR_DB_PATH` est codé en dur** dans `berlue/params.py`
   (littéral `"data/fever/faiss"`, pas lu depuis l'environnement) —
   bloque toute indirection vers un chemin monté (bucket GCS) sans
   modifier le code. (`RAG_INDEX_DIR`, à côté, n'est en réalité consommé
   nulle part dans le code — laissé tel quel, pas touché.)
3. **`GET /llms` est cassé pour du distant.**
   `BerlueService.get_available_llms()` (`berlue/api/service.py`) appelle
   `ollama.list()` — le module `ollama` brut, pas le wrapper
   `OllamaClient`. Il ignore donc `BERLUE_OLLAMA_HOST` et surtout n'envoie
   jamais le jeton OIDC requis par `berlue-llm`
   (`--no-allow-unauthenticated`) → 401/403 garanti en prod.
4. **`cloudrun_deploy` ne passe aucune variable d'environnement.**
   Contrairement à `gcp_up` (qui fait
   `--update-env-vars=BERLUE_OLLAMA_HOST=...` sur le service d'éval), la
   cible `cloudrun_deploy` de `make/cloudrun.mk` ne fixe rien —
   `BERLUE_OLLAMA_HOST` resterait à son défaut `http://localhost:11434`,
   inexistant sur Cloud Run.

## Index RAG : bucket GCS dédié, pas dans l'image

L'index FAISS/FEVER vit dans un bucket GCS **dédié** (pas `BUCKET_NAME`,
déjà utilisé pour d'autres usages MLOps — un volume GCS FUSE monte tout le
contenu d'un bucket, pas un sous-dossier, donc mélanger des données sans
rapport dans le même bucket les rendrait toutes visibles dans le conteneur
API). Bucket vide aujourd'hui côté RAG → on définit l'arborescence
maintenant :

```
gs://<rag-bucket>/
  faiss/
    <corpus-version>/     # ex. small-2000, full-145k
      index.faiss
      metadata.pkl
```

`<corpus-version>` en dossier (pas de fichier à la racine) : chaque
génération d'index (`berlue/rag/indexer.py` écrit exactement ces deux
fichiers) garde sa propre version sans écraser la précédente — changer de
corpus = changer `RAG_CORPUS_VERSION` (`make/cloudrun.mk`, défaut
`full-145k`) et redéployer, sans toucher à l'image ni au bucket.

Construit à part (une machine locale ou un job ponctuel), jamais reconstruit
au `docker build` — découple le cycle de vie du corpus (rare) de celui des
déploiements de code (fréquent). Création du bucket + IAM : gratuit,
anticipable, donc dans `gcp_setup` (et sa suppression dans `gcp_destroy`,
`rag_bucket_delete`) — jamais `gcp_up`/`gcp_down`, qui ne gèrent que le
coût variable à la demande (min-instances) :

```bash
# une fois (fait partie de gcp_setup — pas besoin de le rejouer seul sauf
# pour recréer juste le bucket)
make gcp_setup
```

```bash
# construction locale de l'index, comme aujourd'hui
make download_fever_data_full   # ou _small pour itérer plus vite
make build_fever_index
```

```bash
# upload vers gs://RAG_BUCKET_NAME/faiss/RAG_CORPUS_VERSION
make rag_index_upload
```

Côté Cloud Run, `cloudrun_deploy` (Phase 2) monte le bucket en volume GCS
FUSE (natif 2ᵉ génération, aucun code Python à ajouter) plutôt que de
télécharger les fichiers à la main au démarrage — flags déjà dans la cible,
rien à faire de plus ici.

## Phase 0 — Corriger le code ✅ fait

- **RAG** : `RAG_VECTOR_DB_PATH` lu depuis l'environnement dans
  `berlue/params.py` (`os.environ.get(...)`, comme le reste des chemins
  configurables) au lieu du littéral codé en dur.
- **`/llms`** : `OllamaClient.list_models()` (nouvelle méthode,
  `berlue/llm/client.py`) — réutilise `self.client`, déjà configuré avec
  l'auth OIDC dans `__init__`. `BerlueService.get_available_llms()`
  (`berlue/api/service.py`) délègue à `OllamaClient().list_models()` au
  lieu du module `ollama` global.

## Phase 1 — Préparer `berlue-llm`, et étendre le warming à tout le produit ✅ fait (Makefile)

Le service `berlue-llm` existe déjà ; build/déploiement inchangés :

```bash
# une fois — active l'API Compute Engine nécessaire au GPU
make gcp_enable_compute
```

```bash
# build + push l'image Ollama, déploie/maj le service GPU
make docker_build_llm docker_push_llm
make cloudrun_llm_deploy
```

Deux cold starts distincts à couvrir pour le chemin produit, tous les deux
via une **même fonction de warming** — extension de `gcp_up`/`gcp_down`
(déjà en place pour l'éval) plutôt qu'un mécanisme séparé :

- **`berlue-llm`** : modèle pullé non persistant (disque éphémère), re-pull
  ~100s à chaque réveil. `WARM_MODELS` doit couvrir les modèles du pipeline
  principal — `OLLAMA_MODEL`/`EXTRACT_MODEL`/`RAG_MODEL` (tous
  `llama3.2:3b` par défaut) — en plus de ceux déjà pullés côté éval.
- **`berlue-api-<env>`** : chargement de `sentence-transformers`
  (embeddings RAG, modèle `all-mpnet-base-v2` téléchargé depuis HuggingFace
  à l'instanciation de `RagRetriever` dans `lifespan()`) — dépendance
  réseau à chaque cold start, couverte par le même `min-instances=1` que
  `berlue-llm` plutôt que par une modification du `Dockerfile`.

Extension concrète de `gcp_up`/`gcp_down` :

- `gcp_up` : en plus de `berlue-eval-mocked-service` (+ `berlue-llm` si
  `WARM_MODELS`), passer `berlue-api-<env>` à `min-instances=1` et attendre
  qu'il réponde sur `/` (même logique de polling que pour
  `berlue-eval-mocked-service` sur `/health`).
- `gcp_down` : redescendre `berlue-api-<env>` à `min-instances=0` en plus de
  `berlue-eval-mocked-service`/`berlue-llm`, inconditionnellement — même
  principe qu'aujourd'hui (pas d'état à suivre entre les deux commandes).

**Priorité avant tout test réel** (cf. section « Garde-fous coûts ») : la
seule chose qui coûte cher sans qu'on s'en aperçoive, c'est `berlue-llm`
resté allumé — donc `gcp_up`/`gcp_down` étendus doivent être écrits et
vérifiés en premier, avant la moindre session de test contre `/predict`.

## Phase 2 — Câbler `berlue-api-<env>` sur `berlue-llm` ✅ fait

`cloudrun_deploy` (`make/cloudrun.mk`) résout maintenant l'URL de
`berlue-llm` **dans la recette** (`$$(...)` shell, pas `$(shell ...)` — qui
s'évaluerait au parsing du Makefile, donc à chaque invocation de `make`, y
compris avant que `berlue-llm` existe), fusionné directement dans le
`gcloud run deploy` existant :

```makefile
cloudrun_deploy: gcp_check_cli_auth
	@LLM_URL=$$(gcloud run services describe $(CLOUDRUN_LLM_SERVICE) --region $(GCP_REGION) --project $(GCP_PROJECT) --format="value(status.url)"); \
	gcloud run deploy $(GAR_IMAGE)-$(CLOUDRUN_ENV) \
		--image $(GCP_REGION)-docker.pkg.dev/$(ARTIFACT_PROJECT)/$(ARTIFACTSREPO)/$(GAR_IMAGE):prod \
		--timeout=$(GAR_TIMEOUT) \
		--add-volume=name=rag,type=cloud-storage,bucket=$(RAG_BUCKET_NAME) \
		--add-volume-mount=volume=rag,mount-path=/mnt/rag \
		--update-env-vars=USE_MOCK=0,BERLUE_OLLAMA_HOST=$$LLM_URL,RAG_VECTOR_DB_PATH=/mnt/rag/faiss/$(RAG_CORPUS_VERSION) \
		...
```

Corrigé au passage : `--image` référençait `$(GCP_PROJECT)`, alors que
`docker_push_prod` pousse vers `$(ARTIFACT_PROJECT)` — inconsistant dès que
les deux projets diffèrent (confirmé par l'ancien
`docs/deploy/gcp-deployment.md`, supprimé depuis mais dont le contenu disait
explicitement que toutes les cibles image doivent suivre
`ARTIFACT_PROJECT`). Sans incidence tant que `ARTIFACT_PROJECT=GCP_PROJECT`
(le défaut), mais c'était le mauvais projet référencé dans le cas contraire.

Le SA reste `sa-berlue` (déjà le défaut) → l'auth OIDC vers `berlue-llm`
marche sans code supplémentaire. Lecture sur le bucket de l'index :
`rag_bucket_grant_sa` (nouvelle cible, appelée par `gcp_setup` — `gcs_grant`
existant ne gère que `--member="user:$(USER)"`, accès humain, pas
utilisable pour `sa-berlue`).

`GAR_TIMEOUT=600` (`make/config.mk`, remplace le défaut Cloud Run 300s) —
`/predict` enchaîne ~6 appels LLM séquentiels (génération, extraction, K=5
échantillons SelfCheck, RAG, fusion).

`GAR_MEMORY`/`GAR_CPU` mesurés en conditions réelles (31/08, premier test
`/predict` de bout en bout contre `berlue-api-test`), pas laissés au
défaut faute de mesure comme prévu initialement :

- `2Gi` (défaut initial) : le "disque" du conteneur est adossé à la
  mémoire allouée sur Cloud Run — `/predict` télécharge à la demande le
  modèle NLI de SelfCheckGPT (`potsawee/deberta-v3-large-mnli`, ~1,7 Go,
  en plus du modèle d'embedding RAG déjà chargé) et manquait de place
  pour l'écrire (1703 Mio libres pour un fichier de 1740 Mio).
- `4Gi` : la requête a cette fois été tuée en plein milieu (`Container
  terminated on signal 9` dans les logs Cloud Run — OOM réel, pas une
  erreur applicative) — charger les deux modèles + le runtime torch en
  pic dépasse 4Gi.
- `8Gi` : `/predict` passe de bout en bout (200, ~100s sur la première
  requête, modèle froid côté `berlue-llm`).
- Cloud Run plafonne la mémoire selon le CPU alloué (1 vCPU → 4Gi max,
  confirmé par une erreur `gcloud` explicite) — `GAR_CPU=2` ajouté à
  `cloudrun_deploy` pour débloquer `GAR_MEMORY=8Gi`, pas un simple choix
  de performance.

## Phase 3 — Build + déploiement de l'image API corrigée

```bash
make docker_build_prod
make docker_push_prod
make cloudrun_deploy CLOUDRUN_ENV=test
```

```bash
# récupère l'URL pour le smoke-test
make cloudrun_url CLOUDRUN_ENV=test
```

Non vérifié faute de projet GCP réel à ce stade : le volume GCS FUSE
(`--add-volume type=cloud-storage`) peut exiger
`--execution-environment=gen2` selon la version de `gcloud`/Cloud Run — si
`cloudrun_deploy` échoue là-dessus au premier essai, ajouter le flag dans
`make/cloudrun.mk`.

`gcp_up` (Phase 1, étendu) d'abord — sans ça `berlue-llm` est en
scale-to-zero et le smoke-test `/predict` échoue simplement parce que rien
n'est chaud, pas à cause d'un vrai problème :

```bash
make gcp_up WARM_MODELS="llama3.2:3b"
```

Smoke-test direct en `curl` (`/`, `/llms`, `/predict`) avant de toucher à
Aletheia — isole les problèmes API des problèmes front.

## Phase 4 — Brancher Aletheia dessus

- `.env` d'Aletheia : `BERLUE_API_URL=<url berlue-api-test>` (service public
  par défaut sur `test`/`staging`/`prod`, donc pas d'OIDC côté Aletheia —
  appel HTTPS simple).
- `utils/api_client.py` : le timeout de `/predict` (60s aujourd'hui) est
  probablement trop court dès que `berlue-llm` est froid — à aligner sur le
  `--timeout` retenu en Phase 2.
- Test de bout en bout depuis la vraie page Streamlit
  (`pages/1_🔎_Prediction.py`).

## Phase 5 — Promotion

Une fois `test` validé, mêmes commandes sur `staging` puis `prod`
(`CLOUDRUN_ENV=staging|prod`) — image `:prod` inchangée, juste promue.

## Garde-fous coûts

`berlue-llm` facture dès le premier appel (~0,67 $/h GPU). Comme pour
l'éval : toujours `gcp_down` (étendu, cf. Phase 1) en fin de session de
test/démo — ne jamais laisser `min-instances=1` sans y penser.

Ne pas se fier au seul fait que la commande `gcp_down` se termine sans
erreur — `gcloud run services update` peut réussir tout en laissant un état
différent de celui attendu si un flag est mal passé. Vérifier après coup,
pas juste lancer :

```bash
# min-instances des 3 services (berlue-eval-mocked-service, berlue-llm,
# berlue-api-<env>) — doit afficher 0 partout après gcp_down
make gcp_status
```

`gcp_status` (nouvelle cible, `make/cloudrun.mk`) — objectif : que la
vérification post-`gcp_down` soit un réflexe d'une commande, pas une étape
qu'on saute par flemme.

**Première fois que `gcp_up`/`gcp_down` couvrent `berlue-api-<env>`** (Phase
1) : dérouler tout le cycle à vide avant le premier vrai test `/predict` —
`gcp_up` → `gcp_status` (les deux services à 1) → `gcp_down` → `gcp_status`
(les deux services à 0, y compris `berlue-llm`) — pour prouver que
l'extinction marche vraiment avant d'en dépendre pendant une session de
test.

## Décisions tranchées

- **`/llms`** : reste une requête live vers `berlue-llm`, sa fiabilité
  dépend du warming (`gcp_up` étendu, cf. Phase 1) plutôt que d'une liste
  figée côté config.
- **Accès public** : `berlue-api-test/-staging/-prod` restent publics par
  défaut (`CLOUDRUN_PUBLIC_*=true`, déjà en place) — acceptable pour
  l'instant, pas d'IAM ni d'OIDC côté Aletheia à ce stade.
- **Bucket RAG** : dédié (`${GCP_PROJECT}-berlue-rag`), pas de partage avec
  `BUCKET_NAME` — arborescence définie dans la section « Index RAG »
  ci-dessus.
- **Préchauffe de `berlue-api-<env>`** : oui, via la même extension de
  `gcp_up`/`gcp_down` que `berlue-llm` (cf. Phase 1) — pas de mécanisme
  séparé.

## Décisions ouvertes

- Taille du corpus FEVER uploadé dans le bucket : extrait 2000 lignes
  (rapide à construire) vs corpus complet ~145k (meilleure précision RAG) —
  n'affecte plus l'image ni les builds, changeable par un simple ré-upload.

## Prochaine étape — reproduire en local le CPU/GPU non-idle sur `berlue-llm`

Observé le 31/08 (cf. [`docs/gcp/aletheia-local.md`](../docs/gcp/aletheia-local.md)) :
après un warmup (`gcp_up WARM_MODELS="llama3.2:3b"`), l'instance
`berlue-llm` est restée classée *active* par Cloud Run pendant plus de 20
minutes sans aucune requête HTTP entrante (CPU ~20-25%, GPU ~5% en continu,
confirmé par les graphes Metrics de la console) — empêchant tout
scale-to-zero indépendamment de `min-instances`. Deux lignes de log
repérées sur cette période, candidates mais pas confirmées comme cause :

```
level=WARN msg="llama-server GPU discovery watchdog timed out" error="context deadline exceeded"
level=WARN msg="unable to refresh free memory, using old values"
```

Suggère une boucle de retry côté `llama-server`/Ollama qui ne se stabilise
jamais, plutôt qu'un vrai travail de calcul — à confirmer.

À faire pour identifier la cause précise (pas fait faute d'accès à un GPU
en local dans cette session) :

1. Reproduire la config exacte de `Dockerfile.llm` en local sur une machine
   avec GPU (`OLLAMA_KEEP_ALIVE=-1`, mêmes `OLLAMA_NUM_PARALLEL`) —
   `make ollama_setup`/`docker_run_local`-style, ou directement `ollama
   serve` avec les mêmes variables d'environnement.
2. Chauffer avec `llama3.2:3b` (`ollama pull` + un appel `/api/generate`
   jetable), puis laisser tourner **sans aucune requête** pendant 15-20
   minutes en surveillant `nvidia-smi`/l'usage CPU en continu, et les logs
   Ollama en verbosité max (`OLLAMA_DEBUG=1`, `--log-verbosity 4`) pour
   capturer la fréquence des deux messages ci-dessus et voir s'ils
   corrèlent avec l'activité CPU/GPU mesurée.
3. Une fois la boucle identifiée, chercher le réglage Ollama qui l'arrête
   (ou confirmer que c'est un comportement inhérent au serveur GPU
   `llama-server` sans réglage direct, auquel cas la seule parade reste la
   discipline documentée dans `aletheia-local.md` — `cloudrun_llm_delete`
   systématique plutôt que compter sur le scale-to-zero).
