# GPU sur Cloud Run — choix de machine et parallélisme

Deux services portent un GPU :

- **`berlue-llm`** (Ollama) sert tous les appels LLM : ceux de `/predict`
  (génération, extraction, échantillons SelfCheck, jugement RAG) et ceux de
  l'évaluation (le même pipeline, plus génération et juge en mode 2). Commandes :
  [`cloudrun.md`](cloudrun.md#service-ollama-berlue-llm).
- **`berlue-api-<env>`** fait tourner en process le NLI de SelfCheck
  (DeBERTa-large) et les embeddings du RAG. Sur CPU, SelfCheck fait les deux
  tiers du temps d'une requête ; sur GPU, il passe sous la seconde (mesures :
  [`latence-predict.md`](latence-predict.md)). Le GPU de `berlue-llm` n'est
  joignable qu'en HTTP via Ollama : l'API a besoin de sa propre carte.

Le service d'éval (`berlue-eval`) reste sans GPU.

## Types de GPU

Deux types de GPU existent sur Cloud Run :

| Type | VRAM | Minimums imposés | Régions | Utilisé par |
|---|---|---|---|---|
| `nvidia-l4` | 24 Go | 4 CPU / 16 Gi, **8 CPU / 32 Gi au plus** | `europe-west1`, `europe-west4`, `us-central1`, `us-east4`, `asia-southeast1`, `asia-south1` | `berlue-api-<env>` (`API_GPU_TYPE`) |
| `nvidia-rtx-pro-6000` (Blackwell) | 96 Go | **20 CPU / 80 Gi** | `europe-west4`, `us-central1`, `asia-southeast1`, `asia-south2` — pas `europe-west1` | `berlue-llm` (`LLM_GPU_TYPE`) |

**`berlue-llm` sur RTX PRO 6000** : les deux modèles du pipeline
(`llama3.1:8b` 8,5 Go + `llama3.2:3b` 5,5 Go, VRAM mesurée) tiennent ensemble
avec leurs slots parallèles. Sur les 24 Go d'un L4, ils saturent la carte et
s'évincent mutuellement pendant une requête. C'est ce GPU qui fixe la région
des services, `europe-west4` (cf. `make/config.mk`).

**L'API sur L4** : DeBERTa-large et `all-mpnet-base-v2` tiennent en ~2,4 Go ;
le L4 est le moins cher des deux et suffit largement.

Repli tout L4, par exemple pour une région sans RTX PRO 6000 (~0,67 $/h le
GPU, mais les deux modèles se disputent 24 Go) :

```bash
make cloudrun_llm_deploy LLM_GPU_TYPE=nvidia-l4 LLM_CPU=8 LLM_MEMORY=32Gi
```

Une API sans GPU : `make cloudrun_deploy API_GPU_TYPE= GAR_CPU=2 GAR_MEMORY=8Gi`.

## Un seul service Ollama partagé, pas un par rôle

