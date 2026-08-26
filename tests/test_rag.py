"""Test de contrat pour `berlue.rag.retriever.verify_claim` -> `RagVerdict`."""

import pytest

from berlue.core.schemas import Claim, RagVerdict, Verdict
from berlue.rag.retriever import RagRetriever


@pytest.mark.skip(reason="TODO: à activer une fois verify_claim() implémenté")
def test_verify_claim_returns_rag_verdict():
    """verify_claim() doit renvoyer un RagVerdict valide ; evidence=None ne doit pas planter."""
    retriever = RagRetriever()
    claim = Claim(id="c1", text="Paris est la capitale de la France.", source_answer="...")
    result = retriever.verify_claim(claim)
    assert isinstance(result, RagVerdict)
    assert result.claim_id == claim.id
    assert result.verdict in Verdict
    assert 0.0 <= result.confidence <= 1.0
