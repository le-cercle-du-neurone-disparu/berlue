"""Pipeline Berlue factice pour développer la boucle d'évaluation sans dépendre
d'un LLM ni d'un index FAISS réels.

Ne pas confondre avec `berlue.mocks.mock_pipeline.MockBerluePipeline` (mock figé
utilisé pour le développement frontend, activé par `USE_MOCK`) : celui-ci vise au
contraire une diversité aléatoire des verdicts, pour exercer toutes les cases de
la matrice de confusion pendant le développement de `berlue.evaluation.run_eval`.
"""

import random

from berlue.api.schemas import ClaimResult, LLMConfig, PredictOutput

STATUSES = ["green", "orange", "red"]
EVIDENCE_SOURCES = ["FEVER_corpus", "SelfCheckGPT"]

CLAIM_TEMPLATES = [
    "Le sujet de la question est correctement identifié.",
    "La date mentionnée dans la réponse est exacte.",
    "Le lieu cité correspond aux sources disponibles.",
    "La relation de cause à effet énoncée est vérifiable.",
    "Le chiffre avancé est cohérent avec le corpus de référence.",
]

EVIDENCE_TEMPLATES = [
    "Aucune contradiction détectée dans les échantillons SelfCheckGPT.",
    "Preuve trouvée dans le corpus FEVER confirmant l'affirmation.",
    "Preuve trouvée dans le corpus FEVER contredisant l'affirmation.",
    "Les échantillons générés divergent fortement entre eux.",
]


class RandomBerluePipeline:
    """Simule `predict()` avec des verdicts tirés au hasard, sans appeler ni LLM
    ni retriever — sert à développer et tester la boucle d'évaluation
    (`berlue.evaluation.run_eval`) indépendamment de la disponibilité d'Ollama.
    """

    def __init__(self, seed: int | None = None, min_claims: int = 1, max_claims: int = 4):
        self.rng = random.Random(seed)
        self.min_claims = min_claims
        self.max_claims = max_claims

    def predict(self, question: str, answer: str | None = None, llm: LLMConfig | None = None) -> PredictOutput:
        """Même signature que `BerlueService.predict` — `answer`/`llm` sont
        acceptés pour la compatibilité d'appel mais n'influencent aucun
        résultat, tout est tiré aléatoirement.

        Si `answer` est fourni (vérification d'une réponse donnée, cf. jeu de
        test d'évaluation), il est renvoyé tel quel dans `full_llm_answer` —
        sinon une réponse simulée est générée.
        """
        llm = llm or LLMConfig()

        n_claims = self.rng.randint(self.min_claims, self.max_claims)
        claims = [self._random_claim(index) for index in range(n_claims)]

        return PredictOutput(
            question=question,
            llm_used=llm,
            full_llm_answer=answer if answer is not None else f"Réponse simulée à : {question}",
            claims=claims,
        )

    def _random_claim(self, index: int) -> ClaimResult:
        template = self.rng.choice(CLAIM_TEMPLATES)
        return ClaimResult(
            claim_text=f"{template} (#{index + 1})",
            status=self.rng.choice(STATUSES),
            fusion_score=round(self.rng.uniform(0.0, 1.0), 2),
            evidence_source=self.rng.choice(EVIDENCE_SOURCES),
            evidence_text=self.rng.choice(EVIDENCE_TEMPLATES),
        )
