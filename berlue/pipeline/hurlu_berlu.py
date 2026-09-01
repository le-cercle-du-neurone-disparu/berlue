import logging

from berlue.core.schemas import PipelineResult, Verdict
from berlue.llm.client import OllamaClient
from berlue.params import OLLAMA_MODEL, OLLAMA_SYSTEM_PROMPT, RAG_MODEL
from berlue.pipeline.extraction import do_extraction
from berlue.pipeline.fusion import do_fusion
from berlue.rag.retriever import RagRetriever
from berlue.selfcheck.sampler import sample_responses
from berlue.selfcheck.scorer import compute_divergence

logger = logging.getLogger(__name__)


class HurluBerlu:
    """Pipeline principal sans état (Stateless) pour la vérification RAG."""

    def __init__(
        self,
        llm_client: OllamaClient | None = None,
        llm_extract: OllamaClient | None = None,
        retriever: RagRetriever | None = None,
    ):
        # Le LLM principal (celui qui répond à la question et génère les samples)
        self.llm_client = llm_client

        # Le LLM outil (celui qui extrait les affirmations)
        self.llm_extract = llm_extract or llm_client

        self.retriever = retriever

    # ÉTAPE 1
    def generate_response(
        self,
        question: str,
    ) -> PipelineResult:
        """Génère la réponse de base à partir de la question de l'utilisateur."""

        # Formatage du prompt avec la question
        prompt = OLLAMA_SYSTEM_PROMPT.format(question=question)

        # Appel au LLM
        answer = self.llm_client.generate(prompt=prompt)

        return PipelineResult(question=question, raw_answer=answer)

    # ÉTAPE 2
    def extract_claims(self, result: PipelineResult) -> PipelineResult:

        result.claims = do_extraction(self.llm_extract, result.raw_answer)

        return result

    # ÉTAPE 3
    def generate_samples(self, result: PipelineResult) -> PipelineResult:

        result.samples = sample_responses(question=result.question, client=self.llm_client)
        return result

    # ÉTAPE 4
    def evaluate_selfcheck(self, result: PipelineResult) -> PipelineResult:

        logger.debug("🧠 Calcul des scores de divergence SelfCheckNLI...")

        for claim in result.claims:
            score = compute_divergence(claim=claim, samples=result.samples)
            result.selfcheck_scores.append(score)
        if result.selfcheck_scores:
            avg_divergence = sum(s.divergence_score for s in result.selfcheck_scores) / len(result.selfcheck_scores)
            avg_confidence = 1.0 - avg_divergence
            alert = "🔴" if avg_divergence > 0.5 else "🟢"
            logger.debug(
                "%s [SelfCheck GLOBAL] Divergence moyenne : %.2f | Confiance : %.2f",
                alert,
                avg_divergence,
                avg_confidence,
            )

        return result

    # ÉTAPE 5
    def evaluate_rag(self, result: PipelineResult) -> PipelineResult:

        logger.debug("🧠 Calcul des verdicts du RAG...")

        for claim in result.claims:
            verdict = self.retriever.verify_claim(claim=claim)
            result.rag_scores.append(verdict)

        return result

    # ÉTAPE 6
    def fuse_results(
        self, result: PipelineResult, weight_rag: float = 0.7, weight_selfcheck: float = 0.3
    ) -> PipelineResult:
        """
        Dernière étape : combine les scores RAG et SelfCheckGPT pour statuer sur chaque affirmation.
        Utilise le pattern Passe-Plat.
        """

        return do_fusion(result, weight_rag, weight_selfcheck)


