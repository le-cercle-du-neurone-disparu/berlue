# Benchmark d'exécution — local vs GCP

Mesure du temps et du coût de chaque étape d'un scope d'éval minimal, en
local et sur GCP (Job Cloud Run `berlue-eval-mocked` + service Ollama
`berlue-llm`) — sert de référence pour estimer le coût d'un run à plus
grande échelle. Scope utilisé partout : `dataset=halueval`, `ratio=0.999`
(10 questions de test, 20 lignes mode 1 — cf.
[`storage.md`](storage.md) pour comment `ratio` détermine la
taille du split), `model_id`/`judge_model` = `llama3.1:8b`. Tâche de
génération scindée en deux moitiés dans les deux modes (simule plusieurs
workers/exécutions sur le même scope), matrices construites une fois les
deux moitiés faites. En mode 2, Berlue et baseline sont deux chemins
totalement séparés (cf. [`modes.md`](modes.md)) : la baseline n'est jamais
calculée pendant les moitiés de génération, uniquement par son propre appel.

## Local

Pré-requis : `ollama serve` actif, `llama3.1:8b` déjà tiré
(`ollama pull llama3.1:8b`). Juge = `llama3.1:8b` également (jamais un
modèle plus petit par souci de vitesse — fausserait la comparaison avec les
autres mesures qui utilisent la même taille de modèle des deux côtés).

```bash
make evaluate_model DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b START=0 END=10
make evaluate_model DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b START=10 END=20
make evaluate_model_matrix DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b
make evaluate_baseline DATASET=halueval RATIO=0.999

# WARMUP=true sur la première moitié seulement : précharge generator+juge en
# VRAM avant de démarrer le chrono de la boucle, pour que son récapitulatif
# de temps ne compte pas le chargement modèle (cf. note ci-dessous)
make evaluate_model_generated DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b START=0 END=5 WARMUP=true
make evaluate_model_generated DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b START=5 END=10
make evaluate_model_generated_matrix DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b
make evaluate_model_generated_baseline DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b START=0 END=10
make evaluate_model_generated_baseline_matrix DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b
```

| Étape | Durée | Détail |
|---|---|---|
| Mode 1, moitié 1 (10 lignes) | 1,09 s | mock, CPU, SQLite local |
| Mode 1, moitié 2 (10 lignes) | 1,07 s | idem |
| Mode 1, matrice | 1,11 s | 20/20 exemples (split complet) |
| Mode 1, baseline | 1,13 s | recalculée à la volée, jamais stockée |
| Mode 2, Berlue, moitié 1 (5 questions, warmup inclus) | 7,68 s | dont 2,90 s de warmup (chargement modèle, cf. note) — génération+Berlue+juge, jamais la baseline |
| Mode 2, Berlue, moitié 2 (5 questions) | 4,15 s | déjà chaud (pas de warmup relancé) |
| Mode 2, Berlue, matrice | 1,17 s | 10/10 questions (split complet), ne dépend jamais de la baseline |
| Mode 2, baseline | 1,14 s | **10 questions classifiées** — seul endroit où la baseline mode 2 tourne (cf. note ci-dessous) |
| Mode 2, matrice baseline | 1,18 s | 10/10, ne dépend jamais du verdict Berlue (cf. [`api.md`](api.md)) |
| **Total** | **~19,7 s** | |

### Détail par tâche (mode 2, hors cache)

Chaque appel de `evaluate_model_generated`/`evaluate_baseline_generated`
affiche un temps moyen par tâche réellement effectuée (jamais les hits de
cache) — bien plus précis que le temps englobant de la commande. Mesuré sur
les 10 questions ci-dessus :

| Tâche | Provient de | Temps moyen / appel | n |
|---|---|---|---|
| Génération (`llama3.1:8b`) | moitiés `evaluate_model_generated` | 0,59 s | 10 |
| Juge (`llama3.1:8b`) | moitiés `evaluate_model_generated` | 0,08 s | 10 |
| Berlue (mock) | moitiés `evaluate_model_generated` | 0,000 s | 10 |
| Baseline NLI (CPU) | `evaluate_model_generated_baseline` | 0,001 s | 10 |

**Warmup** : le premier appel réel à un modèle Ollama pas encore chargé paie
son temps de chargement en VRAM, mélangé au temps d'inférence — sur cette
machine, ~2,8 s pour `llama3.1:8b` (contre ~0,6 s d'inférence en régime
établi). `WARMUP=true` sur la moitié 1 précharge le modèle avant de démarrer
le chrono de la boucle, donc son récapitulatif par tâche ci-dessus reflète le
même régime établi que la moitié 2 (pas de warmup relancé, déjà chaud) —
sans ce préchargement, la moyenne de la moitié 1 inclurait le chargement et
ne serait plus comparable à la moitié 2 ni à une mesure GCP où le service
Ollama a été chauffé au préalable.

