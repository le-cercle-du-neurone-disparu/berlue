"""Chargement des exemples labellisés (HaluEval et/ou TruthfulQA, cf.
`params.EVAL_DATASETS`) utilisés à la fois pour entraîner le classifieur NLI
baseline (`berlue.nli_baseline.train`) et pour évaluer le pipeline Berlue complet
(`berlue.evaluation.run_eval`) — même split train/test pour les deux, pour rester
comparables.

Params utilisés (`berlue.params`) : `EVAL_DATASETS`, `HALUEVAL_DATA_PATH`,
`TRUTHFULQA_DATA_PATH`."""

from berlue.params import EVAL_DATASETS, HALUEVAL_DATA_PATH, TRUTHFULQA_DATA_PATH

KNOWN_DATASETS = ("halueval", "truthfulqa")


def load_labeled_examples(
    datasets: list[str] = EVAL_DATASETS,
    halueval_path: str = HALUEVAL_DATA_PATH,
    truthfulqa_path: str = TRUTHFULQA_DATA_PATH,
) -> list[dict]:
    """Charge des exemples labellisés depuis les jeux listés dans `datasets` (parmi
    `KNOWN_DATASETS`, cf. `params.EVAL_DATASETS` pour activer un seul dataset à la
    fois via `.env`), en lisant les fichiers depuis `halueval_path`/`truthfulqa_path`
    (défauts : `params.HALUEVAL_DATA_PATH`/`params.TRUTHFULQA_DATA_PATH`), normalisés
    vers un même format
    `{question, answer, ground_truth_label, source}` (`ground_truth_label` : `True`
    = réponse correcte, `False` = réponse hallucinée/incorrecte — les deux datasets
    sont binaires, pas de `Verdict.NOT_ENOUGH_INFO`).

    TODO(evaluation) :
    - "halueval" (subset QA) : `pd.read_json(url, lines=True)` avec `url =
      "https://raw.githubusercontent.com/RUCAIBox/HaluEval/main/data/qa_data.json"`,
      colonnes `knowledge`/`question`/`right_answer`/`hallucinated_answer` —
      "melter" `right_answer`/`hallucinated_answer` en une colonne `answer` +
      `hallucinated` (bool). Cf. `docs/data-HaluEval.md`/`.ipynb` sur
      `origin/docs-HaluEval`.
    - "truthfulqa" : CSV
      `https://raw.githubusercontent.com/sylinrl/TruthfulQA/main/TruthfulQA.csv`
      (colonnes `Question`, `Best Answer`, `Correct Answers`, `Incorrect
      Answers`) — schéma différent de HaluEval, à harmoniser vers le même format.
    - Ne charger/concaténer que les datasets présents dans `datasets` ; lever une
      erreur claire si `datasets` contient une valeur hors `KNOWN_DATASETS`.
    """
    # TODO(evaluation)
    # return [
    #     {
    #         "question": "Quelle est la capitale de la France ?",
    #         "answer": "Paris est la capitale de la France.",
    #         "ground_truth_label": True,
    #         "source": "halueval",
    #     },
    #     {
    #         "question": "Est-ce que manger des carottes améliore la vue dans le noir ?",
    #         "answer": "Oui, manger des carottes permet de voir dans le noir.",
    #         "ground_truth_label": False,
    #         "source": "truthfulqa",
    #     },
    # ]
    raise NotImplementedError


def split_train_test(examples: list[dict], test_size: float = 0.2, seed: int = 0) -> tuple[list[dict], list[dict]]:
    """Sépare `examples` en (train, test) : train pour
    `nli_baseline.train.train_baseline`, test pour
    `evaluation.run_eval.evaluate_baseline` (et, plus tard, pour évaluer le
    pipeline complet sur le même jeu de test, pour rester comparables)."""
    # TODO(evaluation)
    # train_examples, test_examples = examples[:-20], examples[-20:]  # proportions réelles via test_size
    # return train_examples, test_examples
    raise NotImplementedError
