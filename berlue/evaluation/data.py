"""Chargement des exemples labellisés (HaluEval et/ou TruthfulQA, cf.
`params.EVAL_DATASETS`) utilisés à la fois pour entraîner le classifieur NLI
baseline (`berlue.nli_baseline.train`) et pour évaluer le pipeline Berlue complet
(`berlue.evaluation.run_eval`) — même split train/test pour les deux, pour rester
comparables.

Params utilisés (`berlue.params`) : `EVAL_DATASETS`, `HALUEVAL_DATA_PATH`,
`TRUTHFULQA_DATA_PATH`.
"""

import pandas as pd
from sklearn.model_selection import train_test_split

from berlue.params import EVAL_DATASETS, HALUEVAL_DATA_PATH, TRUTHFULQA_DATA_PATH

KNOWN_DATASETS = ("halueval", "truthfulqa")


def load_labeled_examples(
    datasets: list[str] = EVAL_DATASETS,
    halueval_path: str = HALUEVAL_DATA_PATH,
    truthfulqa_path: str = TRUTHFULQA_DATA_PATH,
) -> list[dict]:
    """Charge des exemples labellisés depuis les jeux listés dans `datasets`."""

    # Validation des noms de datasets
    for ds in datasets:
        if ds not in KNOWN_DATASETS:
            raise ValueError(f"❌ Dataset inconnu : '{ds}'. Les options valides sont : {KNOWN_DATASETS}")

    all_examples = []

    # ==========================================
    # 1. Traitement de HaluEval
    # ==========================================
    if "halueval" in datasets:
        print(f"📥 Chargement de HaluEval depuis : {halueval_path}")
        df_he = pd.read_json(halueval_path, lines=True)

        # Extraction des exemples CORRECTS
        df_true = df_he[["question", "right_answer"]].copy()
        df_true.rename(columns={"right_answer": "answer"}, inplace=True)
        df_true["ground_truth_label"] = True

        # Extraction des exemples HALLUCINÉS
        df_false = df_he[["question", "hallucinated_answer"]].copy()
        df_false.rename(columns={"hallucinated_answer": "answer"}, inplace=True)
        df_false["ground_truth_label"] = False

        # Concaténation et ajout de la source
        df_he_combined = pd.concat([df_true, df_false], ignore_index=True)
        df_he_combined["source"] = "halueval"

        # Ajout à la liste globale
        all_examples.extend(df_he_combined.to_dict(orient="records"))

    # ==========================================
    # 2. Traitement de TruthfulQA
    # ==========================================
    if "truthfulqa" in datasets:
        print(f"📥 Chargement de TruthfulQA depuis : {truthfulqa_path}")
        df_tqa = pd.read_csv(truthfulqa_path)

        # Extraction des exemples CORRECTS
        df_true_tqa = df_tqa[["Question", "Best Answer"]].copy()
        df_true_tqa.rename(columns={"Question": "question", "Best Answer": "answer"}, inplace=True)
        df_true_tqa["ground_truth_label"] = True

        # Extraction des exemples INCORRECTS
        # Les fausses réponses sont séparées par des ';', on extrait la première pour équilibrer
        df_false_tqa = df_tqa[["Question", "Incorrect Answers"]].copy()
        df_false_tqa["answer"] = df_false_tqa["Incorrect Answers"].astype(str).apply(lambda x: x.split(";")[0].strip())
        df_false_tqa.drop(columns=["Incorrect Answers"], inplace=True)
        df_false_tqa.rename(columns={"Question": "question"}, inplace=True)
        df_false_tqa["ground_truth_label"] = False

        # Concaténation et ajout de la source
        df_tqa_combined = pd.concat([df_true_tqa, df_false_tqa], ignore_index=True)
        df_tqa_combined["source"] = "truthfulqa"

        # Ajout à la liste globale
        all_examples.extend(df_tqa_combined.to_dict(orient="records"))

    print(f"✅ Chargement terminé : {len(all_examples)} exemples normalisés au total.")
    return all_examples


def split_train_test(examples: list[dict], test_size: float = 0.2, seed: int = 0) -> tuple[list[dict], list[dict]]:
    """Sépare `examples` en (train, test) pour l'entraînement et l'évaluation,
    en évitant le data leakage : on sépare par question unique pour qu'une même
    question ne se retrouve pas à la fois dans le train et dans le test.
    """

    # Filtre les questions en double pour ne retorner que des questions différentes
    unique_questions = list(set(ex["question"] for ex in examples))

    # Split sur les questions uniques (et non pas sur les lignes)
    train_questions, test_questions = train_test_split(unique_questions, test_size=test_size, random_state=seed)

    # Conversion de la liste en set pour une meilleure performance (O(1))
    train_q_set = set(train_questions)

    # Reconstruction des datasets finaux

    train_examples = []
    test_examples = []

    for ex in examples:
        if ex["question"] in train_q_set:
            train_examples.append(ex)
        else:
            test_examples.append(ex)

    print(f"🔀 Split sans leakage (par question) : {len(train_examples)} (train) / {len(test_examples)} (test).")
    return train_examples, test_examples
