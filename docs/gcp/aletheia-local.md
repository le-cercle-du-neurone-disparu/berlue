# Aletheia en local, Berlue sur GCP

Fait tourner l'interface Aletheia sur sa machine, branchée sur l'API Berlue
déployée sur Cloud Run (`berlue-api-<env>` + `berlue-llm`) plutôt que sur un
Ollama/RAG local — aucune dépendance locale lourde côté Aletheia
(Ollama et FAISS restent l'affaire de Berlue).

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

1. Allumer et préchauffer `berlue-llm` et `berlue-api-<env>` — sans ça, la
   première requête Aletheia attend le démarrage des GPU et le téléchargement
   des modèles. `WARM_MODELS` doit couvrir les modèles du pipeline
   (`BERLUE_OLLAMA_MODEL`, `EXTRACT_MODEL`, `RAG_MODEL`) :

```bash
# depuis le repo berlue — ~5 min 30
make gcp_up WARM_MODELS="llama3.2:3b llama3.1:8b"
make api_warm      # attend que l'API ait chargé l'index FAISS et le NLI
```

2. Récupérer l'URL de l'environnement Berlue visé et la mettre dans le
   `.env` d'Aletheia :

```bash
# depuis le repo berlue
make cloudrun_url CLOUDRUN_ENV=test
```

```bash
# dans le .env du repo aletheia
BERLUE_API_GCP_URL=https://berlue-api-test-xxxxxxxxxx.europe-west4.run.app
```

3. Lancer Aletheia en local, branché sur cette URL :

```bash
# depuis le repo aletheia
make run_app_gcp
```

L'application répond sur http://localhost:8501. Temps de réponse attendus : ~0,1 s
pour une question déjà en cache, 1,2 à 5 s pour une question neuve selon le
nombre d'affirmations (cf. [`latence-predict.md`](latence-predict.md)). Le
premier appel après un `gcp_up` est plus long (10 à 16 s).

## Terminer une session

```bash
# depuis le repo berlue
make gcp_down
make gcp_status    # vérifier : aucun service ne doit rester
```

`gcp_down` **supprime** les trois services : c'est le seul arrêt garanti de la
facturation. Redescendre `min-instances` à 0 ne suffit pas — Cloud Run peut
garder en vie une instance déjà démarrée, et une instance GPU inactive facture
plein tarif (cf. [`cloudrun.md`](cloudrun.md#ce-que-gcp_down-fait-exactement)).
Les deux GPU allumés coûtent ~7 à 8 $/h.

Recréer les services pour la session suivante ne rebuilde rien (images dans
Artifact Registry, code et modèles dans leurs buckets) :

```bash
make cloudrun_deploy_all
```
