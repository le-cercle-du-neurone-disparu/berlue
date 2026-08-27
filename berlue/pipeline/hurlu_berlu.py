import textwrap
import uuid

from berlue.core.schemas import Claim, PipelineResult
from berlue.llm.client import OllamaClient
from berlue.rag.retriever import RagRetriever
from berlue.selfcheck.sampler import sample_responses
from berlue.selfcheck.scorer import compute_divergence


class HurluBerlu:
    """Pipeline principal sans état (Stateless) pour la vérification RAG."""

    def __init__(self, llm_client: OllamaClient | None = None, retriever: RagRetriever | None = None):
        self.client = llm_client or OllamaClient()
        self.retriever = retriever or RagRetriever()

    def _do_llm_extraction(self, answer_text: str) -> list[Claim]:
        """Méthode privée : découpe une réponse en affirmations atomiques."""
        if not answer_text or not answer_text.strip():
            return []

        prompt = textwrap.dedent(f"""\
            Tu es un expert en analyse de données factuelles. Ta tâche est de décomposer
            le texte suivant en une liste d'affirmations courtes, atomiques et indépendantes.

            Règles strictes :
            1. Chaque affirmation ne doit contenir qu'une seule idée ou un fait.
            2. Chaque affirmation doit avoir du sens toute seule hors contexte
               (remplace les pronoms comme 'il', 'elle', 'ce' par le sujet explicite).
            3. Ne rajoute aucun texte avant ou après ta liste.
            4. Tu dois répondre UNIQUEMENT par une liste à puces (commençant par '- ').

            Texte à analyser :
            {answer_text}

            Affirmations :
        """)

        # Plus besoin de passer le client, on utilise self.client directement !
        raw_response = self.client.generate(prompt=prompt, temperature=0.0)

        claims = []
        for line in raw_response.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                claim_text = line[2:].strip()
                if claim_text:
                    claims.append(Claim(id=str(uuid.uuid4()), text=claim_text, source_answer=answer_text))

        return claims

    # ÉTAPE 1
    def generate_response(
        self, question: str, length_constraint: str = "Réponds de manière claire et concise, en 3 à 5 phrases maximum."
    ) -> PipelineResult:
        """Génère la réponse de base avec une limite de longueur."""

        full_prompt = f"{question}\n\n[Instruction : {length_constraint}]"

        answer = self.client.generate(prompt=full_prompt)

        return PipelineResult(question=question, raw_answer=answer)

    # ÉTAPE 2
    def extract_claims(self, result: PipelineResult) -> PipelineResult:

        result.claims = self._do_llm_extraction(result.raw_answer)

        return result

    # ÉTAPE 3
    def generate_samples(self, result: PipelineResult) -> PipelineResult:

        result.samples = sample_responses(question=result.question, client=self.client)
        return result

    # ÉTAPE 4
    def evaluate_selfcheck(self, result: PipelineResult) -> PipelineResult:

        print("   🧠 Calcul des scores de divergence SelfCheckNLI...")

        for claim in result.claims:
            score = compute_divergence(claim=claim, samples=result.samples)
            result.selfcheck_scores.append(score)

        return result

    # ÉTAPE 5
    def evaluate_rag(self, result: PipelineResult) -> PipelineResult:

        print("   🧠 Calcul des verdicts du RAG...")

        for claim in result.claims:
            verdict = self.retriever.verify_claim(claim=claim)
            result.rag_scores.append(verdict)

        return result

    # ÉTAPE 6
    # TODO Fusionner scores Self Check et RAG


if __name__ == "__main__":
    import argparse

    from berlue.core.schemas import Verdict

    parser = argparse.ArgumentParser(description="Démo du pipeline HurluBerlu, étape par étape.")
    parser.add_argument(
        "--until",
        choices=["generate", "extract", "samples", "selfcheck", "rag"],
        default="rag",  # Le défaut va jusqu'au bout
        help="S'arrête après cette étape (défaut : rag).",
    )
    parser.add_argument("--question", default="Pourquoi l'eau mouille ?", help="Question posée au LLM.")
    args = parser.parse_args()

    print("🚀 Démarrage du pipeline HurluBerlu...")
    pipeline = HurluBerlu()
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
    # Si on n'a PAS demandé de s'arrêter à selfcheck, on continue vers le RAG
    if args.until != "selfcheck":
        final_result = pipeline.evaluate_rag(final_result)

    # TODO : implémenter fusion
    # if args.until not in ["selfcheck", "rag"]:
    #     final_result = pipeline.fuse_results(final_result)

    # ==========================================
    # AFFICHAGE DU BILAN FINAL (SelfCheck + RAG)
    # ==========================================
    print("\n✅ Traitement terminé ! Voici le bilan de l'évaluation :")
    print("=" * 70)
    print(f"🔹 QUESTION : {final_result.question}")
    print(f"🔹 RÉPONSE BRUTE :\n{final_result.raw_answer}")
    print("=" * 70)

    print(f"\n🔹 ANALYSE DES {len(final_result.claims)} AFFIRMATIONS :")

    scores_dict = {score.claim_id: score for score in final_result.selfcheck_scores}
    rag_dict = {verdict.claim_id: verdict for verdict in final_result.rag_scores}

    for i, claim in enumerate(final_result.claims, 1):
        print(f"\n   {i}. {claim.text}")

        # 1. Affichage SelfCheck (toujours présent au stade du bilan)
        score = scores_dict.get(claim.id)
        if score:
            alert = "🔴 HALLUCINATION" if score.divergence_score > 0.5 else "🟢 COHÉRENT"
            print(f"      ↳ 🧠 [SelfCheck] : {alert} | Divergence : {score.divergence_score:.2f}")
        else:
            print("      ↳ 🧠 [SelfCheck] : ⚠️ Aucun score.")

        # 2. Affichage RAG (uniquement si la liste rag_scores n'est pas vide)
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

    print("\n" + "=" * 70)
