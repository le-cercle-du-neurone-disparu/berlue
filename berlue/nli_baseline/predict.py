"""Prédiction avec le classifieur NLI léger — baseline de comparaison utilisée par
`berlue.evaluation` face au pipeline Berlue complet (RAG inversé + SelfCheckGPT).

Params utilisés (`berlue.params`) : `NLI_BASELINE_PATH`."""

from berlue.core.schemas import Verdict
from berlue.params import NLI_BASELINE_PATH


class NliBaseline:
    """Charge le modèle entraîné par `train.train_baseline` et prédit un verdict
    directement depuis le texte question+réponse, sans preuve/evidence — c'est ce
    qui distingue ce baseline du pipeline complet, qui s'appuie sur le RAG."""

    def __init__(self, model_path: str = NLI_BASELINE_PATH):
        self.model_path = model_path
        # TODO(nli_baseline): joblib.load(model_path) — lever une erreur claire si
        # le fichier n'existe pas encore (rappeler de lancer train.py d'abord).
        raise NotImplementedError

    def predict(self, question: str, answer: str) -> Verdict:
        """Prédit soutenue/contredite (`Verdict.SUPPORTED`/`Verdict.CONTRADICTED`)
        pour une paire question/réponse — jamais `Verdict.NOT_ENOUGH_INFO` :
        HaluEval et TruthfulQA sont tous deux des labels binaires vrai/faux."""
        # TODO(nli_baseline)
        # return Verdict.SUPPORTED  # ou Verdict.CONTRADICTED
        raise NotImplementedError
