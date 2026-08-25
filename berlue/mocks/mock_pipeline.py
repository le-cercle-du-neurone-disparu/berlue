# berlue/mocks/mock_pipeline.py

from berlue.api.schemas import LLMConfig


class MockBerluePipeline:
    """
    Fake pipeline used for frontend development.
    Simulates the behavior of the real ML model.
    """

    def get_available_llms(self) -> list[str]:
        """
        Returns a mock list of available LLMs.
        """
        return ["llama3", "mistral-7b", "gpt-3.5-turbo", "claude-3-haiku"]

    def predict(self, question: str, llm_config: LLMConfig) -> dict:
        """
        Simulates generating an answer and finding a hallucination.
        """
        # We return a dictionary that exactly matches the PredictOutput schema
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
        Simulates running a full benchmark.
        """
        # We return a dictionary that exactly matches the Metrics schema
        # The llm_config is passed here if you ever need to simulate different metrics
        # based on the model or temperature chosen!
        return {"berlue_accuracy": 0.82, "baseline_nli_accuracy": 0.65, "berlue_precision": 0.85}
