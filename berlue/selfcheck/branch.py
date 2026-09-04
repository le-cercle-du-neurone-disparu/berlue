"""Branche SelfCheckGPT complète : échantillonner le modèle, puis scorer chaque
affirmation contre ces échantillons.

Deux étages parallélisés séparément, parce qu'ils n'attendent pas la même chose :
les K générations sont bloquées sur le serveur Ollama, les passages NLI sur
torch. Le second dépend du premier — il faut tous les échantillons pour scorer
la première affirmation — donc ils s'enchaînent, chacun sur son pool.
"""

import logging

from berlue.core.schemas import Claim, SelfCheckOutcome
from berlue.llm.client import OllamaClient
from berlue.params import (
    SELFCHECK_K,
    SELFCHECK_SAMPLE_WORKERS,
    SELFCHECK_SCORE_WORKERS,
    SELFCHECK_TEMPERATURE_MAX,
    SELFCHECK_TEMPERATURE_MIN,
)
from berlue.pipeline.parallel import map_parallele
from berlue.selfcheck.sampler import sample_responses
from berlue.selfcheck.scorer import compute_divergence

logger = logging.getLogger(__name__)


def run_selfcheck(
    question: str,
    claims: list[Claim],
    client: OllamaClient,
    k: int = SELFCHECK_K,
    temperature_min: float = SELFCHECK_TEMPERATURE_MIN,
    temperature_max: float = SELFCHECK_TEMPERATURE_MAX,
    sample_workers: int = SELFCHECK_SAMPLE_WORKERS,
    score_workers: int = SELFCHECK_SCORE_WORKERS,
) -> SelfCheckOutcome:
    """Échantillonne le modèle sur `question`, puis score chaque affirmation.

    Les échantillons sont tirés même sans affirmation à scorer : ils décrivent la
    stabilité du modèle sur la question, pas sur une affirmation, et l'API les
    affiche à ce titre.
    """
    samples = sample_responses(
        question=question,
        k=k,
        temperature_min=temperature_min,
        temperature_max=temperature_max,
        client=client,
        max_workers=sample_workers,
    )

    if not claims:
        return SelfCheckOutcome(samples=samples)

    logger.debug("🧠 Calcul des scores de divergence SelfCheckNLI sur %d affirmation(s)...", len(claims))
    scores = map_parallele(
        lambda claim: compute_divergence(claim=claim, samples=samples),
        claims,
        score_workers,
        "selfcheck-nli",
    )

    avg_divergence = sum(s.divergence_score for s in scores) / len(scores)
    alert = "🔴" if avg_divergence > 0.5 else "🟢"
    logger.debug(
        "%s [SelfCheck GLOBAL] Divergence moyenne : %.2f | Confiance : %.2f",
        alert,
        avg_divergence,
        1.0 - avg_divergence,
    )

    return SelfCheckOutcome(samples=samples, scores=scores)
