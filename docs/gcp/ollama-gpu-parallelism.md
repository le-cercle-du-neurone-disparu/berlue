# Ollama — parallélisme GPU et usage mémoire

Comment Ollama répartit la VRAM entre poids du modèle, cache KV et calcul
quand plusieurs requêtes tournent en parallèle (`OLLAMA_NUM_PARALLEL`) —
mécanique générale, applicable à n'importe quel déploiement Ollama (poste
de dev local comme `berlue-llm` sur GCP). Choix du GPU/dimensionnement
spécifique à `berlue-llm` : [`infra-gpu.md`](infra-gpu.md).

## Trois postes de VRAM, un seul qui grossit avec le parallélisme

Au chargement d'un modèle, Ollama (via llama.cpp) réserve :

```
VRAM totale = poids_modèle (FIXE, dépend de la quantization du modèle)
            + NUM_PARALLEL × KV-cache_par_slot (LINÉAIRE)
            + compute (~fixe, buffers de calcul batch)
            + marge de sécurité (LLAMA_ARG_FIT_TARGET, 1024 Mio par défaut)
```

Vérifié en conditions réelles (`llama3.1:8b`, RTX 5070 Ti Laptop 12 Go,
`OLLAMA_CONTEXT_LENGTH=4096`) — breakdown exact loggué par llama.cpp au
chargement (`common_memory_breakdown_print`) :

```
CUDA0 : 8611 Mio = model 4403 + context 4096 + compute 112   (NUM_PARALLEL=8)
CUDA0 : 10148 Mio = model 4403 + context 5632 + compute 113  (NUM_PARALLEL=11)
```

`model`/`compute` restent constants d'un run à l'autre ; seul `context`
bouge, proportionnellement à `NUM_PARALLEL` — confirmé linéaire, `+512 Mio`
par `+1 NUM_PARALLEL` sur cette configuration précise.

## D'où vient le coût linéaire par slot

Chaque slot parallèle a besoin de son propre cache KV (Key/Value) — un
par séquence en cours de génération, indépendant des autres :

```
KV-cache par slot = 2 (K et V) × n_layers × n_kv_heads × head_dim × octets_par_élément × context_length
```

Les 4 premiers facteurs sont des **paramètres d'architecture du modèle**,
gravés dans son fichier GGUF — pas des réglages runtime. Pour
`llama3.1:8b`, lus directement dans les métadonnées au chargement
(`llama_model_loader`, pas une supposition) :

| Métadonnée GGUF | Valeur | Rôle |
|---|---|---|
| `llama.block_count` | 32 | `n_layers` |
| `llama.attention.head_count_kv` | 8 | `n_kv_heads` (GQA — 8 têtes KV pour 32 têtes de requête, `head_count`) |
| `llama.embedding_length` | 4096 | `hidden_size` → `head_dim = 4096/32 = 128` |

Avec `OLLAMA_KV_CACHE_TYPE` par défaut (f16, 2 octets/élément) et
`context_length=4096` :

```
2 × 32 × 8 × 128 × 2 × 4096 = 536 870 912 octets = 512 Mio
```

Exactement la pente mesurée. GQA (8 têtes KV au lieu de 32) est ce qui
rend ce coût relativement bas — un modèle en attention classique (MHA,
`head_count_kv = head_count`) coûterait 4× plus cher par slot sur ce
modèle précis.

## Modèles mesurés — référence

Poids et coût KV-cache par slot (`common_memory_breakdown_print`,
`OLLAMA_CONTEXT_LENGTH=4096`, cache f16) pour les modèles disponibles
localement, avec le plafond `N_max` dérivé de la formule ci-dessus
(marge de sécurité 1024 Mio) sur deux GPU :

