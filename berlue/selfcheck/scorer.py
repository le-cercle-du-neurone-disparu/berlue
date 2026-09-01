"""Score de divergence SelfCheckGPT par affirmation (méthode NLI officielle)."""

import logging

import torch
from selfcheckgpt.modeling_selfcheck import SelfCheckNLI

from berlue.core.schemas import Claim, SelfCheckScore

logger = logging.getLogger(__name__)

# Variable globale pour garder le modèle en mémoire (Singleton)
_SELFCHECK_NLI_MODEL = None


def _get_selfcheck_nli() -> SelfCheckNLI:
    """Charge le modèle NLI une seule fois en mémoire (sur GPU si disponible)."""

    global _SELFCHECK_NLI_MODEL

    if _SELFCHECK_NLI_MODEL is None:
        # Détection automatique du matériel (Nvidia CUDA ou CPU)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        logger.info("⏳ Initialisation de SelfCheckNLI sur : %s...", device)

        _SELFCHECK_NLI_MODEL = SelfCheckNLI(device=device)

    return _SELFCHECK_NLI_MODEL


def compute_divergence(claim: Claim, samples: list[str]) -> SelfCheckScore:
    """Calcule le score de divergence d'une affirmation par rapport aux échantillons
    en utilisant le package officiel SelfCheckGPT (modèle NLI).
    """

    if not samples:
        raise ValueError(
            f"❌ Impossible d'évaluer l'affirmation '{claim.id}' : "
            "la liste d'échantillons (samples) est vide. Le LLM a probablement échoué en amont."
        )

    # Récupération du modèle (déjà chargé en VRAM/RAM)
    selfcheck_nli = _get_selfcheck_nli()

    # Le package attend une LISTE de phrases. On met notre 'claim.text' dans une liste.
    # Il va comparer cette phrase avec la liste des 'samples'.
    scores = selfcheck_nli.predict(sentences=[claim.text], sampled_passages=samples)

    # scores est un tableau numpy (ex: [0.334014]), on extrait la première valeur
    divergence = float(scores[0])
    logger.debug("divergence = %s", divergence)
    return SelfCheckScore(claim_id=claim.id, divergence_score=divergence, confidence=1.0 - divergence)
