"""Script de test pour valider le fonctionnement du RAG inversé sur FEVER."""

import json
from pathlib import Path

from berlue.core.schemas import Claim
from berlue.rag.retriever import RagRetriever
from berlue.params import FEVER_DATA_PATH


def load_sample_claims(fever_path: str, n_samples: int = 100) -> list[tuple[Claim, str]]:
    """Charge quelques exemples du dataset FEVER pour les tests."""
    samples = []
    fever_path = "data/raw/fever.jsonl"
    with open(fever_path, "r") as f:
        for i, line in enumerate(f):
            if i >= n_samples * 3:
                break
            if not line.strip():
                continue
            data = json.loads(line)
            if data.get("label") in ["SUPPORTS", "REFUTES"]:
                claim = Claim(text=data["claim"], source_sentence=data["claim"])
                samples.append((claim, data["label"]))

    return samples[:n_samples]


def test_retriever():
    """Test principal du retriever."""
    print("=" * 60)
    print("🔍 TEST DU RAG RETRIEVER SUR FEVER")
    print("=" * 60)

    print("\n1️⃣ Initialisation du retriever...")
    try:
        retriever = RagRetriever()
        print("✅ Retriever chargé avec succès")
    except Exception as e:
        print(f"❌ Erreur lors du chargement : {e}")
        return

    print("\n2️⃣ Chargement des exemples de test...")
    fever_path = "data/raw/fever.jsonl"

    if not Path(fever_path).exists():
        print(f"❌ Fichier {fever_path} introuvable")
        return

    samples = load_sample_claims(str(fever_path), n_samples=100)
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

            print("Preuves trouvées :")
            for j, ev in enumerate(verdict.evidences[:3], 1):
                print(f"  {j}. {ev.label} (dist={ev.distance:.3f}) : {ev.text[:60]}...")

            is_correct = (verdict.verdict == expected_label)
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
    print(f"Précision : {correct/len(samples):.2%}")
    print("=" * 60)


if __name__ == "__main__":
    test_retriever()
