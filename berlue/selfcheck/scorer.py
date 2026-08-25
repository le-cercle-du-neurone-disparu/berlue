"""Score de divergence SelfCheckGPT par affirmation (zero-resource)."""

from berlue.core.schemas import Claim, SelfCheckScore


def compute_divergence(claim: Claim, samples: list[str]) -> SelfCheckScore:
    """Calcule le score de divergence d'une affirmation par rapport aux échantillons."""
    # TODO(selfcheck)
    raise NotImplementedError
