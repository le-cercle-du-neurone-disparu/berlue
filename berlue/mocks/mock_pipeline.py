# berlue/mocks/mock_pipeline.py

from berlue.api.schemas import LLMConfig


class MockBerluePipeline:
    """
    Faux pipeline utilisé pour le développement frontend.
    Simule le comportement du vrai modèle ML.
    """

    def get_available_llms(self) -> list[str]:
        """
        Retourne une liste factice de LLM disponibles (tags Ollama réels, pullables).
        """
        return ["qwen2.5:0.5b", "qwen2.5:1.5b", "llama3.2:1b", "gemma3:1b"]

    def predict(self, question: str, llm_config: LLMConfig) -> dict:
        """
        Simule la génération d'une réponse et la détection d'une hallucination.
        """
        # On retourne un dictionnaire qui correspond exactement au schéma PredictOutput
        return {
            "question": question,
            "llm_used": {"name": llm_config.name, "temperature": llm_config.temperature},
            "full_llm_answer": "Le ciel est vert. C'est dû à la réfraction.",
            "claims": [
                {
                    "claim_text": "Le ciel est vert.",
                    "status": "red",
                    "fusion_score": 0.88,
                    "evidence_source": "FEVER_corpus",
                    "evidence_text": "Le ciel est bleu pendant la journée.",
                },
                {
                    "claim_text": "C'est dû à la réfraction.",
                    "status": "green",
                    "fusion_score": 0.15,
                    "evidence_source": "SelfCheckGPT",
                    "evidence_text": "Aucune contradiction détectée.",
                },
            ],
        }

    def evaluate_dataset(self, dataset_name: str, n_samples: int, llm_config: LLMConfig) -> dict:
        """
        Simule l'exécution d'un benchmark complet.
        """
        # On retourne un dictionnaire qui correspond exactement au schéma Metrics (2 matrices
        # de confusion 2x3 : baseline vs berlue, sur 75 assertions vraies + 25 fausses)
        # Le llm_config est passé ici au cas où vous voudriez simuler des métriques différentes
        # selon le modèle ou la température choisis !
        return {
            "baseline": {
                "ground_truth_true": {"predicted_true": 50, "predicted_undecided": 15, "predicted_false": 10},
                "ground_truth_false": {"predicted_true": 8, "predicted_undecided": 7, "predicted_false": 10},
            },
            "berlue": {
                "ground_truth_true": {"predicted_true": 62, "predicted_undecided": 8, "predicted_false": 5},
                "ground_truth_false": {"predicted_true": 4, "predicted_undecided": 6, "predicted_false": 15},
            },
        }
