"""Vérification d'une affirmation par recherche de preuves dans l'index FEVER (RAG inversé)."""

import pickle

import faiss
from sentence_transformers import SentenceTransformer

from berlue.core.schemas import Claim, Evidence, RagVerdict, Verdict
from berlue.params import EMBEDDING_MODEL, VECTOR_DB_PATH


class RagRetriever:
    """Charge l'index FEVER (construit par `indexer.build_index`) et vérifie des affirmations."""

    def __init__(self, index_path: str = VECTOR_DB_PATH):
        self.index_path = index_path

        print("🔍 [RagRetriever] Chargement du modèle de langage...")
        self.model = SentenceTransformer(EMBEDDING_MODEL)

        print(f"🔍 [RagRetriever] Chargement de l'index FAISS depuis {index_path}...")
        self.index = faiss.read_index(index_path)

        print("🔍 [RagRetriever] Chargement des métadonnées...")
        with open(index_path + ".meta", "rb") as f_meta:
            self.metadata = pickle.load(f_meta)

        print("✅ [RagRetriever] Prêt !")

    def retrieve(self, claim: Claim, top_k: int = 5) -> list[Evidence]:
        """Recherche les `top_k` passages les plus proches de l'affirmation."""

        # 1. On transforme le texte du Claim en vecteur mathématique (1, dimension)
        claim_vector = self.model.encode([claim.text])

        # 2. FAISS cherche les voisins les plus proches
        # distances : la distance L2 (plus c'est proche de 0, plus ça se ressemble)
        # indices : la position dans la liste de métadonnées
        distances, indices = self.index.search(claim_vector, top_k)

        evidences = []
        for dist, idx in zip(distances[0], indices[0], strict=True):
            if idx == -1:  # FAISS renvoie -1 s'il n'y a pas assez de résultats
                continue

            doc_meta = self.metadata[idx]

            # On convertit la distance L2 en un "score de similarité"
            score = 1.0 / (1.0 + float(dist))

            evidence = Evidence(
                text=doc_meta["claim"],
                source=f"FEVER_ID: {doc_meta['id']}",  # On utilise 'source' pour stocker l'origine
                similarity_score=score,
            )

            evidence._fever_label = doc_meta["label"]

            evidences.append(evidence)

        return evidences

    def verify_claim(self, claim: Claim) -> RagVerdict:
        """Vérifie une affirmation et retourne un verdict avec un score de confiance."""

        evidences = self.retrieve(claim, top_k=1)

        if not evidences:
            return RagVerdict(claim_id=claim.id, verdict=Verdict.NOT_ENOUGH_INFO, confidence=0.0, evidence=None)

        best_evidence = evidences[0]

        # LOGIQUE DU RAG INVERSÉ : on mappe les labels FEVER sur le strEnum 'Verdict'
        if best_evidence.similarity_score > 0.6:
            fever_label = str(best_evidence._fever_label).upper()

            if fever_label == "SUPPORTS":
                final_verdict = Verdict.SUPPORTED
            elif fever_label == "REFUTES":
                final_verdict = Verdict.CONTRADICTED
            else:
                final_verdict = Verdict.NOT_ENOUGH_INFO

            confidence = best_evidence.similarity_score
        else:
            # Si le texte est trop éloigné, on n'a pas assez d'infos pour juger
            final_verdict = Verdict.NOT_ENOUGH_INFO
            confidence = 0.0

        return RagVerdict(claim_id=claim.id, verdict=final_verdict, confidence=confidence, evidence=best_evidence)
