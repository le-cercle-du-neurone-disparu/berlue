# Les poids des modèles en bucket

Les deux modèles HuggingFace du pipeline ne sont ni dans l'image, ni téléchargés à
l'exécution : ils vivent dans un bucket GCS, monté en volume et désigné aux
bibliothèques par `HF_HOME`.

## Le problème

Le pipeline charge deux modèles **paresseusement**, au premier usage réel :

| modèle | chargé par | poids |
|---|---|---|
| le SentenceTransformer d'embedding | `RagRetriever.__init__` | ~0,44 Go |
| `potsawee/deberta-v3-large-mnli` (SelfCheck) | le singleton de `selfcheck/scorer.py` | ~1,74 Go |

Sans cache, chaque démarrage à froid les retéléchargeait — **~2,2 Go, en plein milieu
d'une requête déjà longue**, et de nouveau après chaque `scale-to-zero`.

## Pourquoi un bucket plutôt que l'image

Les cuire dans l'image marcherait, mais ajouterait 2,2 Go à un artefact déjà lourd
(~6,5 Go de dépendances), rebuildé et repoussé à chaque changement de dépendance —
alors que ces poids ne changent qu'au changement de modèle.

C'est le même raisonnement que pour l'index RAG et le code applicatif : **ce qui est
lourd et rarement modifié n'a pas sa place dans l'image**.

## Comment ça marche

```
gs://<projet>-berlue-models/hub/…      le cache HuggingFace, publié une fois
        ↓ volume GCS FUSE
/mnt/models                            monté en lecture seule dans le conteneur
        ↓ HF_HOME=/mnt/models
transformers / sentence-transformers   trouvent les poids sans réseau
```

Les services partent avec **`HF_HUB_OFFLINE=1`**. C'est délibéré : un cache absent
échoue franchement au lieu de dégénérer en téléchargement silencieux de 2,2 Go à
chaque démarrage à froid. Le déploiement contrôle d'ailleurs la présence du cache
avant de partir (`_models_check`), sur le modèle du contrôle de l'index RAG.

Vérifié : le chargement fonctionne depuis un cache **en lecture seule et sans réseau** —
les bibliothèques n'ont pas besoin d'écrire dans le cache pour lire un modèle déjà présent.

## Les commandes

```bash
make models_push        # publie les poids (~2,2 Go) — seulement si un modèle change
make models_content     # ce que contient le bucket
make gcp_doctor         # vérifie, entre autres, que le cache est en place
```

`models_bucket_create` et `models_bucket_grant_sa` sont appelés par `gcp_setup`,
`models_bucket_delete` par `gcp_destroy`. Rien à faire à la main.

## Ce qui est publié, et ce qui ne l'est pas

Seuls les poids **`safetensors`** partent dans le bucket. Le dépôt du NLI contient
aussi un `pytorch_model.bin` de 1,74 Go — exactement le même modèle, dans un format
que `transformers` n'utilise pas quand safetensors est présent. L'ignorer fait passer
la publication de 3,7 à **2,18 Go**.

Les noms des modèles ne sont recopiés nulle part : celui de l'embedding est lu depuis
`berlue/params.py` par `make`, celui du NLI depuis le paquet `selfcheckgpt` par le
script de publication. Changer de modèle dans le code suffit à changer ce qui est publié.
