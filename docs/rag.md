# RAG inversé (FEVER)

Vérifie une affirmation en cherchant les claims FEVER les plus proches
(embeddings + FAISS) et en votant sur leurs labels — voir `berlue/rag/` et
`README.structure.md`.

## Prérequis

- Dépendances installées : `make reinstall_package` (installe `faiss-cpu`,
  `sentence-transformers`, `tqdm` entre autres, via `requirements.txt`)
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

Lance `berlue/rag/test_rag.py` : charge l'index, prend 10 affirmations de
`data/fever/raw/fever.jsonl`, affiche le verdict RAG et la preuve citée pour
chacune, puis un résumé (corrects/testés). Échoue avec un message clair si
l'index n'existe pas encore (`make build_fever_index` d'abord).

## ⚠️ La précision affichée n'est pas un vrai score de qualité

`test_rag.py` teste sur le même fichier que celui indexé par
`build_fever_index` — chaque affirmation testée est donc quasi son propre
plus proche voisin dans l'index, d'où une précision proche de 100% quel que
soit le sous-ensemble. C'est une fuite de données, pas une mesure de
performance réelle : ce script valide la plomberie (l'index se charge, le
scoring tourne, le format de sortie est correct), pas la qualité du RAG. Un
vrai split train/index vs test reste à faire.

## Pas de LLM impliqué

`verify_claim()` n'utilise que `SentenceTransformer` (embeddings) et l'index
FAISS — aucun appel à Ollama. Le `Claim` passé en entrée est soit construit à
la main (comme dans `test_rag.py`), soit produit en amont par
`berlue/llm/` + l'extracteur d'affirmations dans le pipeline complet, pas par
ce module.

## Tests automatisés

`tests/test_rag.py` contient un test de contrat pytest
(`test_verify_claim_returns_rag_verdict`), actuellement marqué
`@pytest.mark.skip` — à reprendre plus tard avec de vrais tests (mocks/fixtures
propres), pas avec le script manuel du dev en l'état.
