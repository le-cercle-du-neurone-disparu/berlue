# Benchmark d'exécution — local vs GCP

Mesure du temps et du coût de chaque étape d'un scope d'éval minimal, en
local et sur GCP (service Cloud Run `berlue-eval-mocked-service` + service
Ollama `berlue-llm`) — sert de référence pour estimer le coût d'un run à
plus grande échelle. Scope utilisé partout : `dataset=halueval`,
`ratio=0.995` (50 questions de test, 100 lignes mode 1 — cf.
[`storage.md`](storage.md) pour comment `ratio` détermine la taille du
split), `model_id`/`judge_model` = `llama3.1:8b`. En mode 2, Berlue et
baseline sont deux chemins totalement séparés (cf. [`modes.md`](modes.md)).

## Local

Pré-requis : `ollama serve` actif, `llama3.1:8b` déjà tiré
(`ollama pull llama3.1:8b`). Juge = `llama3.1:8b` également (jamais un
modèle plus petit par souci de vitesse — fausserait la comparaison).

```bash
make evaluate_model DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b START=0 END=50
make evaluate_model DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b START=50 END=100
make evaluate_model_matrix DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b
make evaluate_baseline DATASET=halueval RATIO=0.995

# WARMUP=true sur la première moitié seulement : précharge generator+juge en
# VRAM avant de démarrer le chrono de la boucle, pour que son récapitulatif
# de temps ne compte pas le chargement modèle (cf. note ci-dessous)
make evaluate_model_generated DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b START=0 END=25 WARMUP=true
make evaluate_model_generated DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b START=25 END=50
make evaluate_model_generated_matrix DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b
make evaluate_model_generated_baseline DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b
make evaluate_model_generated_baseline_matrix DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b
```

| Étape | Durée | Détail |
|---|---|---|
| Mode 1, moitié 1 (50 lignes) | 1,06 s | mock, CPU, SQLite local |
| Mode 1, moitié 2 (50 lignes) | 1,06 s | idem |
| Mode 1, matrice | 1,07 s | 100/100 exemples (split complet) |
| Mode 1, baseline | 1,05 s | recalculée à la volée, jamais stockée |
| Mode 2, Berlue, moitié 1 (25 questions, warmup inclus) | 17,6 s | dont 2,93 s de warmup (chargement modèle, cf. note) — génération+Berlue+juge, jamais la baseline |
| Mode 2, Berlue, moitié 2 (25 questions) | 15,5 s | déjà chaud (pas de warmup relancé) |
| Mode 2, Berlue, matrice | 1,01 s | 50/50 questions (split complet), ne dépend jamais de la baseline |
| Mode 2, baseline | 1,21 s | 50 questions classifiées — seul endroit où la baseline mode 2 tourne |
| Mode 2, matrice baseline | 1,01 s | 50/50, ne dépend jamais du verdict Berlue |
| **Total** | **~41,6 s** | |

### Détail par tâche (mode 2, hors cache)

Chaque appel de `evaluate_model_generated`/`evaluate_baseline_generated`
affiche un temps moyen par tâche réellement effectuée (jamais les hits de
cache) — bien plus précis que le temps englobant de la commande. `n` reflète
la réutilisation réelle du cache : une question déjà répondue pour ce
`model_id`/`generation_version` (par un scope antérieur, même sur un autre
`ratio` — `llm_answers` n'est pas indexée sur `ratio`, cf.
[`storage.md`](storage.md)) n'est jamais régénérée :

| Tâche | Temps moyen / appel | n |
|---|---|---|
| Génération (`llama3.1:8b`) | 0,615 s | 40 |
| Juge (`llama3.1:8b`) | 0,079 s | 40 |
| Berlue (mock) | 0,000 s | 50 |
| Baseline NLI (CPU) | 0,0003 s | 50 |

**Warmup** : le premier appel réel à un modèle Ollama pas encore chargé paie
son temps de chargement en VRAM, mélangé au temps d'inférence — sur cette
machine, ~2,8 s pour `llama3.1:8b` (contre ~0,6 s d'inférence en régime
établi). `WARMUP=true` sur la moitié 1 précharge le modèle avant de démarrer
le chrono, pour rester comparable à la moitié 2 (déjà chaude).

**Contexte matériel** : machine de dev avec GPU local (NVIDIA RTX 5070 Ti
Laptop, 12 Go VRAM) — les temps mode 2 reflètent cette carte, pas
nécessairement la performance du L4 (24 Go) utilisé sur GCP.

## GCP