**Note sur la baseline mode 2** : `evaluate_model_generated` ne calcule
jamais la baseline (cf. [`modes.md`](modes.md)) — `evaluate_model_generated_baseline`
est le seul endroit où elle tourne, en aval, sur les réponses déjà générées
par les deux moitiés ci-dessus (confirmé : "10 question(s) classifiée(s)",
pas "0"). C'est un classifieur NLI local (CPU), de toute façon quasi gratuit
(0,001 s/appel) — l'essentiel du temps de cet appel (~1,1 s) est le
démarrage Python + rechargement du dataset, pas la classification
elle-même. Même chose pour la matrice baseline : juge et baseline étant déjà
en cache, elle ne fait que lire et comparer.

**Contexte matériel** : machine de dev avec GPU local (NVIDIA RTX 5070 Ti
Laptop, 12 Go VRAM) — les temps mode 2 (génération+juge réels) reflètent
cette carte, pas nécessairement la performance du L4 (24 Go) utilisé sur
GCP. Comparer avec la section GCP ci-dessous plutôt que d'extrapoler depuis
le local seul.

## GCP

Job Cloud Run `berlue-eval-mocked` (CPU, 1 vCPU/512 Mi par défaut) + service
Cloud Run `berlue-llm` (GPU L4, Ollama, `--no-allow-unauthenticated` +
`roles/run.invoker` pour `sa-berlue`). Prérequis : image poussée
(`make docker_build_eval docker_push_eval` / `docker_build_llm
docker_push_llm`), services déployés (`make cloudrun_llm_deploy
cloudrun_eval_deploy`), modèle tiré sur le service Ollama (`/api/pull`, une
fois — perdu si le service retombe à 0, cf. note plus bas).

Berlue et la baseline sont deux chemins totalement séparés (cf.
[`modes.md`](modes.md)), comme en local :

```bash
make cloudrun_eval_run DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b START=0 END=10
make cloudrun_eval_run DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b START=10 END=20
make cloudrun_eval_run DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b MATRIX=true
make cloudrun_eval_baseline DATASET=halueval RATIO=0.999

# WARMUP=true sur la première moitié seulement : précharge generator+juge sur
# berlue-llm avant de démarrer le chrono de la boucle (cf. note warmup plus bas)
make cloudrun_eval_run DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b MODE=generated START=0 END=5 WARMUP=true
make cloudrun_eval_run DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b MODE=generated START=5 END=10
make cloudrun_eval_run DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b MODE=generated MATRIX=true
make cloudrun_eval_baseline_generated DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b START=0 END=10
make cloudrun_eval_baseline_generated_matrix DATASET=halueval RATIO=0.999 MODEL_ID=llama3.1:8b JUDGE_MODEL=llama3.1:8b
```

| Étape | Durée | Détail |
|---|---|---|
| Mode 1, moitié 1 (10 lignes) | 92 s | inclut le provisionnement d'une nouvelle exécution de Job |
| Mode 1, moitié 2 (10 lignes) | 98 s | idem |
| Mode 1, matrice | 97 s | 20/20 (split complet) |
| Mode 1, baseline | 112 s | recalculée à la volée |
| Mode 2, Berlue, moitié 1 (5 questions, warmup inclus) | 177 s | dont ~76 s de warmup (chargement modèle sur `berlue-llm`, cf. note) — génération+Berlue+juge, jamais la baseline |
| Mode 2, Berlue, moitié 2 (5 questions) | 98 s | déjà chaud (pas de warmup relancé) |
| Mode 2, Berlue, matrice | 107 s | 10/10 (split complet), ne dépend jamais de la baseline |
| Mode 2, baseline | 101 s | **10 questions classifiées** — seul endroit où la baseline mode 2 tourne |
| Mode 2, matrice baseline | 70 s | 10/10, ne dépend jamais du verdict Berlue (cf. [`api.md`](api.md)) |
| **Total** | **~952 s (~16 min)** | |

### Détail par tâche (mode 2, hors cache)

Même récapitulatif par tâche qu'en local (cf. section Local ci-dessus),
lu dans les logs des exécutions Job (`gcloud logging read` ou Console) :

| Tâche | Provient de | Temps moyen / appel | n |
|---|---|---|---|
| Génération (`llama3.1:8b` via `berlue-llm`) | moitiés `evaluate_model_generated` | 1,10 s | 10 |
| Juge (`llama3.1:8b` via `berlue-llm`) | moitiés `evaluate_model_generated` | 0,12 s | 10 |
| Berlue (mock) | moitiés `evaluate_model_generated` | 0,000 s | 10 |
| Baseline NLI (CPU, dans le Job) | `evaluate_model_generated_baseline` | 0,003 s | 10 |

