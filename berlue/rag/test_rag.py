"""Script de test pour valider le fonctionnement du RAG inversé sur FEVER."""

import json
from pathlib import Path

from berlue.core.schemas import Claim
from berlue.pipeline.hurlu_berlu import HurluBerlu

# ## FEVER_LABEL_TO_VERDICT : pour comparer le label attendu (string FEVER) au verdict
# ## retourné (enum Verdict), qui n'utilisent pas le même vocabulaire.
from berlue.rag.retriever import FEVER_LABEL_TO_VERDICT, RagRetriever


def load_sample_claims(fever_path: str, n_samples: int = 10) -> list[tuple[Claim, str]]:
    """Charge quelques exemples du dataset FEVER pour les tests."""
    samples = []
    fever_path = "data/fever/raw/fever.jsonl"
    with open(fever_path) as f:
        for i, line in enumerate(f):
            if i >= n_samples * 3:
                break
            if not line.strip():
                continue
            data = json.loads(line)
            if data.get("label") in ["SUPPORTS", "REFUTES"]:
                claim = Claim(id=i, text=data["claim"], source_answer=data["claim"])
                samples.append((claim, data["label"]))

    return samples[:n_samples]


def test_retriever():
    """Test principal du retriever."""
    print("=" * 60)
    print("🔍 TEST DU RAG RETRIEVER SUR FEVER")
    print("=" * 60)

    print("\n1️⃣ Initialisation du retriever...")
    # try:
    if 1:
        retriever = RagRetriever()
        print("✅ Retriever chargé avec succès")
    # except Exception as e:
    #     print(f"❌ Erreur lors du chargement : {e}")
    #     return

    print("\n2️⃣ Chargement des exemples de test...")
    fever_path = "data/fever/raw/fever.jsonl"

    if not Path(fever_path).exists():
        print(f"❌ Fichier {fever_path} introuvable")
        return

    samples = load_sample_claims(str(fever_path), n_samples=10)
    print(f"✅ {len(samples)} exemples chargés")

    print("\n3️⃣ Test des affirmations...\n")

    correct = 0
    for i, (claim, expected_label) in enumerate(samples, 1):
        print(f"--- Test #{i} ---")
        print(f"Affirmation : {claim.text[:80]}...")
        print(f"Label attendu : {expected_label}")

        try:
            verdict = retriever.verify_claim(claim)
            print(f"Verdict RAG : {verdict.verdict}")
            print(f"Confiance : {verdict.confidence:.2%}")

            # ## RagVerdict.evidence est une seule Evidence (contrat core.schemas), pas une liste.
            if verdict.evidence:
                ev = verdict.evidence
                print(f"Preuve citée ({ev.source}, score={ev.similarity_score:.3f}) : {ev.text[:60]}...")
            else:
                print("Aucune preuve citée.")

            # ## expected_label est une string FEVER, verdict.verdict un Verdict (enum) : on
            # ## passe par le même mapping que retriever.py pour comparer les deux.
            is_correct = verdict.verdict == FEVER_LABEL_TO_VERDICT[expected_label]
            status = "✅" if is_correct else "❌"
            print(f"Résultat : {status} {'Correct' if is_correct else 'Incorrect'}")
            if is_correct:
                correct += 1

        except Exception as e:
            print(f"❌ Erreur : {e}")

        print()

    print("=" * 60)
    print("📊 RÉSUMÉ DES TESTS")
    print("=" * 60)
    print(f"Exemples testés : {len(samples)}")
    print(f"Corrects : {correct}/{len(samples)}")
    print(f"Précision : {correct / len(samples):.2%}")
    print("=" * 60)


def test_retriever_with_llm(question: str = "Où est né Nikolaj Coster-Waldau ?"):
    """Test manuel : pose une question au LLM, extrait ses affirmations (HurluBerlu), les vérifie via le RAG."""
    print("=" * 60)
    print("🔍 TEST DU RAG RETRIEVER SUR UNE VRAIE RÉPONSE LLM")
    print("=" * 60)

    try:
        print("\n1️⃣ Génération de la réponse LLM...")
        pipeline = HurluBerlu()
        result = pipeline.generate_response(question)
        print(f"❓ Question : {question}")
        print(f"🤖 Réponse : {result.raw_answer}")

        print("\n2️⃣ Extraction des affirmations...")
        result = pipeline.extract_claims(result)
        print(f"✅ {len(result.claims)} affirmation(s) extraite(s)")

        print("\n3️⃣ Initialisation du retriever...")
        retriever = RagRetriever()

        print("\n4️⃣ Vérification RAG de chaque affirmation...\n")
        for i, claim in enumerate(result.claims, 1):
            print(f"--- Affirmation #{i} ---")
            print(f"Texte : {claim.text}")
            verdict = retriever.verify_claim(claim)
            print(f"Verdict RAG : {verdict.verdict}")
            print(f"Confiance : {verdict.confidence:.2%}")
            if verdict.evidence:
                ev = verdict.evidence
                print(f"Preuve citée ({ev.source}, score={ev.similarity_score:.3f}) : {ev.text[:60]}...")
            else:
                print("Aucune preuve citée.")
            print()

    except Exception as e:
        print(f"❌ Erreur : {e}")
        print("💡 Ollama doit tourner en local (`make ollama_setup` ou `ollama serve`).")


if __name__ == "__main__":
    test_retriever()
    test_retriever_with_llm()
