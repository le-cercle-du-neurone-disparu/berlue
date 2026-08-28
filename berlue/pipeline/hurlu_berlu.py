import textwrap
import uuid

from berlue.core.schemas import Claim, FusedVerdict, PipelineResult, Verdict
from berlue.llm.client import OllamaClient
from berlue.rag.retriever import RagRetriever
from berlue.selfcheck.sampler import sample_responses
from berlue.selfcheck.scorer import compute_divergence


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
        self.llm_extract = llm_extract or OllamaClient()

        self.retriever = retriever or RagRetriever()

    def _do_llm_extraction(self, answer_text: str) -> list[Claim]:
        """Méthode privée : découpe une réponse en affirmations atomiques."""
        if not answer_text or not answer_text.strip():
            return []

        prompt = textwrap.dedent(f"""\
            Tu es un expert en analyse de données factuelles. Ta tâche est de décomposer
            le texte suivant en une liste d'assertions courtes, atomiques et indépendantes.

            Règles strictes :
            1. Chaque assertion ne doit contenir qu'une seule idée ou un fait.
            2. Chaque assertion doit avoir du sens toute seule hors contexte
               (remplace les pronoms comme 'il', 'elle', 'ce' par le sujet explicite).
            3. Ne rajoute aucun texte avant ou après ta liste.
            4. Tu dois répondre UNIQUEMENT par une liste à puces (commençant par '- ').

            Ne te sens pas obligé de produire pluisuers assertions s'il n'y en a qu'une dans le texte à analyser.

            Texte à analyser :
            {answer_text}

            Affirmations :
        """)

        raw_response = self.llm_client.generate(prompt=prompt, temperature=0.0)

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

        answer = self.llm_client.generate(prompt=full_prompt)

        return PipelineResult(question=question, raw_answer=answer)

    # ÉTAPE 2
    def extract_claims(self, result: PipelineResult) -> PipelineResult:

        result.claims = self._do_llm_extraction(result.raw_answer)

        return result

    # ÉTAPE 3
    def generate_samples(self, result: PipelineResult) -> PipelineResult:

        result.samples = sample_responses(question=result.question, client=self.llm_client)
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
    def fuse_results(
        self, result: PipelineResult, weight_rag: float = 0.7, weight_selfcheck: float = 0.3
    ) -> PipelineResult:
        """
        Dernière étape : combine les scores RAG et SelfCheckGPT pour statuer sur chaque affirmation.
        Utilise le pattern Passe-Plat.
        """
        print("\n🧬 [Fusion] Début de la synthèse des résultats...")

        # Pour retrouver les résultats en O(1) sans faire des boucles imbriquées
        rag_dict = {v.claim_id: v for v in result.rag_scores}
        sc_dict = {s.claim_id: s for s in result.selfcheck_scores}

        for claim in result.claims:
            rag = rag_dict.get(claim.id)
            sc = sc_dict.get(claim.id)

            # 1. Calcul de la cohérence interne (l'inverse de la divergence)
            # Si le score de divergence est 0.1, la cohérence est 0.9 (très sûr)
            coherence = 1.0 - sc.divergence_score if sc else 0.5

            # 2. Application de l'arbre de décision
            if rag and rag.verdict != Verdict.NOT_ENOUGH_INFO:
                # CAS A : Le RAG a trouvé une preuve tranchée dans la base de données
                final_verdict = rag.verdict

                # Le score est un mix : le RAG pèse 70%, la certitude du LLM pèse 30%
                final_conf = (rag.confidence * weight_rag) + (coherence * weight_selfcheck)

                if final_verdict == Verdict.SUPPORTED:
                    explanation = "L'affirmation est factuellement prouvée par la base de données."
                else:
                    explanation = "L'affirmation est formellement contredite par la base de données."

                evidence = rag.evidence

            else:
                # CAS B : Le RAG n'a rien trouvé. On s'en remet au comportement du LLM.
                if coherence < 0.5:
                    # Le LLM s'est contredit dans les samples. C'est une hallucination !
                    final_verdict = Verdict.CONTRADICTED
                    final_conf = 1.0 - coherence  # Plus il est incohérent, plus on est sûr que c'est faux
                    explanation = "Hallucination probable détectée : le LLM s'est contredit lui-même."
                else:
                    # Le LLM est sûr de lui, mais on n'a pas de preuve.
                    final_verdict = Verdict.NOT_ENOUGH_INFO
                    final_conf = coherence
                    explanation = "L'affirmation semble cohérente, mais manque de sources dans la base."

                evidence = None

            # Petite sécurité pour être sûr que la confiance reste entre 0.0 et 1.0
            final_conf = min(max(final_conf, 0.0), 1.0)

            # 3. Création de l'objet final
            fused = FusedVerdict(
                claim_id=claim.id,
                claim_text=claim.text,
                verdict=final_verdict,
                confidence=final_conf,
                evidence=evidence,
                explanation=explanation,
            )
            result.fused_verdicts.append(fused)

        return result


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