| Modèle (Q4) | Poids | KV-cache/slot | Compute | `N_max` (12 Go) | `N_max` (L4, 24 Go) |
|---|---|---|---|---|---|
| `qwen2.5:0.5b` | 373 Mio | 48 Mio | 37 Mio | 210 | 439 |
| `llama3.2:1b` | 1252 Mio | 128 Mio | 64 Mio | 71 | 157 |
| `qwen2.5:3b` | 1834 Mio | 144 Mio | 80 Mio | 59 | 136 |
| `llama3.2:3b` | 1918 Mio | 448 Mio | 70 Mio | 19 | 43 |
| `phi3:3.8b` | 2021 Mio | 1536 Mio | 64 Mio | 5 | 12 |
| `mistral:7b` | 4097 Mio | 512 Mio | 112 Mio | 12 | 33 |
| `qwen2.5:7b` | 4168 Mio | 224 Mio | 136 Mio | 27 | 76 |
| `llama3.1:8b` | 4403 Mio | 512 Mio | 112 Mio | 11 | 33 |
| `deepseek-r1:8b` | 4643 Mio | 576 Mio | 100 Mio | 10 | 29 |
| `qwen3:8b` | 4643 Mio | 576 Mio | 100 Mio | 10 | 29 |
| `gemma2:9b` | 5185 Mio | 1344 Mio | 114 Mio | 3 | 12 |
| `phi3:14b` | 7442 Mio | 800 Mio | 129 Mio | 3 | 17 |
| `qwen2.5:14b` | 8148 Mio | 768 Mio | 115 Mio | 2 | 17 |

`N_max` (12 Go) mesuré/vérifié empiriquement pour `llama3.1:8b` et
`qwen2.5:14b` (section précédente et suivante) ; les autres lignes
appliquent la formule sans re-test individuel de la casse. `N_max`
(24 Go, `berlue-llm`) dérivé de la même façon que dans
[`infra-gpu.md`](infra-gpu.md), non vérifié empiriquement sur ce GPU.

Deux modèles avec un `head_count`/`head_count_kv`/`embedding_length`
identiques (`deepseek-r1:8b` et `qwen3:8b`, même architecture `qwen3` 8B)
donnent le même poids et le même coût par slot — la formule dépend de
l'architecture, pas du nom du modèle. `phi3:3.8b` illustre l'autre bout du
spectre : `head_count_kv = head_count` (attention classique, pas de GQA) —
32 têtes KV au lieu de 8-10 pour les modèles voisins, coût par slot
1536 Mio, le plus élevé de cette liste malgré une taille de poids modeste.
`gemma2:9b` illustre un piège de lecture des métadonnées : son
`head_dim` réel (256, coût mesuré = 1344 Mio) n'est **pas**
`embedding_length ÷ head_count` (3584 ÷ 16 = 224 donnerait 1176 Mio) —
certaines architectures déclarent un `head_dim` explicite indépendant de
ce ratio ; le lire dans les métadonnées GGUF (`ollama show <model>`
expose `model_info`) plutôt que le dériver évite l'erreur.

## Rôle de `OLLAMA_CONTEXT_LENGTH`

C'est le facteur `context_length` de la formule ci-dessus : la taille de
contexte réservée **par slot**, appliquée uniformément à tous les slots
parallèles d'un modèle chargé — la valeur par défaut utilisée au
chargement si la requête n'en précise pas d'autre.