Les rôles servis par Ollama (l'embedding du RAG n'en fait pas partie :
`berlue/rag/retriever.py` charge `sentence-transformers` en process, dans
l'API) :

- **Génération** (`OllamaClient(model=scope.model_id)`) — le modèle
  **évalué**, variable par nature (comparer différents modèles est tout
  l'intérêt du système) : pas figeable sur une instance dédiée.
- **Extraction** (`EXTRACT_MODEL`), **jugement RAG** (`RAG_MODEL`) et
  **juge** d'évaluation (`JUDGE_MODEL`) — fixes, `llama3.1:8b` par défaut.
- **Échantillonnage SelfCheckGPT** — réutilise le client de génération,
  pas un rôle à part.

Un seul service partagé, plutôt qu'un par rôle :

- `OLLAMA_MAX_LOADED_MODELS` (défaut = 3 × nb GPU, donc **3** sur un GPU
  unique) laisse plusieurs modèles chargés en VRAM tant qu'ils tiennent
  ensemble, sans rechargement à chaque requête.
- Le modèle évalué étant par nature variable (ensemble ouvert, pas un
  rôle fixe), une instance dédiée par modèle n'a pas de sens — un serveur
  partagé qui charge à la demande est la seule approche qui tient pour ce
  rôle précis.
- Le GPU Cloud Run est facturé à la seconde d'utilisation
  (scale-to-zero à l'arrêt) — multiplier les services multiplie le risque
  de GPU payé mais peu utilisé, pour un usage batch.
- Cohérent avec le pattern officiel Google (tutoriel Ollama+Gemma sur
  Cloud Run GPU) : un seul service Ollama, pas un par modèle appelant.

**Quand reconsidérer** (déclencheur, pas une règle absolue) : si un modèle
évalué devient nettement plus gros que ce que le GPU peut porter en même
temps qu'extraction+juge, `OLLAMA_MAX_LOADED_MODELS` retombe sous pression
VRAM — Ollama met en file d'attente et décharge/recharge les modèles
inactifs, retombant sur le coût de cold start (11-35s mesuré) en pleine
exécution. Séparer par classe de taille de modèle (juge/extraction sur un
service économe, génération sur un service dédié plus gros) redeviendrait
alors pertinent — pas le cas avec les modèles par défaut actuels.

## Parallélisme : combien tient en VRAM

`cloudrun_llm_deploy` déploie avec `--concurrency=4` et
`OLLAMA_NUM_PARALLEL=4` (`make/cloudrun.mk`) — alignés l'un sur l'autre,
suivant la recommandation du tutoriel officiel Google.

Les poids du modèle sont chargés **une seule fois**, partagés par tous les
slots parallèles (et par les rôles qui utilisent le même `model_id` —
génération+juge sur `llama3.1:8b` dans l'éval, par exemple, un seul jeu de
poids pour les deux). Ce qui scale avec `OLLAMA_NUM_PARALLEL`, c'est le
**KV-cache par requête en cours** (le contexte de génération), pas les
poids — confirmé par l'API/FAQ Ollama : *"required RAM scales by
OLLAMA_NUM_PARALLEL × OLLAMA_CONTEXT_LENGTH"*, formule indépendante de la
taille du modèle.

```
VRAM utilisée ≈ poids_du_modèle (une fois par modèle distinct chargé)
              + Σ (slots_parallèles × contexte_par_slot × coût_kv_cache_par_token)
              + overhead fixe
```

**Plafond réel par taille de modèle**, `N_max = ⌊(VRAM_libre − poids − compute − marge_1024) / KV-cache_par_slot⌋`
(`OLLAMA_CONTEXT_LENGTH=4096`, cache f16 — dérivation de la formule :
[`ollama-gpu-parallelism.md`](ollama-gpu-parallelism.md)) :

| Modèle (Q4) | Poids | KV-cache/slot | GPU | VRAM libre | `N_max` |
|---|---|---|---|---|---|
| `qwen2.5:0.5b` | 373 Mio | 48 Mio | RTX 5070 Ti Laptop, 12 Go | 11537 Mio | **210** |
| `llama3.1:8b` | 4403 Mio | 512 Mio | RTX 5070 Ti Laptop, 12 Go | 11537 Mio | **11** |
| `qwen2.5:14b` | 8148 Mio | 768 Mio | RTX 5070 Ti Laptop, 12 Go | 11537 Mio | **2** |
| `llama3.1:8b` | 4403 Mio | 512 Mio | `berlue-llm` (L4, 24 Go) | 22528 Mio | **33** |
| `qwen2.5:14b` | 8148 Mio | 768 Mio | `berlue-llm` (L4, 24 Go) | 22528 Mio | **17** |

Poids/KV-cache mesurés directement (`common_memory_breakdown_print`,
`sudo journalctl -u ollama`, `NUM_PARALLEL=1` pour lire le poste `model`
sans interférence du contexte) sur une RTX 5070 Ti Laptop pour les trois
premières lignes — table complète pour d'autres tailles de modèle :
[`ollama-gpu-parallelism.md`](ollama-gpu-parallelism.md#modèles-mesurés--référence).
VRAM libre du L4 mesurée en conditions réelles sur `berlue-llm`
(`make cloudrun_llm_logs`) : `"vram-based default context"
total_vram="22.0 GiB"` — Ollama **auto-ajuste** le contexte par slot
selon la VRAM disponible plutôt que de planter si la configuration
demandée est trop juste. Les deux lignes L4 appliquent la formule à cette
VRAM libre réelle (poids/KV-cache identiques à ceux mesurés sur la RTX
5070 Ti, indépendants du GPU pour un même modèle/quantization) ; non
revérifiées par un `common_memory_breakdown_print` sur `berlue-llm`
lui-même.

`cloudrun_llm_deploy` déploie avec `NUM_PARALLEL=4` — bien sous le plafond
de 33 calculé ci-dessus pour `llama3.1:8b` sur un L4. Sur le RTX PRO 6000 (96 Go),
le plafond est plus haut encore ; il n'a pas été mesuré.

## Candidats plus gros pour le modèle évalué

Un modèle nettement plus gros que `llama3.1:8b` est un candidat plausible
pour le rôle de génération — vérifier que même de très gros modèles
hallucinent dans certains cas de démo fait partie de l'intérêt du système.
**Estimations uniquement**, à partir du seul nombre de paramètres et du
ratio poids Q4_K_M ≈ 0,573 Gio/milliard mesuré sur les 13 modèles de la
table ci-dessus — aucun de ces modèles n'a été pullé/chargé, ni son
`n_layers`/`n_kv_heads`/`head_dim` réel vérifié (cf. le piège `gemma2`
plus haut sur ce point précis) :

| Modèle candidat | Paramètres | Poids estimé (Q4) | VRAM restante sur L4 (compute+marge déduits) | Faisabilité |
|---|---|---|---|---|
| `gemma2:27b` | 27B | ~15854 Mio | ~5520 Mio pour le KV-cache | plausible, quelques slots |
| `qwen2.5:32b` | 32B | ~18775 Mio | ~2599 Mio pour le KV-cache | plausible, parallélisme faible |
| `yi:34b` | 34B | ~19942 Mio | ~1432 Mio pour le KV-cache | tendu, 1-2 slots au mieux |
| `command-r:35b` | 35B | ~20535 Mio | ~839 Mio pour le KV-cache | très tendu, probablement 1 seul slot |
| `llama3.1:70b` | 70B | ~41055 Mio | négatif — ne tient pas sur un seul L4 (24 Go) | non — RTX PRO 6000 (96 Go) ou quantization plus forte |

À confirmer par une vraie mesure (`ollama pull` + `common_memory_breakdown_print`,
comme pour les 13 modèles déjà dans [`ollama-gpu-parallelism.md`](ollama-gpu-parallelism.md#modèles-mesurés--référence))
avant de retenir un candidat précis pour l'éval.

## Combien de vCPU pour `berlue-llm`

Le nombre de vCPU d'un service à 1 GPU est borné par Cloud Run : **au moins
20 vCPU / 80 Gio sur RTX PRO 6000** (le défaut de `cloudrun_llm_deploy`), et
**au plus 8 vCPU / 32 Gio sur L4** (`.08-1, 1, 2, 4, 6, 8` sont les seules
valeurs acceptées, `gcloud` refuse le reste).

Le vCPU alloué ne sert pas le calcul GPU lui-même (ça, c'est
`OLLAMA_NUM_PARALLEL`, cf. [`ollama-gpu-parallelism.md`](ollama-gpu-parallelism.md))
mais la gestion des connexions/requêtes concurrentes côté serveur — un
sous-dimensionnement s'y manifeste par de vrais rejets HTTP (429/503), pas
juste une latence plus élevée. Mesuré sur L4 (`llama3.1:8b`,
`OLLAMA_NUM_PARALLEL` calé sur la charge à chaque palier, détail dans
[`execution-benchmark.md`](../evaluation/execution-benchmark.md)) :

| vCPU | Prix | 16 concurrents | 32 concurrents |
|---|---|---|---|
| 4 | 1,05 $/h | 69,3 tok/s, 0% échec | 83,5 tok/s, **12,7% échec réel** |
| 6 | 1,23 $/h | 89,7 tok/s, 0% échec | 93,6 tok/s, 0% échec |
| 8 | 1,42 $/h | 92,8 tok/s, 0% échec | **145,0 tok/s, 0% échec** |

Prix = GPU L4 (0,672 $/h, fixe quel que soit le vCPU) + CPU (0,0648 $/h/vCPU)
+ mémoire (0,0072 $/h/Gio), tarifs catalogue `europe-west1`, config
`--no-gpu-zonal-redundancy`.

À faible concurrence les trois tailles se valent (4 vCPU tient très bien à
16). Dès qu'on vise une vraie concurrence de run (32+), **8 vCPU l'emporte
nettement, en débit et en tok/s par dollar dépensé** (102 vs 76 à 6 vCPU) —
et c'est le seul sans erreur serveur : en repli L4, déployer à 8 vCPU / 32 Gio.

## Mécanique détaillée du parallélisme et test de charge

Formule exacte du coût VRAM par slot parallèle (dérivée des paramètres
d'architecture du modèle, vérifiée empiriquement par un test de charge
poussé jusqu'à la casse), et ce qui relève de la physique de l'inférence
transformer vs des choix de politique Ollama/llama.cpp :
[`ollama-gpu-parallelism.md`](ollama-gpu-parallelism.md).

`OLLAMA_MAX_LOADED_MODELS` et `OLLAMA_NUM_PARALLEL` ne sont réévalués
qu'au déclencheur décrit plus haut (modèle évalué trop gros) — pas de
suivi automatique de la pression VRAM aujourd'hui.

Bake le modèle dans l'image (`Dockerfile.llm`) ou volume persistant
(GCS FUSE) pour `/root/.ollama`, pour survivre à un scale-to-zero sans
re-pull — non implémenté, cf. [`cloudrun.md`](cloudrun.md#service-ollama-berlue-llm).
