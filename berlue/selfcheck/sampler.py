"""Échantillonnage à température élevée pour SelfCheckGPT (K tirages)."""

from berlue.llm.client import OllamaClient
from berlue.params import SELFCHECK_K, SELFCHECK_TEMPERATURE


def sample_responses(
    question: str,
    k: int = SELFCHECK_K,
    temperature: float = SELFCHECK_TEMPERATURE,
    client: OllamaClient | None = None,
) -> list[str]:
    """Génère K réponses indépendantes à `question` à température élevée."""
    client = client or OllamaClient()
    return client.generate_many(question, k=k, temperature=temperature)
