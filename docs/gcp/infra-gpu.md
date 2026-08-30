# GPU sur Cloud Run — choix de machine et parallélisme

Seul le **mode 2** de l'évaluation (réponse générée + juge,
`evaluate_model_generated`) appelle un LLM réel — le mode 1 (mock,
`RandomBerluePipeline`) n'a besoin d'aucun GPU. Le service Ollama
(`berlue-llm`) est donc dimensionné pour ce seul usage : batch,
prévisible, pas de trafic interactif continu. Commandes de déploiement :
[`cloudrun.md`](cloudrun.md#service-ollama-berlue-llm).

## Type de GPU retenu

Deux types de GPU seulement existent sur Cloud Run aujourd'hui (services
et jobs) — pas de choix plus large :

| Type | VRAM | Minimums imposés | Régions |
|---|---|---|---|
| **`nvidia-l4`** (retenu) | 24 Go | 4 CPU / 16 Gi (8 CPU / 32 Gi recommandé) | `europe-west1` ✅, `europe-west4`, `us-central1`, `us-east4`, `asia-southeast1`, `asia-south1` |
| `nvidia-rtx-pro-6000` (Blackwell) | 96 Go | 20 CPU / 80 Gi | `europe-west4`, `us-central1`, `asia-southeast1`, `asia-south2` — pas `europe-west1` |

`nvidia-l4` : largement suffisant pour des modèles 7-8B (`llama3.1:8b`,
`qwen2.5:0.5b`), minimums CPU/mémoire nettement plus légers, et c'est le
seul des deux disponible dans `europe-west1` (région du projet) — le RTX
PRO 6000 forcerait soit un changement de région, soit un coût de base
élevé pour une VRAM surdimensionnée par rapport aux modèles évalués ici.

## Un seul service Ollama partagé, pas un par rôle

Trois rôles servis par Ollama aujourd'hui (le RAG n'en fait pas partie —
`berlue/rag/retriever.py` charge un modèle d'embedding
`sentence-transformers` en process, pas de serveur séparé) :

- **Génération** (`OllamaClient(model=scope.model_id)`) — le modèle
  **évalué**, variable par nature (comparer différents modèles est tout
  l'intérêt du système) : pas figeable sur une instance dédiée.
- **Extraction** (`EXTRACT_MODEL`) et **juge** (`JUDGE_MODEL`) — fixes,
  petits.
- **Échantillonnage SelfCheckGPT** — réutilise le client de génération,
  pas un rôle à part.

Un seul service partagé, plutôt qu'un par rôle :

- `OLLAMA_MAX_LOADED_MODELS` (défaut = 3 × nb GPU, donc **3** sur un L4
  unique) coïncide exactement avec ces 3 rôles — plusieurs modèles
  peuvent rester chargés simultanément en VRAM tant qu'ils tiennent
  ensemble dans les 24 Go, sans rechargement à chaque requête.
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
évalué devient nettement plus gros que ce que le L4 peut porter en même
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

`cloudrun_llm_deploy` déploie `llama3.1:8b` avec `NUM_PARALLEL=4` — bien
sous le plafond de 33 : large marge disponible avant que le parallélisme
serveur ne devienne le facteur limitant sur ce GPU.

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
