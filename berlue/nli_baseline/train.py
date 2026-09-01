"""Entraîne un classifieur NLI léger (TF-IDF + régression logistique) sur une
partie de HaluEval/TruthfulQA, utilisé comme baseline de comparaison par
`berlue.evaluation` — le reste sert de jeu de test (cf. `berlue.evaluation.data`).

Params utilisés (`berlue.params`) : `NLI_BASELINE_PATH`, `TRAIN_RATIO`.
"""

import logging
import os
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from berlue.evaluation.data import load_labeled_examples, split_train_test
from berlue.params import NLI_BASELINE_PATH, TRAIN_RATIO

logger = logging.getLogger(__name__)


def train_baseline(out_path: str = NLI_BASELINE_PATH, train_ratio: float = TRAIN_RATIO) -> None:
    """Entraîne un TfidfVectorizer + LogisticRegression sur le texte
    question+réponse d'une partie de HaluEval/TruthfulQA et sauvegarde le modèle
    avec joblib vers `out_path` (défaut : `params.NLI_BASELINE_PATH`).
    """
    logger.info("⏳ Chargement et découpage des données...")
    examples = load_labeled_examples()
    train_examples, _test_examples = split_train_test(examples, train_ratio)

    # Concaténation de la question et de la réponse avec un espace.
    x_train = [f"{ex['question']} {ex['answer']}" for ex in train_examples]
    y_train = [ex["ground_truth_label"] for ex in train_examples]

    logger.info("🧠 Création et entraînement du pipeline NLI (TF-IDF + LogReg)...")

    pipeline = Pipeline(
        [
            ("tfidf", TfidfVectorizer(max_features=10000)),  # Limite optionnelle pour éviter de faire exploser la RAM
            ("clf", LogisticRegression(max_iter=1000)),  # max_iter élevé pour garantir la convergence
        ]
    )

    pipeline.fit(x_train, y_train)

    # Vérification de l'existence du dossier parent avant sauvegarde
    os.makedirs(Path(out_path).parent, exist_ok=True)

    # Sauvegarde
    joblib.dump(pipeline, out_path)
    logger.info("✅ Modèle baseline sauvegardé avec succès dans : %s", out_path)


if __name__ == "__main__":
    from berlue.logging_config import setup_logging

    setup_logging()
    train_baseline()
