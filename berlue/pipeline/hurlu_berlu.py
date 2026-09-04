"""Pipeline principal de vérification : génère, extrait, puis fait juger la réponse
par deux branches indépendantes avant de les fusionner.

    generate_answer ─> extract_claims ─┬─> branche RAG (fidélité documentaire) ──┐
                                       └─> branche SelfCheck (cohérence interne) ┴─> fusion

Les deux branches ne partagent rien une fois les affirmations extraites : elles
lisent la même liste d'affirmations, en lecture seule, et rendent chacune son
propre résultat. Elles tournent donc dans deux threads, et chacune répartit ses
propres appels sur son pool (cf. `berlue.params.RAG_WORKERS` et
`SELFCHECK_*_WORKERS`).

Aucune étape ne remplit un objet commun : `PipelineResult` est figé et assemblé
en une seule fois, quand les deux branches ont fini.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from berlue.core.schemas import Claim, PipelineResult, RagJudgment, Verdict
from berlue.llm.client import OllamaClient
from berlue.params import NUM_PREDICT_ANSWER, OLLAMA_MODEL, OLLAMA_SYSTEM_PROMPT, RAG_MODEL
from berlue.pipeline.extraction import do_extraction
from berlue.pipeline.fusion import do_fusion
from berlue.rag.retriever import RagRetriever
from berlue.selfcheck.branch import run_selfcheck

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
    def generate_answer(self, question: str) -> str:
        """Génère la réponse de base à partir de la question de l'utilisateur."""
        prompt = OLLAMA_SYSTEM_PROMPT.format(question=question)
        return self.llm_client.generate(prompt=prompt, num_predict=NUM_PREDICT_ANSWER)

    # ÉTAPE 2
    def extract_claims(self, question: str, answer: str) -> list[Claim]:
        """Découpe la réponse en affirmations atomiques."""
        return do_extraction(self.llm_extract, question=question, answer_text=answer)

    # ÉTAPE 3 — les deux branches, en parallèle
    def compute_signals(self, question: str, answer: str | None = None) -> PipelineResult:
        """Tout le pipeline **sauf** la fusion : génération (si `answer` est absent),
        extraction, puis les deux branches de vérification en parallèle.

        C'est la partie coûteuse — un appel LLM par affirmation côté RAG, K
        échantillons plus un passage NLI par affirmation côté SelfCheck — et c'est
        elle qu'on met en cache : la fusion qui la consomme est une fonction pure,
        instantanée, qu'on veut pouvoir rejouer avec d'autres `FUSION_*` sans
        repayer ces appels.
        """
        raw_answer = answer if answer is not None else self.generate_answer(question)
        claims = self.extract_claims(question, raw_answer)

        # Deux threads, un par branche. Les deux futurs sont lus avant de sortir du
        # bloc : une exception dans l'une n'abandonne pas l'autre en arrière-plan,
        # le `with` l'attend de toute façon.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="branche") as executor:
            futur_rag = executor.submit(self.retriever.verify_claims, claims)
            futur_selfcheck = executor.submit(run_selfcheck, question, claims, self.llm_client)
            rag = futur_rag.result()
            selfcheck = futur_selfcheck.result()

        return PipelineResult(
            question=question,
            raw_answer=raw_answer,
            claims=claims,
            samples=selfcheck.samples,
            selfcheck_scores=selfcheck.scores,
            rag_scores=rag.verdicts,
            rag_traces=rag.traces,
            panne=rag.panne,
        )

    # ÉTAPE 4
    def fuse(self, result: PipelineResult) -> PipelineResult:
        """Combine le jugement RAG et le score SelfCheck pour statuer sur chaque
        affirmation. Les poids et seuils viennent de `params.py` (`FUSION_*`), pas
        de la signature : ils doivent être réglables sans éditer chaque appelant."""
        return do_fusion(result)

    def run(self, question: str, answer: str | None = None) -> PipelineResult:
        """Le pipeline complet, de la question aux verdicts fusionnés."""
        return self.fuse(self.compute_signals(question, answer))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Démo du pipeline HurluBerlu, étape par étape.")
    parser.add_argument(
        "--until",
        choices=["generate", "extract", "selfcheck", "rag", "fusion"],
        default="fusion",  # Le défaut va jusqu'au bout, c'est à dire la fusion !
        help="S'arrête après cette étape (défaut : fusion).",
    )
    parser.add_argument("--question", default="Has Ryan Gosling visited Africa ?", help="Question posée au LLM.")
    parser.add_argument("--model", type=str, default=OLLAMA_MODEL, help="Modèle qui répond et fournit les échantillons")
    parser.add_argument("--rag", type=str, default=RAG_MODEL, help="Modèle du RAG inversé")
    parser.add_argument(
        "--log-level",
        choices=["ERROR", "WARNING", "INFO", "DEBUG"],
        default=None,
        help="Niveau de log (défaut : BERLUE_LOG_LEVEL, ou INFO).",
    )
    # Un seul parse_args, après TOUS les add_argument : les trois appels successifs
    # d'avant faisaient rejeter --model, --rag et --log-level comme inconnus.
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
    raw_answer = pipeline.generate_answer(args.question)
    if args.until == "generate":
        print(f"\n🔹 RÉPONSE BRUTE :\n{raw_answer}")
        raise SystemExit

    # --- Étape 2 ---
    claims = pipeline.extract_claims(args.question, raw_answer)
    if args.until == "extract":
        print(f"\n🔹 {len(claims)} AFFIRMATION(S) EXTRAITE(S) :")
        for i, claim in enumerate(claims, 1):
            print(f"   {i}. {claim.text}")
        raise SystemExit

    # --- Étape 3 : une seule branche, ou les deux en parallèle ---
    if args.until == "selfcheck":
        selfcheck = run_selfcheck(args.question, claims, pipeline.llm_client)
        print(f"\n🔹 {len(selfcheck.samples)} ÉCHANTILLON(S) GÉNÉRÉ(S) :")
        for i, sample in enumerate(selfcheck.samples, 1):
            print(f"   {i}. {sample.strip()}")
        print(f"\n🔹 {len(selfcheck.scores)} SCORE(S) SELFCHECK :")
        for score in selfcheck.scores:
            print(f"   {score.claim_id} · divergence {score.divergence_score:.2f}")
        raise SystemExit

    if args.until == "rag":
        rag = pipeline.retriever.verify_claims(claims)
        print(f"\n🔹 {len(rag.verdicts)} VERDICT(S) RAG :")
        for verdict in rag.verdicts:
            print(f"   {verdict.claim_id} · {verdict.verdict} · confiance {verdict.confidence:.2f}")
        if rag.panne:
            print(f"\n⚠️ PANNE : {rag.panne}")
        raise SystemExit

    final_result = pipeline.run(args.question, answer=raw_answer)

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
                # Le RAG rend un RagJudgment, pas un Verdict : comparer aux membres de
                # Verdict ne pouvait jamais être vrai, et la ligne affichait donc
                # toujours « PAS ASSEZ D'INFOS ».
                rag_alert = {
                    RagJudgment.FEVER_CONFIRMS: "🟢 PROUVÉ VRAI (FEVER)",
                    RagJudgment.FEVER_REFUTES: "🔴 PROUVÉ FAUX (FEVER)",
                    RagJudgment.LIKELY_TRUE: "🟢 PROBABLEMENT VRAI",
                    RagJudgment.LIKELY_FALSE: "🔴 PROBABLEMENT FAUX",
                }.get(rag_verdict.verdict, "⚪ PAS ASSEZ D'INFOS")

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
