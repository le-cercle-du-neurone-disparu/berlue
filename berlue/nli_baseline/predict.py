"""Prédiction avec le classifieur NLI léger — baseline de comparaison utilisée par
`berlue.evaluation` face au pipeline Berlue complet (RAG inversé + SelfCheckGPT).

Params utilisés (`berlue.params`) : `NLI_BASELINE_PATH`.
"""

import os

import joblib

from berlue.core.schemas import Verdict
from berlue.params import NLI_BASELINE_PATH


class NliBaseline:
    """Charge le modèle entraîné par `train.train_baseline` et prédit un verdict
    directement depuis le texte question+réponse, sans preuve/evidence — c'est ce
    qui distingue ce baseline du pipeline complet, qui s'appuie sur le RAG.
    """

    def __init__(self, model_path: str = NLI_BASELINE_PATH):
        self.model_path = model_path

        # Vérification de l'existence du modèle
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Le modèle NLI n'a pas été trouvé au chemin : '{self.model_path}'.\n"
                "💡 N'oubliez pas d'exécuter le script d'entraînement en premier "
                "(ex: `python -m berlue.train` ou `make train_baseline`)."
            )

        # Chargement du Pipeline scikit-learn
        self.pipeline = joblib.load(self.model_path)

    def predict(self, question: str, answer: str) -> Verdict:
        """Prédit soutenue/contredite (`Verdict.SUPPORTED`/`Verdict.CONTRADICTED`)
        pour une paire question/réponse — jamais `Verdict.NOT_ENOUGH_INFO` :
        HaluEval et TruthfulQA sont tous deux des labels binaires vrai/faux.
        """
        # Utilisation de la même logique de concaténation qu'à l'entraînement
        text_input = f"{question} {answer}"

        # Le modèle attend une liste de textes, on passe donc une liste à un élément.
        # [0] permet de récupérer la prédiction unique depuis le tableau (numpy array) retourné.
        raw_prediction = self.pipeline.predict([text_input])[0]

        # raw_prediction est un booléen (True pour vrai/supporté, False pour halluciné/contredit)
        if raw_prediction:
            return Verdict.SUPPORTED
        else:
            return Verdict.CONTRADICTED


if __name__ == "__main__":
    result = NliBaseline().predict(
        question="Quelle est la capitale de la France ?",
        answer="Paris est la capitale de la France.",
    )
    print(result)