Ce budget est **partagé entre le prompt et la réponse générée**, pas deux
zones séparées — chaque token généré attend sur tous les tokens
précédents (prompt et déjà générés) via le KV-cache, d'où le coût mémoire
dérivé plus haut. Un modèle qui produit du texte de raisonnement avant sa
réponse finale (ex. `deepseek-r1:8b`) consomme ce même budget avec ces
tokens de raisonnement, au même titre que la réponse — pas une zone à
part. Exemple mesuré (section "Comment le batching s'enchaîne dans le
temps") : 14 tokens de prompt + 88 de réponse = 102 tokens au total sur
les 4096 réservés, un seul total, pas deux budgets distincts.

Une requête peut la remplacer via `options.num_ctx` — vérifié aux logs
(`journalctl -u ollama`) : une requête avec un `num_ctx` différent de
celui du runner actuellement chargé déclenche un **rechargement complet
du modèle** (nouveau `runner`, poids relus, `n_slots`/`n_ctx_slot`
recalculés) avec la nouvelle valeur appliquée à **tous les slots**
parallèles de ce modèle, pas seulement à la requête qui l'a demandée — un
`num_ctx` par requête est donc honoré, mais au prix d'un rechargement à
chaque changement de valeur, et son effet est partagé par tout le
parallélisme de ce modèle, pas isolé par requête. Si le nouveau contexte
total (`num_ctx × NUM_PARALLEL`) ne tient plus dans la VRAM disponible,
Ollama réduit automatiquement le nombre de couches déchargées sur GPU
(`load_tensors: offloaded X/N layers to GPU`, X < N) au lieu de refuser
la requête — même garde-fou que pour un `NUM_PARALLEL` trop haut.
Un workload qui alterne des `num_ctx` différents entre requêtes paierait
donc un rechargement à chaque bascule — à réserver à un `num_ctx` stable
sur toute la durée de vie du runner, ou à laisser `OLLAMA_CONTEXT_LENGTH`
fixer une valeur unique pour tous.

Effet direct, linéaire, sur le coût par slot — diviser `OLLAMA_CONTEXT_LENGTH`
par 2 divise le KV-cache par slot par 2, donc double `N_max` à VRAM
constante (et inversement).

**Le baisser** : quand la charge réelle n'a jamais besoin d'un grand
contexte. Les prompts de l'éval Berlue (question + instruction courte)
mesurent 14 à 48 tokens en conditions réelles (cf. section
"Comment le batching s'enchaîne dans le temps" plus haut) — très en
dessous des 4096 réservés par slot ; descendre à 512 ou 1024 libérerait
4 à 8× plus de marge pour `NUM_PARALLEL`, sans rien perdre pour cet usage
précis. Un contexte plus petit que nécessaire tronque silencieusement
l'historique/le prompt une fois la limite atteinte — à ne baisser qu'en
connaissant la longueur réelle des requêtes envoyées.

**Le monter** : quand la charge a réellement besoin d'un contexte plus
long que 4096 (RAG avec de gros extraits injectés dans le prompt,
conversation multi-tour, document entier à résumer) — sinon le modèle
tronque silencieusement ce qui dépasse, avec une dégradation de qualité
plutôt qu'une erreur explicite. Le coût se paie en `N_max`, linéairement
(un contexte 2× plus grand divise le plafond de parallélisme par 2).

`OLLAMA_CONTEXT_LENGTH` plafonne l'usage du contexte natif du modèle
(131072 pour `llama3.1:8b`), il ne le remplace pas — le modèle reste
capable de bien plus, seule la VRAM réservée par slot au runtime est
limitée par ce réglage.

## Fondamental vs choix de politique Ollama

**Universel à tout moteur d'inférence avec KV-cache** (pas spécifique à
Ollama) :
- La croissance linéaire elle-même — réserver de la mémoire par séquence
  en cours est inhérent au calcul d'attention avec cache, quel que soit le
  moteur (vLLM, TGI, TensorRT-LLM...).
- Les 4 paramètres d'architecture (`n_layers`, `n_kv_heads`, `head_dim`,
  precision native du modèle) — fixes pour un modèle donné, aucun moteur
  ne peut les changer sans changer de modèle.

**Choix de politique Ollama/llama.cpp** (un autre moteur ferait
potentiellement autrement) :
- **`LLAMA_ARG_FIT_TARGET`** (1024 Mio par défaut) — marge de sécurité
  conservatrice, pas une contrainte matérielle. Message vu dans les logs
  au premier échec : *"cannot meet free memory target of 1024 MiB"*.
- **Stratégie de dégradation** : si la marge ne passe pas, Ollama bascule
  des couches sur CPU (`offloaded X/N layers to GPU`, X < N) plutôt que de
  refuser la requête ou de réduire `NUM_PARALLEL` automatiquement — un
  choix d'implémentation, pas une nécessité.
- **`OLLAMA_KV_CACHE_TYPE` par défaut = f16** — compromis précision/mémoire
  choisi par Ollama, ajustable (cf. section suivante).
- **`OLLAMA_NUM_PARALLEL` par défaut** (auto : 4 ou 1 selon la mémoire
  détectée) — une heuristique, pas un maximum technique : monté
  explicitement, on peut toujours essayer plus haut, jusqu'à ce que la
  VRAM (ou la marge de sécurité) ne suive plus.

## Trouver le plafond réel pour une configuration donnée

Mesuré en testant chaque valeur de `NUM_PARALLEL` et en lisant
`offloaded X/N layers to GPU` dans les logs (`sudo journalctl -u ollama`,
ou `gcloud logging read`/`make cloudrun_llm_logs` sur GCP) — X = N confirme
100% GPU, X < N signale un dépassement :

