import ollama

from berlue.api.schemas import ClaimResult, PredictInput, PredictOutput
from berlue.core.schemas import Verdict
from berlue.llm.client import OllamaClient
from berlue.pipeline.hurlu_berlu import HurluBerlu


class BerlueService:
    def predict(self, payload: PredictInput, retriever, extractor) -> PredictOutput:
        """
        Exécute le pipeline et retourne une réponse typée Pydantic.
        """
        # 1. Création du client cible via le payload
        target_llm = OllamaClient(model=payload.llm.name, temperature=payload.llm.temperature)

        # 2. Initialisation du pipeline avec nos outils
        pipeline = HurluBerlu(llm_client=target_llm, llm_extract=extractor, retriever=retriever)

        # 3. Exécution du pipeline
        res = pipeline.generate_response(payload.question)
        res = pipeline.extract_claims(res)
        res = pipeline.generate_samples(res)
        res = pipeline.evaluate_selfcheck(res)
        res = pipeline.evaluate_rag(res)
        res = pipeline.fuse_results(res)

        # 4. Formatage strict avec Pydantic
        claims_output = []
        for fused in res.fused_verdicts:
            # Mapping des couleurs
            if fused.verdict == Verdict.SUPPORTED:
                status = "green"
            elif fused.verdict == Verdict.CONTRADICTED:
                status = "red"
            else:
                status = "orange"

            # Création de l'objet Pydantic ClaimResult
            claim_res = ClaimResult(
                claim_text=fused.claim_text,
                status=status,
                fusion_score=fused.confidence,
                evidence_source="FEVER_corpus" if fused.evidence else "SelfCheckGPT",
                evidence_text=fused.evidence.text if fused.evidence else fused.explanation,
            )
            claims_output.append(claim_res)

        # 5. Retourne l'objet global PredictOutput
        return PredictOutput(
            question=payload.question, llm_used=payload.llm, full_llm_answer=res.raw_answer, claims=claims_output
        )

    def get_available_llms(self) -> list[str]:
        """
        Récupère la liste réelle des modèles installés dans l'Ollama local.
        Si Ollama est inaccessible, l'erreur remontera naturellement jusqu'au endpoint FastAPI.
        """
        response = ollama.list()

        models_list = response.get("models", []) if isinstance(response, dict) else response.models

        available_names = []
        for m in models_list:
            name = m.get("name") if isinstance(m, dict) else m.model
            available_names.append(name)

        return available_names