Génération et juge sont plus lents qu'en local (0,59 s / 0,08 s, cf. section
Local) — cohérent avec la note "contexte matériel" ci-dessus (GPU L4 vs
RTX 5070 Ti local) plus la latence réseau Job → service `berlue-llm`.

**Warmup** : le premier appel à `berlue-llm` après un `/api/pull` paie le
chargement du modèle en VRAM du service — mesuré ici à **~76 s** (bien plus
qu'en local, ~2,8 s), le GPU L4 de `berlue-llm` partant totalement à froid
(instance elle-même provisionnée à la demande) contre un serveur Ollama déjà
actif en local. `WARMUP=true` sur la moitié 1 isole ce coût du reste : sans
lui, la moyenne par appel de génération de la moitié 1 grimperait à plus de
15 s/appel (chargement + inférence mélangés), rendant les deux moitiés non
comparables entre elles.

**D'où vient la grande différence avec le local (~19,7 s) ?** Pas les
imports Python — vérifié (`python -X importtime`) : le chemin de code du
mode mock (`RandomBerluePipeline`) n'importe ni torch, ni spacy, ni
selfcheckgpt, et le script complet (imports + chargement/split du dataset)
tourne en **~1s en local**, sklearn/pandas/scipy inclus. La différence vient
du modèle d'exécution des **Jobs** Cloud Run lui-même : chaque exécution
provisionne un **conteneur entièrement neuf** (contrairement au local, où
chaque étape de la répétition réutilisait implicitement un environnement
déjà chaud) — ce provisionnement/ordonnancement est une latence
d'infrastructure Cloud Run, pas un temps applicatif, donc pas réductible en
optimisant le code. Proportionnellement lourd sur de petites tranches comme
ici (5-10 lignes/questions) ; deviendrait négligeable sur un run à grande
échelle (moins d'exécutions, plus de travail par exécution).

### Le modèle ne survit pas à un scale-to-zero du service Ollama

`Dockerfile.llm` n'embarque pas de modèle pré-baké (image légère,
`ollama pull` à la demande) — mais le pull écrit sur le disque **éphémère**
du conteneur. Quand `berlue-llm` retombe à 0 instance (comportement par
défaut, pas de délai d'inactivité configurable côté Cloud Run — seulement
`min-instances` fixe ou autoscaling standard, vérifié via la doc
officielle), le modèle est **entièrement perdu**, pas seulement déchargé de
la VRAM : la prochaine requête échoue avec `model 'llama3.1:8b' not found`,
il faut re-pull (~100s, téléchargement réseau réel, mesuré) avant de
pouvoir régénérer. `OLLAMA_KEEP_ALIVE=-1` ne protège que contre le
déchargement VRAM **pendant que l'instance est vivante**, pas contre sa
destruction.

Pendant cette session de tests, `min-instances` est resté à `0` du début à
la fin : un `/api/pull` unique avant de démarrer (~104 s, mesuré), puis les
9 exécutions du Job enchaînées sans pause — l'instance `berlue-llm` est
restée chaude spontanément (pas de délai d'inactivité configurable côté
Cloud Run, mais pas non plus retombée à 0 entre deux appels espacés de
quelques minutes) jusqu'au `make cloudrun_llm_scale_to_zero` final. Aucun
re-pull nécessaire une fois le modèle chargé. Ça reste fragile : un enchaînement
plus espacé dans le temps (ou une session de travail qui s'interrompt entre
deux étapes) peut retomber à 0 et perdre le modèle sans prévenir — `min-instances=1`
temporaire reste l'option pour un enchaînement moins serré, à repasser à `0`
immédiatement après (`make cloudrun_llm_scale_to_zero`), jamais laissé actif
au-delà de la session de test. Options non implémentées pour éviter ça en
usage réel : bake le modèle dans l'image (plus lourde à builder/pousser,
mais résiste au scale-to-zero), ou un volume persistant (GCS FUSE) pour
`/root/.ollama`.

### Coût estimé de cette session de tests (approximatif, pas une facture)

- **Job d'éval** (CPU/mémoire seuls, ~952s cumulés sur toutes les étapes) :
  ~0,03 $ — négligeable, couvert par le free tier Cloud Run.
- **Service Ollama** (GPU L4 + 4 CPU/16 Gi) : actif environ 18-20 min sur
  cette session (`/api/pull` → retour à `min-instances=0`, jamais fixé à 1)
  → **~0,20-0,25 $ estimé** (GPU ~0,67 $/h + CPU/mémoire du service, sur une
  fraction d'heure). Chiffre approximatif (pas de lecture de facturation
  réelle, cf. `make gcp_enable_cost_observability` pour activer l'onglet
  "Cost" par service dans la Console) — du même ordre que la session
  précédente sur ce même refactor (~0,20 $), nettement moins que la toute
  première session (~1,40 $) qui avait laissé le service actif ~1h10-1h15.