```bash
# reconfigurer NUM_PARALLEL (exemple systemd local — sur Cloud Run,
# cf. cloudrun_llm_deploy dans cloudrun.mk)
sudo systemctl edit ollama   # Environment="OLLAMA_NUM_PARALLEL=N"
sudo systemctl daemon-reload && sudo systemctl restart ollama

curl -s -X POST http://localhost:11434/api/generate \
  -d '{"model":"llama3.1:8b","prompt":"hi","stream":false}' > /dev/null
sudo journalctl -u ollama --since "20 seconds ago" | grep "offloaded.*layers to GPU"
```

**Mesuré sur RTX 5070 Ti Laptop (12 Go), `llama3.1:8b`,
`OLLAMA_CONTEXT_LENGTH=4096`** — plafond exact = 11 (12 casse déjà,
32/33 couches) :

| `NUM_PARALLEL` | 100% GPU ? |
|---|---|
| 8, 9, 10, **11** | ✅ |
| 12, 14, 15, 16, 32 | ❌ (couches sur CPU, dégradation massive) |

Formule prédictive, vérifiée a posteriori sur ces mesures :

```
N_max = floor((VRAM_libre − poids_modèle − compute − marge_cible) / KV-cache_par_slot)
      = floor((11537 − 4403 − 112 − 1024) / 512) = 11
```

## Comment le batching s'enchaîne dans le temps, sous le plafond

