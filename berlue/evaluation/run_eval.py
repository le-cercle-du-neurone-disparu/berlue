"""Évaluation offline du pipeline Berlue complet vs baseline NLI sur des exemples
labellisés (HaluEval/TruthfulQA) — produit les chiffres comparatifs utilisés pour
la présentation finale.

Lancer avec : python -m berlue.evaluation.run_eval
Pour l'instant, seule la baseline NLI est évaluée par défaut (le pipeline Berlue
complet n'est pas encore implémenté) — cf. `evaluate_baseline`.

Params utilisés indirectement (`berlue.params`, via `evaluation.data` et
`nli_baseline.predict`) : `EVAL_DATASETS`, `HALUEVAL_DATA_PATH`,
`TRUTHFULQA_DATA_PATH`, `NLI_BASELINE_PATH`.
"""

from berlue.api.schemas import ConfusionMatrix, Metrics
from berlue.nli_baseline.predict import NliBaseline


def evaluate_baseline(baseline: NliBaseline | None = None) -> ConfusionMatrix:
    """Évalue la baseline NLI seule sur le jeu de test (HaluEval + TruthfulQA,
    partie non utilisée par `nli_baseline.train.train_baseline`) et retourne sa
    matrice de confusion.

    TODO(evaluation) :
    1. _, test_examples = evaluation.data.split_train_test(evaluation.data.load_labeled_examples())
    2. Pour chaque exemple : baseline.predict(question, answer) -> Verdict.
    3. evaluation.metrics.build_confusion_matrix(ground_truth, predictions).
    """
    baseline = baseline or NliBaseline()
    # TODO(evaluation)
    # return ConfusionMatrix(
    #     ground_truth_true=ConfusionRow(predicted_true=50, predicted_undecided=15, predicted_false=10),
    #     ground_truth_false=ConfusionRow(predicted_true=8, predicted_undecided=7, predicted_false=10),
    # )
    raise NotImplementedError


def run_evaluation(pipeline, baseline: NliBaseline | None = None) -> Metrics:
    """Compare le pipeline Berlue complet (même contrat que `predict()` sur
    `app.state.model`, cf. `berlue.mocks.mock_pipeline.MockBerluePipeline`) et la
    baseline NLI aux labels vérité-terrain du même jeu de test qu'`evaluate_baseline`,
    et retourne des `Metrics` comparables à celles de `/evaluate`.

    TODO(evaluation) :
    1. evaluate_baseline(baseline) -> matrice baseline.
    2. Même jeu de test, mais vérifié avec `pipeline.predict(question, llm_config)`
       -> matrice berlue (evaluation.metrics.build_confusion_matrix).
    3. Assembler les deux en `Metrics`.
    """
    baseline = baseline or NliBaseline()
    # TODO(evaluation)
    # return Metrics(
    #     baseline=ConfusionMatrix(
    #         ground_truth_true=ConfusionRow(predicted_true=50, predicted_undecided=15, predicted_false=10),
    #         ground_truth_false=ConfusionRow(predicted_true=8, predicted_undecided=7, predicted_false=10),
    #     ),
    #     berlue=ConfusionMatrix(
    #         ground_truth_true=ConfusionRow(predicted_true=62, predicted_undecided=8, predicted_false=5),
    #         ground_truth_false=ConfusionRow(predicted_true=4, predicted_undecided=6, predicted_false=15),
    #     ),
    # )
    raise NotImplementedError


if __name__ == "__main__":
    # Par défaut on n'évalue que la baseline NLI : le pipeline complet (RAG +
    # SelfCheckGPT) n'existe pas encore. Utiliser run_evaluation(pipeline=...) une
    # fois disponible pour comparer les deux.
    evaluate_baseline()
