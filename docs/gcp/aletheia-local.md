# Aletheia en local, Berlue sur GCP

Fait tourner l'interface Aletheia sur sa machine, branchée sur l'API Berlue
déployée sur Cloud Run (`berlue-api-<env>` + `berlue-llm`) plutôt que sur un
Ollama/RAG local — aucune dépendance locale lourde côté Aletheia
(`USE_MOCK`/Ollama/FAISS restent l'affaire de Berlue).

## Prérequis — une fois par machine/session gcloud

S'assurer que l'auth CLI est valide et que l'infra GCP est bien provisionnée
avant toute session — les deux sont idempotents, sans risque à rejouer :

```bash
# depuis le repo berlue — interactif, à lancer depuis son propre terminal
make gcp_auth
```

```bash
# depuis le repo berlue — provisionne/vérifie APIs, Firestore, BigQuery,
# sa-berlue, bucket RAG (gratuit et anticipable, cf. cloudrun.md)
make gcp_setup
```

## Démarrer une session

1. Préchauffer `berlue-llm` et `berlue-api-<env>` — sans ça, la première
   requête Aletheia attend un cold start GPU (30-50s) et peut échouer sur
   les modèles absents (`/llms` vide juste après un réveil, cf.
   [`cloudrun.md`](cloudrun.md#service-ollama-berlue-llm)) :

```bash
# depuis le repo berlue — WARM_MODELS doit couvrir OLLAMA_MODEL/EXTRACT_MODEL/RAG_MODEL
make gcp_up WARM_MODELS="llama3.2:3b"   # API + LLM (make gcp_eval_up pour le service d'éval)
```

2. Récupérer l'URL de l'environnement Berlue visé et la mettre dans le
   `.env` d'Aletheia :

```bash
# depuis le repo berlue
make cloudrun_url CLOUDRUN_ENV=test
```

```bash
# dans le .env du repo aletheia
BERLUE_API_URL=https://berlue-api-test-xxxxxxxxxx.europe-west1.run.app
```

3. Lancer Aletheia :

```bash
# depuis le repo aletheia
make run_app
```

## Terminer une session — toujours forcer l'arrêt réel

`gcp_down` (`min-instances=0`) retire la garantie de capacité chaude, mais
**ne garantit pas l'arrêt immédiat d'une instance déjà active** — observé
en conditions réelles (31/08) : une instance `berlue-llm` restée classée
*active* (jamais *idle*) par Cloud Run pendant plus de 20 minutes après un
`gcp_down`, CPU/GPU non nuls en continu sans aucune requête HTTP entrante
sur cette fenêtre (onglet Metrics de la console Cloud Run — "Container
instance count"/"Container CPU utilization"/"GPU utilization",
`min-instances` en CLI seul ne suffit pas à le détecter). `berlue-llm` est
le seul poste de coût qui compte vraiment ici (GPU, ~0,67 $/h dès la
première requête) — donc systématiquement, en fin de session :

```bash
# gcp_down d'abord (redescend berlue-eval/berlue-api aussi)
make gcp_down
```

```bash
# puis, toujours, pour berlue-llm spécifiquement — seul levier garanti
make cloudrun_llm_delete
```

Vérifier après coup plutôt que de se fier au seul succès de la commande :

```bash
make gcp_status
```

Idéalement, confirmer aussi via l'onglet "Metrics" du service `berlue-llm`
dans la console Cloud Run ("Container instance count" à 0) — c'est ce qui a
révélé le cas du 31/08, invisible en ne regardant que `min-instances` en
CLI.

Reconstruire `berlue-llm` avant la prochaine session (le service n'existe
plus après `cloudrun_llm_delete`) :

```bash
make docker_build_llm docker_push_llm
make cloudrun_llm_deploy
```

`berlue-api-<env>` et `berlue-eval` restent en CPU (coût
largement inférieur) — `gcp_down` seul y est suffisant en pratique, pas
besoin d'un équivalent `delete` systématique.
