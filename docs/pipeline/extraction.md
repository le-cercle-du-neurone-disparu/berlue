# Découpage en affirmations

Découpe la réponse brute du LLM en affirmations atomiques et indépendantes
(`Claim`, une par fait vérifiable) — voir
`berlue/pipeline/hurlu_berlu.py::HurluBerlu._do_llm_extraction`. Chaque
affirmation devient ensuite l'unité vérifiée par SelfCheckGPT et le RAG
inversé ([`selfcheck.md`](selfcheck.md), [`rag.md`](rag.md)).

Un appel LLM (même client que [`llm.md`](llm.md), prompt dédié demandant
une liste à puces, une affirmation par ligne, pronoms résolus) génère le
texte brut ; celui-ci est ensuite parsé ligne par ligne (les lignes qui ne
commencent pas par `- ` sont ignorées).

## Lancer cette étape

```bash
make pipeline_extract QUESTION="Pourquoi la mer est salée ?"
```

Équivalent direct (voir [`hurlu_berlu.md`](hurlu_berlu.md) pour les autres
étapes) :

```bash
python -m berlue.pipeline.hurlu_berlu --until extract --question "Pourquoi la mer est salée ?"
```

## Lancer les tests liés

```bash
pytest tests/test_pipeline.py -v -k extract_claims
```

Tests unitaires purs (`OllamaClient` stubé, cf. `tests/test_pipeline.py`) :
vérifient le parsing de la liste à puces et le cas d'une réponse vide (aucune
affirmation extraite, pas d'appel LLM).
