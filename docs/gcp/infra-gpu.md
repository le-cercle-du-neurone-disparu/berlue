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

**Le mauvais modèle mental** : calculer "taille du modèle × nombre de
slots parallèles" pour voir si ça tient en VRAM. Les poids du modèle sont
chargés **une seule fois**, partagés par tous les slots parallèles (et
par les rôles qui utilisent le même `model_id` — génération+juge sur
`llama3.1:8b` dans l'éval, par exemple, un seul jeu de poids pour les
deux). Ce qui scale avec `OLLAMA_NUM_PARALLEL`, c'est le **KV-cache par
requête en cours** (le contexte de génération), pas les poids — confirmé
par l'API/FAQ Ollama : *"required RAM scales by OLLAMA_NUM_PARALLEL ×
OLLAMA_CONTEXT_LENGTH"*, formule indépendante de la taille du modèle.

```
VRAM utilisée ≈ poids_du_modèle (une fois par modèle distinct chargé)
              + Σ (slots_parallèles × contexte_par_slot × coût_kv_cache_par_token)
              + overhead fixe
```

**Implication par taille de modèle** (ordre de grandeur, L4 24 Go) :

| Taille modèle (Q4) | Poids ≈ | VRAM restante pour le KV-cache parallèle |
|---|---|---|
| ~0,5B (`qwen2.5:0.5b`) | ~0,4 Go | ~23 Go — parallélisme très large possible |
| ~7-8B (`llama3.1:8b`, cas courant ici) | ~4,6-5 Go | ~19 Go — large marge pour 4 slots, probablement bien plus |
| ~13-14B | ~8-9 Go | ~15 Go — encore correct pour quelques slots |
| ~30B+ | plusieurs dizaines de Go | peu voire pas de marge sur un seul L4 — RTX PRO 6000 (96 Go) ou parallélisme réduit à 1-2 |

Vérifié en conditions réelles : les logs de démarrage d'Ollama sur le
service (`make cloudrun_llm_logs`) montrent `"vram-based default
context" total_vram="22.0 GiB" default_num_ctx=4096` — Ollama
**auto-ajuste** le contexte par slot selon la VRAM disponible plutôt que
de planter si la configuration demandée est trop juste, garde-fou intégré
plutôt qu'un calcul à faire soi-même au gramme près.

## Pistes de parallélisation non explorées

- Pas de test de charge mesuré (pousser `OLLAMA_NUM_PARALLEL` jusqu'à la
  casse n'a pas été fait) — les ordres de grandeur ci-dessus viennent de
  la doc Ollama + ce qu'on observe dans les logs, pas d'une mesure directe
  de contention.
- `OLLAMA_MAX_LOADED_MODELS` et `OLLAMA_NUM_PARALLEL` ne sont réévalués
  qu'au déclencheur décrit plus haut (modèle évalué trop gros) — pas de
  suivi automatique de la pression VRAM aujourd'hui.
- Bake le modèle dans l'image (`Dockerfile.llm`) ou volume persistant
  (GCS FUSE) pour `/root/.ollama`, pour survivre à un scale-to-zero sans
  re-pull — non implémenté, cf. [`cloudrun.md`](cloudrun.md#service-ollama-berlue-llm).
