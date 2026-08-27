# Baseline NLI en local

Classifieur léger (TF-IDF + régression logistique) servant de point de
comparaison au pipeline Berlue complet (RAG inversé + SelfCheckGPT) dans
l'évaluation offline — voir `berlue/nli_baseline/` et `berlue/evaluation/`.

## Prérequis

- Dépendances installées : `pip install -r requirements.txt -r requirements_dev.txt`
- Accès réseau : `evaluation/data.py::load_labeled_examples` télécharge
  HaluEval et TruthfulQA depuis GitHub raw à chaque appel, pas de cache local
  pour l'instant.

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
pytest tests/test_nli_baseline.py tests/test_evaluation_data.py tests/test_evaluation_metrics.py -v
```

`test_nli_baseline.py` est marqué `@pytest.mark.functional` (exclu de la lane
CI rapide) et nécessite d'avoir lancé `make train_baseline` avant — il charge
le `.joblib` local, pas de mock. Les deux autres fichiers sont des tests
unitaires purs (pas de réseau, pas de modèle entraîné requis).

## Limiter à un seul dataset

Pour itérer plus vite pendant le développement, sans attendre le
téléchargement des deux jeux de données :

```bash
BERLUE_EVAL_DATASETS=halueval make train_baseline
```

(`halueval`, `truthfulqa`, ou les deux séparés par une virgule — défaut :
les deux, cf. `params.EVAL_DATASETS`.)
