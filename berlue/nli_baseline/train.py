"""Entraîne un classifieur NLI léger (TF-IDF + régression logistique) sur une
partie de HaluEval/TruthfulQA, utilisé comme baseline de comparaison par
`berlue.evaluation` — le reste sert de jeu de test (cf. `berlue.evaluation.data`).

Params utilisés (`berlue.params`) : `NLI_BASELINE_PATH`.
"""

import os
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from berlue.evaluation.data import load_labeled_examples, split_train_test
from berlue.params import NLI_BASELINE_PATH


def train_baseline(out_path: str = NLI_BASELINE_PATH, test_size: float = 0.2) -> None:
    """Entraîne un TfidfVectorizer + LogisticRegression sur le texte
    question+réponse d'une partie de HaluEval/TruthfulQA et sauvegarde le modèle
    avec joblib vers `out_path` (défaut : `params.NLI_BASELINE_PATH`).
    """
    print("⏳ Chargement et découpage des données...")
    examples = load_labeled_examples()
    train_examples, _test_examples = split_train_test(examples, test_size)

    # 3. Vectoriser question+réponse.
    # On concatène simplement la question et la réponse avec un espace.
    # (Ajuste la syntaxe si 'train_examples' contient des dictionnaires et non des objets)
    x_train = [f"{ex['question']} {ex['answer']}" for ex in train_examples]
    y_train = [ex["ground_truth_label"] for ex in train_examples]

    print("🧠 Création et entraînement du pipeline NLI (TF-IDF + LogReg)...")
    # L'utilisation d'un Pipeline permet d'encapsuler la vectorisation et la prédiction
    pipeline = Pipeline(
        [
            ("tfidf", TfidfVectorizer(max_features=10000)),  # Limite optionnelle pour éviter de faire exploser la RAM
            ("clf", LogisticRegression(max_iter=1000)),  # max_iter élevé pour garantir la convergence
        ]
    )

    pipeline.fit(x_train, y_train)

    # 4. Sauvegarde
    # On s'assure que le dossier parent existe avant de sauvegarder
    os.makedirs(Path(out_path).parent, exist_ok=True)

    joblib.dump(pipeline, out_path)
    print(f"✅ Modèle baseline sauvegardé avec succès dans : {out_path}")


if __name__ == "__main__":
    train_baseline()
