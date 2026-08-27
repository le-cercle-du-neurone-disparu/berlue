"""Tests pour `berlue.pipeline.hurlu_berlu.HurluBerlu` — unitaires, un
`OllamaClient` stubé remplace le vrai (pas de serveur Ollama requis)."""

from berlue.core.schemas import Claim, PipelineResult, SelfCheckScore
from berlue.pipeline import hurlu_berlu
from berlue.pipeline.hurlu_berlu import HurluBerlu


class StubOllamaClient:
    """Remplace `OllamaClient` : mêmes méthodes, réponses fixées à l'avance."""

    def __init__(self, response: str = "", responses: list[str] | None = None):
        self.response = response
        self.responses = responses or []

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        return self.response

    def generate_many(self, prompt: str, k: int, temperature_min: float, temperature_max: float) -> list[str]:
        return self.responses


def test_generate_response_builds_pipeline_result():
    stub = StubOllamaClient(response="L'eau mouille car elle a une faible tension de surface.")
    pipeline = HurluBerlu(llm_client=stub)

    result = pipeline.generate_response("Pourquoi l'eau mouille ?")

    assert isinstance(result, PipelineResult)
    assert result.question == "Pourquoi l'eau mouille ?"
    assert result.raw_answer == "L'eau mouille car elle a une faible tension de surface."


def test_extract_claims_parses_bullet_list():
    stub = StubOllamaClient(response="- Affirmation A.\n- Affirmation B.\ntexte hors liste, ignoré\n- Affirmation C.")
    pipeline = HurluBerlu(llm_client=stub)
    result = PipelineResult(question="Q ?", raw_answer="peu importe, le stub ignore le prompt")

    result = pipeline.extract_claims(result)

    assert [claim.text for claim in result.claims] == ["Affirmation A.", "Affirmation B.", "Affirmation C."]
    assert all(isinstance(claim, Claim) for claim in result.claims)
    assert all(claim.source_answer == result.raw_answer for claim in result.claims)


def test_extract_claims_on_empty_answer_returns_no_claims():
    stub = StubOllamaClient(response="- ne devrait jamais être appelé")
    pipeline = HurluBerlu(llm_client=stub)
    result = PipelineResult(question="Q ?", raw_answer="   ")

    result = pipeline.extract_claims(result)

    assert result.claims == []


def test_generate_samples_delegates_to_sampler():
    stub = StubOllamaClient(responses=["échantillon 1", "échantillon 2", "échantillon 3"])
    pipeline = HurluBerlu(llm_client=stub)
    result = PipelineResult(question="Pourquoi l'eau mouille ?", raw_answer="...")

    result = pipeline.generate_samples(result)

    assert result.samples == ["échantillon 1", "échantillon 2", "échantillon 3"]


def test_evaluate_selfcheck_appends_one_score_per_claim(monkeypatch):
    def fake_compute_divergence(claim: Claim, samples: list[str]) -> SelfCheckScore:
        return SelfCheckScore(claim_id=claim.id, divergence_score=0.2, confidence=0.8)

    monkeypatch.setattr(hurlu_berlu, "compute_divergence", fake_compute_divergence)

    pipeline = HurluBerlu(llm_client=StubOllamaClient())
    result = PipelineResult(
        question="Q ?",
        raw_answer="...",
        claims=[
            Claim(id="c1", text="Affirmation A.", source_answer="..."),
            Claim(id="c2", text="Affirmation B.", source_answer="..."),
        ],
        samples=["échantillon 1", "échantillon 2"],
    )

    result = pipeline.evaluate_selfcheck(result)

    assert [score.claim_id for score in result.selfcheck_scores] == ["c1", "c2"]
    assert all(score.divergence_score == 0.2 for score in result.selfcheck_scores)
