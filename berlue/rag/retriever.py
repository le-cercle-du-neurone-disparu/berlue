"""Vérification d'une affirmation par recherche de preuves dans l'index FEVER (RAG inversé)."""

from berlue.core.schemas import Claim, Evidence, RagVerdict
from berlue.params import VECTOR_DB_PATH


class RagRetriever:
    """Charge l'index FEVER (construit par `indexer.build_index`) et vérifie des affirmations."""

    def __init__(self, index_path: str = VECTOR_DB_PATH):
        self.index_path = index_path
        # TODO(rag)
        raise NotImplementedError

    def retrieve(self, claim: Claim, top_k: int = 5) -> list[Evidence]:
        """Recherche les `top_k` passages les plus proches de l'affirmation."""
        # TODO(rag)
        raise NotImplementedError

    def verify_claim(self, claim: Claim) -> RagVerdict:
        """Vérifie une affirmation et retourne un verdict avec un score de confiance."""
        # TODO(rag)
        raise NotImplementedError
