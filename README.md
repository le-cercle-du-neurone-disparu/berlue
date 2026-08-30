# Berlue

Détecteur d'hallucinations LLM : pose une question à un LLM local (Ollama),
découpe sa réponse en affirmations atomiques, puis vérifie chacune par deux
voies indépendantes avant de fusionner leur verdict.

1. Le LLM génère une réponse à la question posée.
2. La réponse est découpée en affirmations atomiques.
3. Chaque affirmation est vérifiée par deux voies indépendantes :
   - **SelfCheckGPT** (`berlue/selfcheck/`) — zero-resource, ne vérifie rien
     contre une source externe : le LLM se contredit-il sur plusieurs
     tirages de la même question ?
   - **RAG inversé** (`berlue/rag/`) — cherche des preuves dans le corpus
     FEVER (embeddings + FAISS) et vote sur les labels des plus proches
     voisins.
4. **Fusion** (`HurluBerlu.fuse_results`) combine les deux en un verdict
   (`supported` / `contradicted` / `not_enough_info`) par affirmation.

L'orchestrateur de ce pipeline est `berlue/pipeline/hurlu_berlu.py` — voir
[`hurlu_berlu.md`](docs/pipeline/hurlu_berlu.md) pour le lancer étape par étape.

Une baseline plus simple (`berlue/nli_baseline/`, TF-IDF + régression
logistique, sans RAG) sert de point de comparaison en évaluation offline —
voir [`baseline.md`](docs/evaluation/baseline.md).

## Démarrage rapide

```bash
make local_setup   # environnement virtuel (pyenv) + dépendances
make ollama_setup  # installe et démarre Ollama en local
```

Puis, étape par étape (voir [`hurlu_berlu.md`](docs/pipeline/hurlu_berlu.md) pour le détail) :

```bash
make pipeline_extract QUESTION="Pourquoi la mer est salée ?"
```

## Documentation

| | |
|---|---|
| **Setup** (préparer sa machine) | [`local-setup.md`](docs/setup/local-setup.md) · [`ollama-setup.md`](docs/setup/ollama-setup.md) · [`gcp.md`](docs/setup/gcp.md) |
| **Dev** | [`structure.md`](docs/dev/structure.md) (plan du code) · [`linting.md`](docs/dev/linting.md) · [`tests.md`](docs/dev/tests.md) |
| **Pipeline** (comment tourne chaque brique de Berlue) | [`hurlu_berlu.md`](docs/pipeline/hurlu_berlu.md) (orchestrateur) · [`llm.md`](docs/pipeline/llm.md) · [`extraction.md`](docs/pipeline/extraction.md) · [`selfcheck.md`](docs/pipeline/selfcheck.md) · [`rag.md`](docs/pipeline/rag.md) · [`fusion.md`](docs/pipeline/fusion.md) |
| **Evaluation** (mesurer Berlue face à une baseline) | [`docs/evaluation/`](docs/evaluation/) |
| **GCP** (composants, authentification, accès équipe) | [`setup/gcp.md`](docs/setup/gcp.md) · [`composants.md`](docs/gcp/composants.md) · [`cloudrun.md`](docs/gcp/cloudrun.md) · [`infra-gpu.md`](docs/gcp/infra-gpu.md) · [`auth.md`](docs/gcp/auth.md) · [`share.md`](docs/gcp/share.md) |
| **Repo** (gestion du dépôt pour l'équipe) | [`github-config.md`](docs/repo/github-config.md) · [`webhook-slack.md`](docs/repo/webhook-slack.md) |
| **Datasets** (aperçu rapide) | [`fever.md`](docs/datasets/fever.md) · [`halueval.md`](docs/datasets/halueval.md) · [`truthfulqa.md`](docs/datasets/truthfulqa.md) |
| **Historique Etude Dataset** | [`historique-etude-data/`](historique-etude-data/) — matériel de travail, pas la doc de référence |

## Mise en service & API

Le déploiement de l'API suit un processus de validation strict en 3 étapes (méthodologie Fail-Fast) :

### Étape 1 : Développement natif local
Implémentez vos endpoints FastAPI dans `berlue/api/fast.py`. Lancez l'API nativement sur votre machine pour une itération rapide et un rechargement à chaud :
```bash
make run_api
```
*Vérifiez la logique de votre code :*
```bash
make test_fast
```

### Étape 2 : Vérification Docker locale
Une fois l'API native fonctionnelle, assurez-vous qu'elle tourne correctement dans son conteneur isolé. Cela permet de détecter les dépendances manquantes avant le déploiement dans le cloud.
```bash
make docker_build_local
make docker_run_local
```
*Vérifiez votre API conteneurisée :*
```bash
make test_functional
```

### Étape 3 : Déploiement Cloud (test → staging → prod)
Une fois le conteneur local validé, construisez l'image de production (plus légère, sans les dépendances de dev) et déployez-la sur 3 environnements Cloud Run (test → staging → prod), une seule image promue progressivement — toutes les commandes (build/push, déploiement par environnement) :
[`cloudrun.md`](docs/gcp/cloudrun.md) — authentification :
[`auth.md`](docs/gcp/auth.md), gestion d'accès : [`share.md`](docs/gcp/share.md).

*Vérifiez votre endpoint en direct* ([`cloudrun.md`](docs/gcp/cloudrun.md)) :

```bash
make cloudrun_url CLOUDRUN_ENV=...
```
