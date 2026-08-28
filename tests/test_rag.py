"""Test de contrat pour `berlue.rag.retriever.verify_claim` -> `RagVerdict`."""

import pytest

from berlue.core.schemas import Claim, RagVerdict, Verdict
from berlue.rag.retriever import RagRetriever


@pytest.mark.functional  # a besoin d'un index FAISS + embeddings réels (RagRetriever)
def test_verify_claim_returns_rag_verdict():
    """verify_claim() doit renvoyer un RagVerdict valide pour une affirmation proche du corpus."""
    retriever = RagRetriever()
    claim = Claim(id="c1", text="Paris est la capitale de la France.", source_answer="...")
    result = retriever.verify_claim(claim)
    assert isinstance(result, RagVerdict)
    assert result.claim_id == claim.id
    assert result.verdict in Verdict
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.functional  # a besoin d'un index FAISS + embeddings réels (RagRetriever)
def test_verify_claim_handles_no_evidence_found():
    """Une affirmation sans rapport avec le corpus doit renvoyer NOT_ENOUGH_INFO avec
    evidence=None, pas planter — c'est la branche de repli de verify_claim() quand
    aucune preuve récupérée n'est assez proche."""
    retriever = RagRetriever()
    claim = Claim(id="c2", text="Xyzzy qwerty plugh zzzz asdf lorem ipsum dolor sit.", source_answer="...")
    result = retriever.verify_claim(claim)
    assert isinstance(result, RagVerdict)
    assert result.verdict == Verdict.NOT_ENOUGH_INFO
    assert result.evidence is None
