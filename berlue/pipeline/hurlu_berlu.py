import textwrap
import uuid

from berlue.core.schemas import Claim, PipelineResult
from berlue.llm.client import OllamaClient
from berlue.selfcheck.sampler import sample_responses
from berlue.selfcheck.scorer import compute_divergence


class HurluBerlu:
    """Pipeline principal sans état (Stateless) pour la vérification RAG."""

    def __init__(self, llm_client: OllamaClient | None = None):
        self.client = llm_client or OllamaClient()

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
    # TODO RAG results

    # ÉTAPE 6
    # TODO Fusionner scores Self Check et RAG


if __name__ == "__main__":
    import argparse

    # --until permet de lancer le pipeline étape par étape (cf. make/pipeline.mk
    # pipeline_generate/pipeline_extract/pipeline_samples/pipeline_selfcheck) —
    # pratique pour itérer sans attendre les étapes suivantes (SelfCheckGPT
    # notamment, qui refait K appels LLM).
    parser = argparse.ArgumentParser(description="Démo du pipeline HurluBerlu, étape par étape.")
    parser.add_argument(
        "--until",
        choices=["generate", "extract", "samples", "selfcheck"],
        default="selfcheck",
        help="S'arrête après cette étape (défaut : selfcheck, le pipeline complet disponible aujourd'hui).",
    )
    parser.add_argument("--question", default="Pourquoi l'eau mouille ?", help="Question posée au LLM.")
    args = parser.parse_args()

    print("🚀 Démarrage du pipeline HurluBerlu...")

    pipeline = HurluBerlu()

    print(f"\n❓ Question posée : {args.question}")

    # Le passage de relais
    result = pipeline.generate_response(args.question)
    if args.until == "generate":
        print(f"\n🔹 RÉPONSE BRUTE :\n{result.raw_answer}")
        raise SystemExit

    result = pipeline.extract_claims(result)
    if args.until == "extract":
        print(f"\n🔹 {len(result.claims)} AFFIRMATION(S) EXTRAITE(S) :")
        for i, claim in enumerate(result.claims, 1):
            print(f"   {i}. {claim.text}")
        raise SystemExit

    result = pipeline.generate_samples(result)
    if args.until == "samples":
        print(f"\n🔹 {len(result.samples)} ÉCHANTILLON(S) GÉNÉRÉ(S) :")
        for i, sample in enumerate(result.samples, 1):
            print(f"   {i}. {sample.strip()}")
        raise SystemExit

    final_result = pipeline.evaluate_selfcheck(result)

    # TODO : implémenter RAG
    # final_result = pipeline.evaluate_rag(final_result)
    # final_result = pipeline.fuse_results(final_result)

    print("\n✅ Traitement terminé ! Voici le bilan de l'évaluation :")
    print("=" * 60)
    print(f"🔹 QUESTION : {final_result.question}")
    print(f"🔹 RÉPONSE BRUTE :\n{final_result.raw_answer}")
    print("=" * 60)

    print(f"\n🔹 ANALYSE DES {len(final_result.claims)} AFFIRMATIONS (SelfCheckNLI) :")

    # On crée un dictionnaire pour retrouver le score de chaque claim par son ID
    scores_dict = {score.claim_id: score for score in final_result.selfcheck_scores}

    for i, claim in enumerate(final_result.claims, 1):
        print(f"\n   {i}. {claim.text}")

        # On récupère le score correspondant à ce claim
        score = scores_dict.get(claim.id)
        if score:
            # Affichage visuel du verdict NLI
            alert = "🔴 HALLUCINATION" if score.divergence_score > 0.5 else "🟢 COHÉRENT"
            print(f"      ↳ {alert} | Divergence : {score.divergence_score:.2f} | Confiance : {score.confidence:.2f}")
        else:
            print("      ↳ ⚠️ Aucun score calculé.")

    print("\n" + "=" * 60)
