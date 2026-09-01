"""Adaptateur qui expose `HurluBerlu` (le vrai pipeline de vérification, cf.
`berlue.pipeline.hurlu_berlu`) sous le même contrat d'appel que
`berlue.evaluation.mock_pipeline.RandomBerluePipeline` — `predict(question,
answer, llm=None) -> PredictOutput` — pour brancher `berlue.evaluation.run_eval`
sur le pipeline réel.

Distinct de `berlue.api.service.BerlueService` (utilisé par l'endpoint HTTP
`/predict`) : signature différente (payload Pydantic + retriever/extractor
injectés par la route FastAPI à chaque requête), pas réutilisable telle
quelle dans une boucle d'éval qui construit son pipeline une fois (retriever
compris — coûteux à charger, cf. `RagRetriever.__init__`) et l'appelle en
boucle sur des milliers de questions.
"""

from berlue.api.schemas import STATUS_BY_VERDICT, ClaimResult, LLMConfig, PredictOutput
from berlue.core.schemas import PipelineResult
from berlue.llm.client import OllamaClient
from berlue.params import EXTRACT_MODEL, OLLAMA_MODEL, RAG_MODEL
from berlue.pipeline.hurlu_berlu import HurluBerlu
from berlue.rag.retriever import RagRetriever


class BerluePipeline:
    """Enveloppe `HurluBerlu` pour vérifier une réponse déjà donnée — jamais
    en générer une nouvelle en conditions normales : `run_eval.evaluate_model`/
    `evaluate_model_generated` fournissent toujours `answer` (la réponse du
    dataset, ou celle déjà générée par `generator_client`), `predict()` ne
    fait qu'extraire et vérifier ses affirmations.
    """

    def __init__(
        self,
        llm_client: OllamaClient | None = None,
        llm_extract: OllamaClient | None = None,
        retriever: RagRetriever | None = None,
    ):
        self._pipeline = HurluBerlu(
            llm_client=llm_client or OllamaClient(model=OLLAMA_MODEL),
            llm_extract=llm_extract or OllamaClient(model=EXTRACT_MODEL),
            retriever=retriever or RagRetriever(llm_client=OllamaClient(model=RAG_MODEL, temperature=0.0)),
        )

    def compute_signals(self, question: str, answer: str | None = None) -> PipelineResult:
        """Tout le pipeline **sauf** la fusion : extraction, échantillons, SelfCheck,
        RAG. C'est la partie coûteuse (un appel LLM par affirmation côté RAG, K
        échantillons côté SelfCheck), et c'est elle qu'on met en cache — la fusion
        qui la consomme est une fonction pure, instantanée, qu'on veut pouvoir
        rejouer avec d'autres `FUSION_*` sans repayer ces appels.
        """
        result = (
            PipelineResult(question=question, raw_answer=answer)
            if answer is not None
            else self._pipeline.generate_response(question)
        )
        result = self._pipeline.extract_claims(result)
        result = self._pipeline.generate_samples(result)
        result = self._pipeline.evaluate_selfcheck(result)
        return self._pipeline.evaluate_rag(result)

    def fuse(self, result: PipelineResult, llm: LLMConfig | None = None) -> PredictOutput:
        """Fusion seule, depuis des signaux fraîchement calculés ou relus du cache."""
        result = self._pipeline.fuse_results(result)

        claims = [
            ClaimResult(
                claim_text=fused.claim_text,
                status=STATUS_BY_VERDICT[fused.verdict],
                fusion_score=fused.confidence,
                evidence_source="FEVER_corpus" if fused.evidence else "SelfCheckGPT",
                evidence_text=fused.evidence.text if fused.evidence else fused.explanation,
            )
            for fused in result.fused_verdicts
        ]

        return PredictOutput(
            question=result.question, llm_used=llm or LLMConfig(), full_llm_answer=result.raw_answer, claims=claims
        )

    def predict(self, question: str, answer: str | None = None, llm: LLMConfig | None = None) -> PredictOutput:
        """Même signature que `RandomBerluePipeline.predict` — `llm` n'est pas utilisé
        (contrairement à `BerlueService.predict`, le modèle sous test est figé à la
        construction de ce pipeline, pas par appel).
        """
        return self.fuse(self.compute_signals(question, answer), llm)