Question distincte du plafond VRAM : une fois sous `NUM_PARALLEL`, les
requêtes concurrentes démarrent-elles vraiment ensemble, et à quel coût par
requête ? Vérifié en comparant, aux logs `journalctl -u ollama`
(`--log-verbosity 4`, le niveau max qu'Ollama configure — suffisant, `OLLAMA_DEBUG=1`
ne l'augmente pas), une requête seule contre 10 requêtes envoyées au même
instant (`NUM_PARALLEL=10`, aucune file, chaque requête obtient un slot
immédiatement) :

- **Dispatch réellement simultané.** Les 10 tâches (`launch_slot_`, `new
  prompt`) sont acceptées et démarrent leur traitement en ~3 ms d'écart —
  pas de délai artificiel, pas de traitement séquentiel côté serveur.
- **Débit par requête individuelle, en baisse nette.** Solo : 91,9 tok/s
  (88 tokens en 946 ms). À 10 requêtes concurrentes : de 30,7 à 66,7 tok/s
  selon la requête (~40 tok/s en moyenne) — chaque flux individuel est
  2 à 3× plus lent qu'en solo.
- **Débit agrégé du système, en hausse.** 753 tokens générés au total en
  3,65 s de mur = ~206 tok/s, soit ~2,2× le débit solo — un vrai gain de
  throughput système, mais sous-linéaire (10 requêtes ne donnent pas 10×
  le débit solo).

C'est le comportement attendu d'un serveur à *continuous batching* (llama.cpp,
comme vLLM/TGI) : à chaque étape de décodage, **toutes** les séquences
actives avancent ensemble dans un seul passage GPU partagé — d'où le
dispatch simultané, et le ralentissement par requête proportionnel au
nombre de séquences présentes dans le lot à cet instant (le même effet est
visible sur le *prefill* : 908 tok/s solo contre 339 tok/s à 10 requêtes
concurrentes). Implication pour paralléliser `evaluate_model_generated` :
viser le débit agrégé (plus de réponses générées par seconde au total), pas
le débit par requête individuelle qui, lui, se dégrade toujours sous charge.

## Le point de saturation du débit agrégé dépend fortement de la taille du modèle

`N_max` (le plafond VRAM) n'est qu'une borne supérieure — le débit agrégé
peut saturer bien avant, dès que le **compute** GPU (pas la VRAM) devient le
facteur limitant. Ce point de saturation dépend fortement de la taille du
modèle, vérifié en comparant deux modèles à contexte réaliste (512, adapté
à des prompts courts — cf. table "Modèles mesurés" plus haut) :

| Modèle | Débit agrégé | Comportement |
|---|---|---|
| `qwen2.5:0.5b` | plafonne ~1350-1500 tok/s dès 6-7 requêtes concurrentes, **plat** ensuite jusqu'à 64 | saturation compute quasi immédiate |
| `llama3.1:8b` | 529,7 tok/s à 32 requêtes concurrentes, 619,7 tok/s à 64 (+17% pour 2× de slots) | rendement décroissant net, mais pas de plateau atteint |

Un tout petit modèle sature le compute GPU dès quelques requêtes
concurrentes — une seule requête n'utilise déjà pas toute la capacité de
calcul disponible, donc en ajouter davantage cesse vite d'apporter un gain
agrégé (juste plus de latence par requête, cf. section suivante). Un
modèle plus gros utilise déjà une part significative du compute par
requête individuelle, donc le batching reste rentable sur une plage de
concurrence beaucoup plus large avant de saturer à son tour. Implication
pratique : le plafond de concurrence *utile* pour un modèle donné se
mesure empiriquement (débit agrégé par palier de charge), `N_max` ne
donne qu'une borne à ne pas dépasser, pas le point optimal.

## `OLLAMA_NUM_PARALLEL` doit être calé sur la concurrence réelle, pas maximisé

`OLLAMA_NUM_PARALLEL` fixe le nombre de slots **réservés**, pas seulement
utilisés à la demande — un serveur configuré large mais sous-exploité paie
un coût réel, pas juste "pas de bénéfice". Vérifié sur deux GPU
indépendants (RTX 5070 Ti Laptop 12 Go, L4 24 Go) : même charge cliente,
seul `OLLAMA_NUM_PARALLEL` change entre les deux colonnes —

| Charge réelle | Serveur large | Serveur calé sur la charge |
|---|---|---|
| 16 clients (local) | 165,3 tok/s (`NUM_PARALLEL=40`) | 399,9 tok/s (`NUM_PARALLEL=16`) |
| 32 clients (local) | 290,0 tok/s (`NUM_PARALLEL=40`) | 527,9 tok/s (`NUM_PARALLEL=32`) |
| 32 clients (GCP) | 60,5 tok/s (`NUM_PARALLEL=128`) | 261,0 tok/s (`NUM_PARALLEL=32`) |

Jusqu'à 4× le débit à charge cliente identique, juste en réduisant le
nombre de slots configurés côté serveur pour coller au nombre de requêtes
réellement envoyées. Cause probable (non confirmée avec certitude) : le
scheduling/les CUDA graphs de llama.cpp composent avec le nombre de slots
*configurés*, pas seulement les slots *actifs* — un slot inactif n'est pas
gratuit.

**Implication pratique** : dimensionner `OLLAMA_NUM_PARALLEL` (et
`CONCURRENCY` côté éval) sur la charge **prévue pour ce run précis**, pas
sur un maximum "au cas où". Chiffres complets (balayage fin, local et
GCP) : [`execution-benchmark.md`](../evaluation/execution-benchmark.md).

## Comportement au-delà du plafond de parallélisme réel (charge client)

Envoyer plus de requêtes concurrentes que `NUM_PARALLEL` ne casse rien —
les requêtes en surplus **s'empilent dans une file** (`OLLAMA_MAX_QUEUE`,
512 par défaut, 503 seulement au-delà), jamais rejetées avant ce seuil.
Vérifié par un test de charge (threads client montant progressivement de
4 à 30, `NUM_PARALLEL=8`) : latence croît **quasi linéairement** avec le
nombre de threads en surplus (1s à 8 threads, ~5s à 30) — pas de mur, pas
de collapse, juste une file qui s'allonge. Au-delà du plafond de
parallélisme réel, plus de threads client ne fait donc jamais mieux
(débit plafonné par `NUM_PARALLEL`), seulement plus de latence par
requête.

## Leviers pour monter le plafond

Chacun agit sur un poste différent de la formule :

| Levier | Poste affecté | Effet |
|---|---|---|
| `OLLAMA_CONTEXT_LENGTH` plus bas | linéaire (KV-cache/slot) | proportionnel — diviser par 2 double le plafond ; cf. section «Rôle de `OLLAMA_CONTEXT_LENGTH`» plus haut pour quand c'est pertinent |
| `OLLAMA_KV_CACHE_TYPE=q8_0`/`q4_0` (au lieu de f16) | linéaire (octets/élément) | q8_0 divise le coût/slot par 2, q4_0 par 4 — précision du cache réduite, impact qualité non mesuré ici |
| Modèle plus quantizé (ex. `q4_K_M` au lieu de `q8_0`) | fixe (poids) | libère de la marge pour le KV-cache, ne change pas la pente |
| Plus de VRAM (GPU différent) | disponible | proportionnel — L4 24 Go (`berlue-llm`) a ~2× la VRAM libre de cette carte 12 Go, plafond attendu ~2× plus haut, **non mesuré empiriquement**
