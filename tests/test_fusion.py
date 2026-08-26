"""Test de contrat pour `berlue.fusion.fuse` -> `FusedVerdict`."""

import pytest

from berlue.core.schemas import Claim, FusedVerdict, RagVerdict, SelfCheckScore, Verdict
from berlue.fusion import fuse


@pytest.mark.skip(reason="TODO: à activer une fois fuse() implémenté")
def test_fuse_returns_fused_verdict():
    """fuse() doit renvoyer un FusedVerdict valide, y compris quand rag_verdict est None."""
    claim = Claim(id="c1", text="La Terre est ronde.", source_answer="...")
    selfcheck_score = SelfCheckScore(claim_id="c1", divergence_score=0.1, confidence=0.9)

    rag_verdict = RagVerdict(claim_id="c1", verdict=Verdict.SUPPORTED, confidence=0.8)
    result = fuse(claim, rag_verdict, selfcheck_score)
    assert isinstance(result, FusedVerdict)
    assert result.claim_id == "c1"
    assert 0.0 <= result.confidence <= 1.0

    result_no_rag = fuse(claim, None, selfcheck_score)
    assert isinstance(result_no_rag, FusedVerdict)
    assert 0.0 <= result_no_rag.confidence <= 1.0
