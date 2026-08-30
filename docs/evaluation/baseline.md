# Baseline NLI en local

Classifieur léger (TF-IDF + régression logistique) servant de point de
comparaison au pipeline Berlue complet (RAG inversé + SelfCheckGPT) dans
l'évaluation offline — voir `berlue/nli_baseline/` et `berlue/evaluation/`.
Pour les datasets eux-mêmes (format, labels), voir
[`halueval.md`](../datasets/halueval.md) et [`truthfulqa.md`](../datasets/truthfulqa.md).

## Prérequis

- Environnement local installé, voir [`local-setup.md`](../setup/local-setup.md).
- Accès réseau au premier appel seulement : `evaluation/data.py::load_labeled_examples`
  télécharge HaluEval et TruthfulQA vers `data/halueval/raw/qa_data.json` et
  `data/truthfulqa/raw/truthfulqa.csv`, et saute le téléchargement s'ils y
  sont déjà — même mécanisme que `make download_eval_data`.

## Entraîner

```bash
make train_baseline
```

Charge HaluEval + TruthfulQA (`params.EVAL_DATASETS`), sépare train/test sans
fuite de données (split par question unique, pas par ligne — une même
question ne se retrouve jamais à la fois des deux côtés), entraîne le
pipeline scikit-learn, et le sauvegarde dans `models/nli_tfidf_logreg.joblib`
(`params.NLI_BASELINE_PATH`).

Le `.joblib` n'est pas versionné (cf. `.gitignore`) — il faut relancer cette
commande après un clone frais avant de pouvoir prédire ou évaluer.

Temps estimé : quelques secondes une fois les datasets téléchargés (~20k
exemples pour HaluEval seul).

## Évaluer

```bash
make evaluate_baseline
```

Réévalue la baseline sur le jeu de test (la partie non utilisée par
`train_baseline`) et affiche la matrice de confusion 2x3 (vérité terrain
vraie/fausse × prédiction vraie/indécise/fausse).

## Tester un exemple isolé

```bash
python -m berlue.nli_baseline.predict
```

Charge le modèle entraîné et prédit sur un exemple fixe codé dans le fichier
— pratique pour un test manuel rapide, nécessite d'avoir lancé
`make train_baseline` avant.

## Lancer les tests liés

```bash
pytest tests/test_evaluation_data.py tests/test_evaluation_metrics.py -v
```

Tests unitaires purs (pas de réseau, pas de modèle entraîné requis).
`tests/temp_test_nli_baseline.py` (préfixe `temp_` — non collecté par
pytest, donc pas lancé par défaut) couvre `NliBaseline.predict`, marqué
`@pytest.mark.functional`, nécessite d'avoir lancé `make train_baseline`
avant (charge le `.joblib` local, pas de mock).

## Limiter à un seul dataset

Pour itérer plus vite pendant le développement, sans attendre le
téléchargement des deux jeux de données :

```bash
BERLUE_EVAL_DATASETS=halueval make train_baseline
```

(`halueval`, `truthfulqa`, ou les deux séparés par une virgule — défaut :
les deux, cf. `params.EVAL_DATASETS`.)
