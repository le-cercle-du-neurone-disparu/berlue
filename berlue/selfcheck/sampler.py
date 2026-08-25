"""Échantillonnage à température élevée pour SelfCheckGPT (K tirages)."""

from berlue.llm.client import OllamaClient
from berlue.params import SELFCHECK_K, SELFCHECK_TEMPERATURE_MAX, SELFCHECK_TEMPERATURE_MIN


def sample_responses(
    question: str,
    k: int = SELFCHECK_K,
    temperature_min: float = SELFCHECK_TEMPERATURE_MIN,
    temperature_max: float = SELFCHECK_TEMPERATURE_MAX,
    client: OllamaClient | None = None,
) -> list[str]:
    """Génère K réponses indépendantes à `question`, chacune à une température
    aléatoire dans `[temperature_min, temperature_max]`."""
    client = client or OllamaClient()
    return client.generate_many(
        question, k=k, temperature_min=temperature_min, temperature_max=temperature_max
    )
