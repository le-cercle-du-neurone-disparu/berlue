"""Échantillonnage à température espacée pour SelfCheckGPT (K tirages)."""

from berlue.llm.client import OllamaClient
from berlue.params import (
    NUM_PREDICT_ANSWER,
    OLLAMA_SYSTEM_PROMPT,
    SELFCHECK_K,
    SELFCHECK_SAMPLE_WORKERS,
    SELFCHECK_TEMPERATURE_MAX,
    SELFCHECK_TEMPERATURE_MIN,
)


def sample_responses(
    question: str,
    k: int = SELFCHECK_K,
    temperature_min: float = SELFCHECK_TEMPERATURE_MIN,
    temperature_max: float = SELFCHECK_TEMPERATURE_MAX,
    client: OllamaClient | None = None,
    max_workers: int = SELFCHECK_SAMPLE_WORKERS,
) -> list[str]:
    """Génère K réponses indépendantes à `question`, chacune à une température
    espacée dans `[temperature_min, temperature_max]`.

    Les K appels partent en parallèle (`max_workers`), la liste rendue restant
    ordonnée par température croissante."""
    prompt = OLLAMA_SYSTEM_PROMPT.format(question=question)
    client = client or OllamaClient()
    return client.generate_many(
        prompt,
        k=k,
        temperature_min=temperature_min,
        temperature_max=temperature_max,
        num_predict=NUM_PREDICT_ANSWER,
        max_workers=max_workers,
    )
