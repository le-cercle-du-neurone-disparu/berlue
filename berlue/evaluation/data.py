"""Chargement des exemples labellisés (HaluEval et/ou TruthfulQA, cf.
`params.EVAL_DATASETS`) utilisés à la fois pour entraîner le classifieur NLI
baseline (`berlue.nli_baseline.train`) et pour évaluer le pipeline Berlue complet
(`berlue.evaluation.run_eval`) — même split train/test pour les deux, pour rester
comparables.

Params utilisés (`berlue.params`) : `EVAL_DATASETS`, `HALUEVAL_URL`,
`HALUEVAL_DATA_PATH`, `TRUTHFULQA_URL`, `TRUTHFULQA_DATA_PATH`, `TRAIN_RATIO`.
"""

import logging
import os
import random

import pandas as pd
import requests
from sklearn.model_selection import train_test_split

from berlue.params import (
    EVAL_DATASETS,
    HALUEVAL_DATA_PATH,
    HALUEVAL_URL,
    TRAIN_RATIO,
    TRUTHFULQA_DATA_PATH,
    TRUTHFULQA_URL,
)

logger = logging.getLogger(__name__)

KNOWN_DATASETS = ("halueval", "truthfulqa")


def download_dataset(url: str, local_path: str) -> str:
    """Télécharge `url` vers `local_path` s'il n'existe pas déjà localement, et
    retourne `local_path` dans tous les cas — cache commun entre le chargement
    (`load_labeled_examples`) et les cibles `make download_*`.
    """
    if os.path.exists(local_path):
        logger.info("✅ %s déjà présent, téléchargement sauté.", local_path)
        return local_path

    logger.info("⬇️  Téléchargement de %s -> %s...", url, local_path)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    response = requests.get(url)
    response.raise_for_status()
    with open(local_path, "wb") as f:
        f.write(response.content)

    logger.info("✅ Téléchargement terminé : %s", local_path)
    return local_path


def explode_answers(rows: list[dict], question_key: str, answers_key: str, ground_truth_label: bool) -> list[dict]:
    """Éclate un champ de réponses séparées par ';' en une ligne par variante
    (une même question peut donc apparaître plusieurs fois, une fois par variante)."""
    records = []
    for row in rows:
        question = row[question_key]
        for answer in str(row[answers_key]).split(";"):
            answer = answer.strip()
            if answer:
                records.append({"question": question, "answer": answer, "ground_truth_label": ground_truth_label})
    return records


def load_labeled_examples(
    datasets: list[str] = EVAL_DATASETS,
    halueval_url: str = HALUEVAL_URL,
    halueval_path: str = HALUEVAL_DATA_PATH,
    truthfulqa_url: str = TRUTHFULQA_URL,
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
        halueval_path = download_dataset(halueval_url, halueval_path)
        logger.info("📥 Chargement de HaluEval depuis : %s", halueval_path)
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
        truthfulqa_path = download_dataset(truthfulqa_url, truthfulqa_path)
        logger.info("📥 Chargement de TruthfulQA depuis : %s", truthfulqa_path)
        rows = pd.read_csv(truthfulqa_path).to_dict(orient="records")

        # Une ligne par variante de réponse (`Correct Answers`/`Incorrect Answers`
        # sont des listes séparées par ';', de taille variable et généralement
        # différente d'une colonne à l'autre) — préserve le déséquilibre vrai/faux
        # du dataset d'origine, au lieu de ne garder qu'une seule réponse de
        # chaque côté par question.
        tqa_examples = explode_answers(rows, "Question", "Correct Answers", ground_truth_label=True)
        tqa_examples += explode_answers(rows, "Question", "Incorrect Answers", ground_truth_label=False)

        for ex in tqa_examples:
            ex["source"] = "truthfulqa"

        # Ajout à la liste globale
        all_examples.extend(tqa_examples)

    logger.info("✅ Chargement terminé : %d exemples normalisés au total.", len(all_examples))
    return all_examples


def balance_classes(examples: list[dict], seed: int) -> list[dict]:
    """Sous-échantillonne la classe majoritaire (`ground_truth_label`), séparément
    pour chaque `source`, pour obtenir autant d'exemples vrais que faux dans
    CHAQUE dataset d'origine (pas seulement sur le total) — un rééquilibrage
    global toutes sources confondues pourrait sinon piocher dans le mauvais
    dataset et casser l'équilibre naturel d'un dataset qui n'en avait pas besoin.
    """
    rng = random.Random(seed)
    balanced = []

    for source in sorted(set(ex["source"] for ex in examples)):
        source_examples = [ex for ex in examples if ex["source"] == source]
        true_examples = [ex for ex in source_examples if ex["ground_truth_label"] is True]
        false_examples = [ex for ex in source_examples if ex["ground_truth_label"] is False]

        n = min(len(true_examples), len(false_examples))
        balanced += rng.sample(true_examples, n) + rng.sample(false_examples, n)

    rng.shuffle(balanced)
    return balanced


def split_train_test(
    examples: list[dict], train_ratio: float = TRAIN_RATIO, seed: int = 0
) -> tuple[list[dict], list[dict]]:
    """Sépare `examples` en (train, test) pour l'entraînement et l'évaluation.

    Split par question unique (pas par ligne) pour éviter le data leakage : une
    même question ne se retrouve jamais à la fois dans le train et dans le test.
    Le train est ensuite rééquilibré à autant d'exemples vrais que faux, dataset
    par dataset (`balance_classes`) ; le test garde la proportion vrai/faux
    telle qu'elle ressort du split par question, sans rééquilibrage.
    """

    # Ordre déterministe avant mélange : nécessaire pour un split reproductible
    # d'un run à l'autre (le train et le test recalculés séparément, ex. entre
    # l'entraînement et l'évaluation, doivent retomber sur le même split).
    unique_questions = sorted(set(ex["question"] for ex in examples))

    # Split sur les questions uniques (et non pas sur les lignes)
    train_questions, _ = train_test_split(unique_questions, train_size=train_ratio, random_state=seed)

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

    train_examples = balance_classes(train_examples, seed)

    logger.info(
        "🔀 Split sans leakage (par question) : %d (train, équilibré 50/50) / %d (test, proportion d'origine).",
        len(train_examples),
        len(test_examples),
    )
    return train_examples, test_examples
