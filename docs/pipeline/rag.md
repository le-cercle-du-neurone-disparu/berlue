# RAG inversé (FEVER)

Vérifie une affirmation en cherchant les claims FEVER les plus proches
(embeddings + FAISS) et en votant sur leurs labels — voir `berlue/rag/` et
`docs/dev/structure.md`. Pour le dataset FEVER lui-même (format, labels,
d'où il vient), voir `docs/datasets/fever.md`.

## Prérequis

Dépendances installées (`faiss-cpu`, `sentence-transformers`, `tqdm` entre
autres, via `requirements.txt`) :

```bash
make reinstall_package
```

- Accès réseau :
  - `download_fever_data_*` télécharge depuis `fever.ai`
  - `build_fever_index` télécharge le modèle d'embedding `all-mpnet-base-v2`
    depuis HuggingFace au premier lancement (~420 Mo, mis en cache ensuite)

## Télécharger les données FEVER

```bash
make download_fever_data_small   # extrait rapide (2000 lignes par défaut)
make download_fever_data_full    # corpus complet (~145k lignes)
```

Les deux écrivent dans `data/fever/raw/` (`fever_small.jsonl` /
`fever_full.jsonl`, aucun des deux n'écrase l'autre) et font pointer le
symlink `data/fever/raw/fever.jsonl` sur le dernier téléchargé — le reste des
commandes ci-dessous utilise toujours ce chemin, sans rien à changer.

`FEVER_SAMPLE_LINES` est surchargeable :

```bash
make download_fever_data_small FEVER_SAMPLE_LINES=20000
```

## Construire l'index

```bash
make build_fever_index
```

Charge `data/fever/raw/fever.jsonl`, ne garde que les exemples
`SUPPORTS`/`REFUTES`, embed chaque claim et écrit l'index FAISS + les
métadonnées dans `data/fever/faiss/` (`params.RAG_VECTOR_DB_PATH`). Échoue
avec un message clair si `fever.jsonl` n'existe pas encore.

Temps estimé : quelques secondes sur l'extrait rapide (2000 lignes), plusieurs
minutes sur le corpus complet.

## Tester

```bash
make test_fever_rag
```

Lance `tests/test_rag.py` (tests pytest marqués `@pytest.mark.functional`) :
vérifie que `verify_claim()` renvoie un `RagVerdict` valide pour une
affirmation proche du corpus, et gère sans planter le cas où aucune preuve
récupérée n'est assez proche (`NOT_ENOUGH_INFO`, `evidence=None`). Échoue avec
un message clair si l'index n'existe pas encore (`make build_fever_index`
d'abord).

## Pas de LLM impliqué

`verify_claim()` n'utilise que `SentenceTransformer` (embeddings) et l'index
FAISS — aucun appel à Ollama. Le `Claim` passé en entrée est soit construit à
la main (comme dans `tests/test_rag.py`), soit produit en amont par
`berlue/llm/` + l'extracteur d'affirmations dans le pipeline complet, pas par
ce module.

## Tests automatisés

`tests/test_rag.py` contient les tests de contrat pytest de `verify_claim()`,
marqués `@pytest.mark.functional` (besoin d'un index FAISS + embeddings réels
via `RagRetriever`) — commande plus haut, section « Tester ».
