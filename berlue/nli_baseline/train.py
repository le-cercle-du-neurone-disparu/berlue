"""Entraîne un classifieur NLI léger (TF-IDF + régression logistique) sur une
partie de HaluEval/TruthfulQA, utilisé comme baseline de comparaison par
`berlue.evaluation` — le reste sert de jeu de test (cf. `berlue.evaluation.data`).

Params utilisés (`berlue.params`) : `NLI_BASELINE_PATH`."""

from berlue.params import NLI_BASELINE_PATH


def train_baseline(out_path: str = NLI_BASELINE_PATH, test_size: float = 0.2) -> None:
    """Entraîne un TfidfVectorizer + LogisticRegression sur le texte
    question+réponse d'une partie de HaluEval/TruthfulQA et sauvegarde le modèle
    avec joblib vers `out_path` (défaut : `params.NLI_BASELINE_PATH`).

    TODO(nli_baseline) :
    1. examples = evaluation.data.load_labeled_examples()
    2. train_examples, _test_examples = evaluation.data.split_train_test(examples, test_size)
       (le jeu de test est réutilisé par evaluation.run_eval, ne pas l'entraîner dessus)
    3. Vectoriser question+réponse (TfidfVectorizer), entraîner LogisticRegression
       sur `ground_truth_label`.
    4. joblib.dump vers `out_path`.
    """
    # TODO(nli_baseline)
    raise NotImplementedError


if __name__ == "__main__":
    train_baseline()
