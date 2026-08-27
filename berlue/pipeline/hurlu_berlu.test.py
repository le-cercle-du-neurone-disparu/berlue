import textwrap
import uuid

from berlue.core.schemas import Claim, FusedVerdict, PipelineResult, Verdict
from berlue.llm.client import OllamaClient
from berlue.rag.hurlu_berlu_rag import RagVerifier
from berlue.selfcheck.sampler import sample_responses
from berlue.selfcheck.scorer import compute_divergence


class HurluBerlu:
    """Pipeline principal sans état (Stateless) pour la vérification RAG."""

    def __init__(self, llm_client: OllamaClient | None = None, rag_verifier: RagVerifier | None = None):
        self.client = llm_client or OllamaClient()
        self.rag_verifier = rag_verifier or RagVerifier()

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
        """Évalue les affirmations contre le corpus RAG."""
        print("📚 Évaluation RAG des affirmations...")

        rag_results = self.rag_verifier.verify_claims(result.claims)
        result.rag_scores = rag_results

        return result

    # ÉTAPE 6
    def fuse_results(self, result: PipelineResult) -> PipelineResult:
        """Fusionne les scores SelfCheck et RAG."""
        print("🔄 Fusion des résultats SelfCheck et RAG...")

        rag_dict = {score.claim_id: score for score in result.rag_scores}
        selfcheck_dict = {score.claim_id: score for score in result.selfcheck_scores}

        for claim in result.claims:
            rag_score = rag_dict.get(claim.id)
            selfcheck_score = selfcheck_dict.get(claim.id)

            if not rag_score or not selfcheck_score:
                fused = FusedVerdict(
                    claim_id=claim.id,
                    claim_text=claim.text,
                    verdict=Verdict.NOT_ENOUGH_INFO,
                    confidence=0.5,
                    evidence=rag_score.evidence if rag_score else None,
                    explanation="⚠️ Informations insuffisantes pour une évaluation complète."
                )
                result.fused_verdicts.append(fused)
                continue

            rag_weight = 0.6
            selfcheck_weight = 0.4

            if rag_score.verdict == Verdict.SUPPORTED and selfcheck_score.divergence_score < 0.3:
                verdict = Verdict.SUPPORTED
                confidence = (rag_score.confidence * rag_weight +
                             (1 - selfcheck_score.divergence_score) * selfcheck_weight)
                explanation = "✅ Affirmation cohérente avec les documents et stable entre les échantillons."

            elif rag_score.verdict == Verdict.CONTRADICTED or selfcheck_score.divergence_score > 0.7:
                verdict = Verdict.CONTRADICTED
                confidence = (rag_score.confidence * rag_weight +
                             selfcheck_score.divergence_score * selfcheck_weight)

                if rag_score.verdict == Verdict.CONTRADICTED and selfcheck_score.divergence_score > 0.7:
                    explanation = "❌ Contradiction dans les documents ET incohérence entre les échantillons."
                elif rag_score.verdict == Verdict.CONTRADICTED:
                    explanation = "❌ Contradiction détectée dans les documents."
                else:
                    explanation = "❌ Incohérence majeure entre les échantillons SelfCheck."

            else:
                verdict = Verdict.NOT_ENOUGH_INFO
                confidence = 0.5

                if rag_score.verdict == Verdict.SUPPORTED:
                    explanation = "⚠️ RAG confirme mais SelfCheck est incertain."
                elif rag_score.verdict == Verdict.CONTRADICTED:
                    explanation = "⚠️ RAG contredit mais SelfCheck est incertain."
                else:
                    explanation = "⚠️ Informations insuffisantes pour déterminer la véracité."

            fused = FusedVerdict(
                claim_id=claim.id,
                claim_text=claim.text,
                verdict=verdict,
                confidence=min(confidence, 1.0),
                evidence=rag_score.evidence,
                explanation=explanation
            )

            result.fused_verdicts.append(fused)

        return result

    # Méthode utilitaire pour exécuter tout le pipeline en une fois
    def run_full_pipeline(self, question: str) -> PipelineResult:
        """Exécute toutes les étapes du pipeline en séquence."""
        result = self.generate_response(question)
        result = self.extract_claims(result)
        result = self.generate_samples(result)
        result = self.evaluate_selfcheck(result)
        result = self.evaluate_rag(result)
        result = self.fuse_results(result)
        return result


if __name__ == "__main__":
    print("🚀 Démarrage du pipeline HurluBerlu...")

    pipeline = HurluBerlu()

    question_test = "Pourquoi l'eau mouille ?"
    print(f"\n❓ Question posée : {question_test}")

    # Version simplifiée avec run_full_pipeline
    final_result = pipeline.run_full_pipeline(question_test)

    print("\n✅ Traitement terminé ! Voici le bilan de l'évaluation :")
    print("=" * 60)
    print(f"🔹 QUESTION : {final_result.question}")
    print(f"🔹 RÉPONSE BRUTE :\n{final_result.raw_answer}")
    print("=" * 60)

    print(f"\n🔹 ANALYSE DES {len(final_result.claims)} AFFIRMATIONS :")

    # Dictionnaires pour retrouver les scores
    selfcheck_dict = {score.claim_id: score for score in final_result.selfcheck_scores}
    rag_dict = {score.claim_id: score for score in final_result.rag_scores}
    fused_dict = {verdict.claim_id: verdict for verdict in final_result.fused_verdicts}

    for i, claim in enumerate(final_result.claims, 1):
        print(f"\n   {i}. {claim.text}")

        # SelfCheck
        selfcheck_score = selfcheck_dict.get(claim.id)
        if selfcheck_score:
            alert = "🔴 HALLUCINATION" if selfcheck_score.divergence_score > 0.5 else "🟢 COHÉRENT"
            print(f"      ↳ SelfCheck: {alert} | Divergence: {selfcheck_score.divergence_score:.2f}")

        # RAG
        rag_score = rag_dict.get(claim.id)
        if rag_score:
            # Déterminer l'emoji pour le verdict RAG
            if rag_score.verdict == Verdict.SUPPORTED:
                rag_emoji = "✅"
            elif rag_score.verdict == Verdict.CONTRADICTED:
                rag_emoji = "❌"
            else:
                rag_emoji = "⚠️"

            print(f"      ↳ RAG: {rag_emoji} {rag_score.verdict.value} | "
                  f"Confiance: {rag_score.confidence:.2f}")

            if rag_score.evidence:
                print(f"      ↳ Preuve: \"{rag_score.evidence.text[:80]}...\"")
                print(f"      ↳ Source: {rag_score.evidence.source}")

        # Verdict Fusionné
        fused = fused_dict.get(claim.id)
        if fused:
            # Déterminer l'emoji pour le verdict fusionné
            if fused.verdict == Verdict.SUPPORTED:
                fused_emoji = "✅"
            elif fused.verdict == Verdict.CONTRADICTED:
                fused_emoji = "❌"
            else:
                fused_emoji = "⚠️"

            print(f"      ↳ {fused_emoji} VERDICT FINAL: {fused.verdict.value} "
                  f"(confiance: {fused.confidence:.2f})")
            print(f"      ↳ {fused.explanation}")

    print("\n" + "=" * 60)