```bash
make gcp_up DATASET=halueval RATIO=0.995 WARM_MODELS="llama3.1:8b"
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b START=0 END=50
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b START=50 END=100
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b MATRIX=true
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.995 BASELINE=true
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b MODE=generated START=0 END=25 WARMUP=true
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b MODE=generated START=25 END=50
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b MODE=generated MATRIX=true
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b MODE=generated BASELINE=true
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.995 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b MODE=generated BASELINE=true MATRIX=true
make gcp_down
```

Mesuré en conditions réelles (`llama3.1:8b` des deux côtés), instance déjà
chaude (après `gcp_up`) :

| Étape | Durée | Détail |
|---|---|---|
| `gcp_up` (`berlue-eval` + `berlue-llm`, modèle tiré+chargé) | ~4 min 20 s | one-shot, avant la série de runs |
| Mode 1, moitié 1 (50 lignes) | 5,0 s | |
| Mode 1, moitié 2 (50 lignes) | 4,8 s | |
| Mode 1, matrice | 6,1 s | 100/100 (split complet) |
| Mode 1, baseline | 0,6 s | recalculée à la volée |
| Mode 2, Berlue, moitié 1 (25 questions, warmup inclus) | 42,5 s | dont ~10,2 s de warmup (chargement modèle sur `berlue-llm`, cf. note) |
| Mode 2, Berlue, moitié 2 (25 questions) | 32,2 s | déjà chaud |
| Mode 2, Berlue, matrice | 5,7 s | 50/50 (split complet) |
| Mode 2, baseline | 4,9 s | |
| Mode 2, matrice baseline | 4,6 s | 50/50 |
| `gcp_down` | ~30 s | one-shot, en fin de session |
| **Total (hors `gcp_up`/`gcp_down`)** | **~106 s (~1 min 46 s)** | |

### Détail par tâche (mode 2, hors cache)

Même récapitulatif par tâche qu'en local, lu dans les logs du service
(`gcloud logging read` ou Console) :

| Tâche | Temps moyen / appel | n |
|---|---|---|
| Génération (`llama3.1:8b` via `berlue-llm`) | 1,16 s | 40 |
| Juge (`llama3.1:8b` via `berlue-llm`) | 0,123 s | 40 |
| Berlue (mock) | 0,000 s | 50 |
| Baseline NLI (CPU, dans l'instance) | ~0,001 s | 50 |

Génération et juge sont ~1,9× plus lents qu'en local — cohérent avec la
note "contexte matériel" ci-dessus (GPU L4 vs RTX 5070 Ti local) plus la
latence réseau entre l'instance d'éval et `berlue-llm`.

**Warmup** : le premier appel à `berlue-llm` après un `/api/pull` paie le
chargement du modèle en VRAM du service — mesuré ici à **~10,2 s**
(contre ~2,8 s en local), le GPU L4 partant plus froid qu'un serveur Ollama
déjà actif localement. `WARMUP=true` sur la moitié 1 isole ce coût du
reste, pour rester comparable à la moitié 2 (déjà chaude).

### Le modèle ne survit pas à un scale-to-zero du service Ollama

Concerne `berlue-llm` seul. `Dockerfile.llm` n'embarque pas de
modèle pré-baké (image légère, `ollama pull` à la demande) — mais le pull
écrit sur le disque **éphémère** du conteneur. Quand `berlue-llm` retombe à
0 instance (comportement par défaut, pas de délai d'inactivité
configurable côté Cloud Run — seulement `min-instances` fixe ou
autoscaling standard), le modèle est **entièrement perdu**, pas seulement
déchargé de la VRAM : la requête suivante échoue avec
`model 'llama3.1:8b' not found`, il faut re-pull (~100s, téléchargement
réseau réel, mesuré) avant de pouvoir régénérer. `OLLAMA_KEEP_ALIVE=-1` ne
protège que contre le déchargement VRAM **pendant que l'instance est
vivante**, pas contre sa destruction — d'où `gcp_up`/`gcp_down` (min-instances
flip explicite) plutôt qu'un `min-instances` laissé actif entre deux
sessions. Options non implémentées pour éviter le re-pull en usage
prolongé : bake le modèle dans l'image (plus lourde à builder/pousser, mais
résiste au scale-to-zero), ou un volume persistant (GCS FUSE) pour
`/root/.ollama`.

### Coût estimé (approximatif, pas une facture)

- **Service d'éval** (CPU/mémoire seuls) : négligeable, couvert par le free
  tier Cloud Run.
- **Service Ollama** (GPU L4 + 4 CPU/16 Gi) : ~0,67 $/h tant que
  `min-instances=1` — de l'ordre de 0,20-0,30 $ pour une session de 20-30
  min (`gcp_up` → série de runs → `gcp_down` immédiat). Chiffre approximatif
  (pas de lecture de facturation réelle — `make
  gcp_enable_cost_observability` pour activer l'onglet "Cost" par service
  dans la Console).
