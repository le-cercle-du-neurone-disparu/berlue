# Plan — alléger les images Docker et les démarrages à froid

> **Statut : plan, rien d'implémenté.** Mesures faites le 01/09 sur
> `berlue-api:prod` (image réellement poussée, projet
> `gen-lang-client-0242212765`). Chantier distinct de la PR « cycle de vie
> GCP » (`feat-reorganize-gcp-setup-deploy-run-down-destroy`).

Les trois images du projet pèsent ~10 Go chacune. Ce n'est pas une fatalité :
**la moitié est du runtime GPU embarqué dans des images qui tournent sur des
Cloud Run sans GPU.**

## 1. Mesure

Couches de `berlue-api:prod` :

| Couche | Taille |
|---|---|
| `RUN pip install --no-cache-dir -r requirements.txt` | **6,45 Go** |
| base `python:3.14-slim` | 87 Mo |
| divers (apt, pip upgrade) | ~63 Mo |

Contenu de `site-packages` dans cette couche :

| Paquet | Taille | Utile sur Cloud Run CPU ? |
|---|---|---|
| `nvidia/` | **2,7 Go** | ❌ runtime CUDA |
| `torch/` | 1,2 Go | ✅ mais la variante CPU suffit |
| `triton/` | **691 Mo** | ❌ compilateur GPU |
| `pyarrow/` | 156 Mo | ✅ (via mlflow/pandas) |
| `spacy/` | 127 Mo | ✅ (via selfcheckgpt) |
| `transformers/` | 120 Mo | ✅ |
| `scipy/` | 110 Mo | ✅ |
| `sympy/` | 77 Mo | ✅ (dépendance torch) |

**~3,4 Go de CUDA + Triton ne seront jamais exécutés** : `berlue-api-<env>`
et `berlue-eval` tournent sur des Cloud Run CPU. Seul `berlue-llm` a un GPU,
et il ne contient pas ce code (image bâtie sur `nvidia/cuda` + Ollama, cf.
`Dockerfile.llm`).

**Origine** : `torch` n'est pas dans `requirements.txt` — il arrive en
dépendance transitive de `sentence-transformers` et `selfcheckgpt`, et pip
installe par défaut la roue CUDA depuis PyPI, qui tire tout le runtime NVIDIA.

## 2. Correctif — roue CPU de torch

Dans `Dockerfile` et `Dockerfile.eval-service`, avant l'installation des
dépendances :

```dockerfile
# torch arrive en dépendance transitive (sentence-transformers, selfcheckgpt)
# et pip prend par défaut la roue CUDA : ~3,4 Go de runtime NVIDIA + Triton
# jamais exécutés, ces images tournant sur des Cloud Run sans GPU. On fixe la
# roue CPU d'abord pour que pip la trouve déjà satisfaite ensuite.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch
RUN pip install --no-cache-dir -r requirements.txt
```

Gain attendu : **~10 Go → ~5 Go**. Bénéfices en cascade :

- builds et pushs plus courts (l'export des couches prenait 131 s) ;
- démarrages à froid Cloud Run plus rapides (moins d'image à tirer) ;
- la marge disque locale cesse d'être un sujet — trois images à 10 Go avaient
  saturé le poste à 93 % pendant `gcp_deploy`.

`Dockerfile.llm` n'est pas concerné (base CUDA, c'est son rôle).

### À vérifier avant de conclure

1. `selfcheckgpt` et `sentence-transformers` fonctionnent sur la roue CPU —
   attendu, mais à confirmer par `make test_functional` et un `/predict` réel.
2. La taille effective après build (`docker images`), pas seulement estimée.
3. Que `pip install -r requirements.txt` ne réinstalle pas une roue CUDA
   par-dessus (vérifier `pip list | grep -i nvidia` dans l'image finale, qui
   doit être vide).

## 3. Poids de modèles — bucket plutôt que téléchargement au démarrage

Chantier distinct, à ne pas mélanger avec le précédent : il ne réduit pas
l'image, il supprime un téléchargement répété.

Aujourd'hui, `all-mpnet-base-v2` (~420 Mo) et le NLI de SelfCheckGPT
(`potsawee/deberta-v3-large-mnli`, ~1,7 Go) **ne sont pas dans l'image** :
ils sont tirés depuis HuggingFace au démarrage du conteneur. C'est ce que
`gcp_up` absorbe explicitement (« sentence-transformers chargé, plus de
téléchargement HuggingFace au prochain `/predict` »).

Conséquence : chaque démarrage à froid repaie ce téléchargement. Ça devient
plus visible maintenant que `gcp_down` supprime `berlue-llm` et qu'une
nouvelle révision repart toujours de zéro.

**Piste** : monter un bucket GCS en volume, comme l'index FAISS le fait déjà
(`RAG_BUCKET_NAME`, `--add-volume type=cloud-storage`, cf.
`make/cloudrun.mk#cloudrun_deploy`) — le motif existe et se réutilise tel
quel. Pointer `HF_HOME` / `SENTENCE_TRANSFORMERS_HOME` dessus.

À trancher avant d'implémenter :

- **Un bucket dédié ou le bucket RAG ?** Un volume GCS FUSE monte *tout* le
  contenu d'un bucket — c'est précisément pourquoi `RAG_BUCKET_NAME` est
  dédié (cf. `make/config.mk`). Même raisonnement ici : plutôt un second
  bucket que mélanger poids et index.
- **Gain réel non mesuré.** GCS FUSE n'est pas rapide en lecture de gros
  fichiers ; charger 2 Go depuis un volume monté peut ne pas battre le
  téléchargement HuggingFace. **À mesurer avant de s'engager**, sur un
  démarrage à froid chronométré dans les deux configurations.
- **Alternative plus simple** : embarquer les poids dans l'image (couche
  stable, mise en cache par Cloud Run). Coûte de la taille d'image — ce que
  la section 2 cherche justement à réduire — mais supprime toute latence
  réseau au boot. À comparer honnêtement aux deux autres options.

## 4. Ordre suggéré

1. **Roue CPU de torch** — gain certain, diff minuscule, risque faible. À
   faire en premier et à livrer seul.
2. **Mesurer** un démarrage à froid après (1) : le téléchargement des poids
   devient peut-être le poste dominant, ou pas. Cette mesure décide si (3)
   vaut le coup.
3. **Poids de modèles** — seulement si (2) le justifie, et en comparant
   bucket monté / image / statu quo sur des temps mesurés.

Ne pas commencer par (3) : c'est le plus de travail, le gain le moins sûr, et
(1) change les termes du problème.
