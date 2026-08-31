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

## Parallélisation (mode généré)

`CONCURRENCY` (cf. [`run.md`](run.md)) parallélise chaque étape de
`evaluate_model_generated` (génération, Berlue, juge) par un pool de
threads — une étape à la fois sur tout le lot, questions dépilées en
parallèle au sein de chaque étape. Chaque appel LLM est borné en longueur
(`num_predict`) pour un pire cas prévisible, indépendant de la charge ou de
la config serveur.

**Règle centrale, vérifiée sur les deux environnements** : `OLLAMA_NUM_PARALLEL`
(côté serveur) doit être **calé sur `CONCURRENCY`** (côté éval), pas
maximisé — un serveur configuré avec plus de slots que la charge réelle
est nettement moins performant, pas juste "sans bénéfice" (mécanisme et
comparaison chiffrée : [`ollama-gpu-parallelism.md`](../gcp/ollama-gpu-parallelism.md)).
Toutes les mesures ci-dessous suivent cette règle (`LLM_NUM_PARALLEL` =
`CONCURRENCY` testé, à chaque palier).

### Local

`llama3.1:8b` des deux côtés, `OLLAMA_CONTEXT_LENGTH=1024` (largement
suffisant pour les prompts courts de l'éval), 500 questions (`ratio=0.8`,
assez pour occuper tous les threads en régime stable — un lot trop petit
dilue le gain) :

```bash
# exemple à CONCURRENCY=24 — reconfigurer OLLAMA_NUM_PARALLEL=24 côté
# serveur avant de lancer (systemd override en dev, cf. ollama-gpu-parallelism.md)
make evaluate_model_generated DATASET=halueval RATIO=0.8 \
  MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b START=0 END=500 CONCURRENCY=24
```

| `CONCURRENCY` | Temps total | | `CONCURRENCY` | Temps total |
|---|---|---|---|---|
| 1 | 373,4 s | | 22 | 101 s |
| 4 | 191 s | | 24 | 101 s |
| 8 | 177 s | | **26** | **98 s (meilleur)** |
| 16 | 109 s | | 28 | 101 s |
| 18 | 104 s | | 30 | 103 s |
| 20 | 102 s | | 32 | 103 s |
| | | | 40 | 107 s |

Plateau large et plat de 18 à 40 (98-109 s, écarts proches du bruit de
mesure) — en dessous de 16, dégradation nette. Toute valeur entre 18 et 32
est quasi optimale sur cette carte (RTX 5070 Ti Laptop, 12 Go) ; pas de
gain à monter plus haut.

### GCP

`berlue-llm` (L4), `OLLAMA_CONTEXT_LENGTH=1024`, redéployé à chaque palier
avec `LLM_NUM_PARALLEL` = `CONCURRENCY` testé :

```bash
make cloudrun_llm_deploy LLM_NUM_PARALLEL=32 LLM_CONCURRENCY=42 LLM_CONTEXT_LENGTH=1024 LLM_CPU=8 LLM_MEMORY=32Gi
make gcp_up DATASET=halueval RATIO=0.8 WARM_MODELS="llama3.1:8b"
make cloudrun_eval_service_invoke DATASET=halueval RATIO=0.8 \
  MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b MODE=generated START=0 END=500 CONCURRENCY=32
```

Débit agrégé mesuré au stress test (`scripts/ollama_load_test.py` contre
`berlue-llm` directement, 8 vCPU — méthode plus rapide que le batch complet
pour balayer beaucoup de paliers, cf. [`cloudrun.md`](../gcp/cloudrun.md)) :

| `CONCURRENCY`=`NUM_PARALLEL` | Débit agrégé | Échec |
|---|---|---|
| 8 | 110,6 tok/s | 0% |
| 16 | 92,8 tok/s | 0% |
| 24 | 116,8 tok/s | 0% |
| **32** | **145,0 tok/s** | 0% |
| 40 | 143,1 tok/s | 0% |
| 48 | 69,0 tok/s | 46,9%* |
| 64 | 134,8 tok/s | 12,5%* |
| 80 | 110,9 tok/s | 23,7%* |
| 96 | 110,4 tok/s | 0% |

\* Erreurs HTTP 429 réelles (rejet serveur), pas des timeouts client —
mesure faite une seule fois par palier, pas assez de répétitions pour
confirmer si c'est un vrai plafond autour de 48 ou un aléa d'infra
ponctuel (64/80/96 ne montrent pas une dégradation propre et croissante,
ce qui serait attendu si c'était un plafond structurel). **`CONCURRENCY=32`
reste le réglage recommandé** — meilleur point mesuré, dans une zone
propre sans aucune erreur.

**vCPU de `berlue-llm`** — 8 (le maximum autorisé par Cloud Run pour 1 GPU)
recommandé dès qu'on vise une vraie concurrence, malgré le surcoût : à
`CONCURRENCY=16`, 4/6/8 vCPU sont proches (66-73 tok/s par $/h dépensé) ;
à `CONCURRENCY=32`, 8 vCPU domine nettement (102 tok/s par $/h, contre 76
à 6 vCPU) et c'est le seul sans erreur serveur (4 vCPU : 12,7% d'échec réel
à 32, mécanisme et détail des prix dans [`infra-gpu.md`](../gcp/infra-gpu.md)).

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
