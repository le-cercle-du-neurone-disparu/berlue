"""Échantillonnage à température espacée pour SelfCheckGPT (K tirages)."""

from berlue.llm.client import OllamaClient
from berlue.params import OLLAMA_SYSTEM_PROMPT, SELFCHECK_K, SELFCHECK_TEMPERATURE_MAX, SELFCHECK_TEMPERATURE_MIN


def sample_responses(
    question: str,
    k: int = SELFCHECK_K,
    temperature_min: float = SELFCHECK_TEMPERATURE_MIN,
    temperature_max: float = SELFCHECK_TEMPERATURE_MAX,
    client: OllamaClient | None = None,
) -> list[str]:
    """Génère K réponses indépendantes à `question`, chacune à une température
    espacée dans `[temperature_min, temperature_max]`."""
    prompt = OLLAMA_SYSTEM_PROMPT.format(question=question)
    client = client or OllamaClient()
    return client.generate_many(prompt, k=k, temperature_min=temperature_min, temperature_max=temperature_max)