if __name__ == "__main__":
    import argparse

    from berlue.core.schemas import Verdict

    parser = argparse.ArgumentParser(description="Démo du pipeline HurluBerlu, étape par étape.")
    parser.add_argument(
        "--until",
        choices=["generate", "extract", "samples", "selfcheck", "rag", "fusion"],
        default="fusion",  # Le défaut va jusqu'au bout, c'est à dire la fusion !
        help="S'arrête après cette étape (défaut : fusion).",
    )
    # parser.add_argument("--question", default="Pourquoi l'eau mouille ?", help="Question posée au LLM.")
    parser.add_argument("--question", default="Has Ryan Gosling visited Africa ?", help="Question posée au LLM.")
    args = parser.parse_args()

    parser.add_argument("--model", type=str, default=OLLAMA_MODEL, help="Le modèle LLM à utiliser")
    args = parser.parse_args()

    parser.add_argument("--rag", type=str, default=RAG_MODEL, help="Le modèle LLM à utiliser")
    parser.add_argument(
        "--log-level",
        choices=["ERROR", "WARNING", "INFO", "DEBUG"],
        default=None,
        help="Niveau de log (défaut : BERLUE_LOG_LEVEL, ou INFO).",
    )
    args = parser.parse_args()

    from berlue.logging_config import setup_logging

    setup_logging(args.log_level)

    print("🚀 Démarrage du pipeline HurluBerlu...")
    pipeline = HurluBerlu(
        llm_client=OllamaClient(model=args.model),
        retriever=RagRetriever(llm_client=OllamaClient(model=args.rag, temperature=0.0)),
    )
    print(f"\n❓ Question posée : {args.question}")

    # --- Étape 1 ---
    result = pipeline.generate_response(args.question)
    if args.until == "generate":
        print(f"\n🔹 RÉPONSE BRUTE :\n{result.raw_answer}")
        raise SystemExit

    # --- Étape 2 ---
    result = pipeline.extract_claims(result)
    if args.until == "extract":
        print(f"\n🔹 {len(result.claims)} AFFIRMATION(S) EXTRAITE(S) :")
        for i, claim in enumerate(result.claims, 1):
            print(f"   {i}. {claim.text}")
        raise SystemExit

    # --- Étape 3 ---
    result = pipeline.generate_samples(result)
    if args.until == "samples":
        print(f"\n🔹 {len(result.samples)} ÉCHANTILLON(S) GÉNÉRÉ(S) :")
        for i, sample in enumerate(result.samples, 1):
            print(f"   {i}. {sample.strip()}")
        raise SystemExit

    # --- Étape 4 ---
    final_result = pipeline.evaluate_selfcheck(result)

    # --- Étape 5 ---
    if args.until not in ["selfcheck"]:
        final_result = pipeline.evaluate_rag(final_result)

    # --- Étape 6 : La Fusion ---
    if args.until == "fusion":
        final_result = pipeline.fuse_results(final_result)

    # ==========================================
    # AFFICHAGE DU BILAN FINAL
    # ==========================================
    print("\n✅ Traitement terminé ! Voici le bilan de l'évaluation :")
    print("=" * 70)
    print(f"🔹 QUESTION : {final_result.question}")
    print(f"🔹 RÉPONSE BRUTE :\n{final_result.raw_answer}")
    print("=" * 70)

    print(f"\n🔹 ANALYSE DES {len(final_result.claims)} AFFIRMATIONS :")

    scores_dict = {score.claim_id: score for score in final_result.selfcheck_scores}
    rag_dict = {verdict.claim_id: verdict for verdict in final_result.rag_scores}
    fused_dict = {fused.claim_id: fused for fused in final_result.fused_verdicts}

    for i, claim in enumerate(final_result.claims, 1):
        print(f"\n   {i}. {claim.text}")

        # 1. Affichage SelfCheck
        score = scores_dict.get(claim.id)
        if score:
            alert = "🔴 HALLUCINATION" if score.divergence_score > 0.5 else "🟢 COHÉRENT"
            print(f"      ↳ 🧠 [SelfCheck] : {alert} | Divergence : {score.divergence_score:.2f}")
        else:
            print("      ↳ 🧠 [SelfCheck] : ⚠️ Aucun score.")

        # 2. Affichage RAG
        if final_result.rag_scores:
            rag_verdict = rag_dict.get(claim.id)
            if rag_verdict:
                if rag_verdict.verdict == Verdict.SUPPORTED:
                    rag_alert = "🟢 SUPPORTÉ"
                elif rag_verdict.verdict == Verdict.CONTRADICTED:
                    rag_alert = "🔴 CONTREDIT"
                else:
                    rag_alert = "⚪ PAS ASSEZ D'INFOS"

                print(f"      ↳ 📚 [RAG]       : {rag_alert} | Confiance : {rag_verdict.confidence:.2f}")

                if rag_verdict.evidence:
                    ev_text = rag_verdict.evidence.text
                    if len(ev_text) > 70:
                        ev_text = ev_text[:67] + "..."
                    print(f'          (Preuve: "{ev_text}")')
            else:
                print("      ↳ 📚 [RAG]       : ⚠️ Aucun verdict.")

        # 3. Affichage FUSION
        if final_result.fused_verdicts:
            fused = fused_dict.get(claim.id)
            if fused:
                if fused.verdict == Verdict.SUPPORTED:
                    fused_alert = "🟢 VALIDÉ"
                elif fused.verdict == Verdict.CONTRADICTED:
                    fused_alert = "🔴 REJETÉ"
                else:
                    fused_alert = "⚪ INCERTAIN"

                print(f"      ↳ ✨ [FUSION]    : {fused_alert} | Confiance globale : {fused.confidence:.2f}")
                print(f"          (Explication: {fused.explanation})")
            else:
                print("      ↳ ✨ [FUSION]    : ⚠️ Aucun verdict final.")

    print("\n" + "=" * 70)
