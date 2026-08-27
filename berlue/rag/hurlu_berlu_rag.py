"""
Module RAG pour la vérification documentaire des affirmations.
Utilise un corpus de documents (ex: Wikipedia FEVER) pour valider ou contredire les affirmations.
"""

import json
from dataclasses import dataclass

import numpy as np
from sentence_transformers import SentenceTransformer

from berlue.core.schemas import Claim, Evidence, RagVerdict, Verdict


@dataclass
class Document:
    """Structure de base pour un document du corpus."""

    id: str
    title: str
    text: str
    embedding: np.ndarray | None = None


class CorpusManager:
    """
    Gestionnaire du corpus de documents pour la recherche RAG.
    Charge les documents depuis un fichier et gère leurs embeddings.
    """

    def __init__(self, corpus_path: str = None, embedding_model: str = "all-MiniLM-L6-v2"):
        """
        Initialise le gestionnaire de corpus.

        Args:
            corpus_path: Chemin vers le fichier JSON contenant les documents
            embedding_model: Nom du modèle SentenceTransformer à utiliser
        """
        self.documents: list[Document] = []
        self.embedding_model = None

        if corpus_path is None:
            corpus_path = self._create_fake_corpus()

        self.corpus_path = corpus_path
        self._load_corpus()
        self._init_embedding_model()
        self._compute_embeddings()

    def _create_fake_corpus(self) -> str:
        """Crée un corpus factice pour les tests."""
        fake_corpus = [
            {
                "id": "doc_1",
                "title": "L'eau et ses propriétés",
                "text": (
                    "L'eau mouille parce que ses molécules sont polaires. "
                    "La polarité de l'eau lui permet de former des liaisons "
                    "hydrogène avec d'autres molécules."
                ),
            },
            {
                "id": "doc_2",
                "title": "Physique de l'eau",
                "text": (
                    "L'adhésion et la cohésion sont les deux propriétés "
                    "qui expliquent pourquoi l'eau mouille. L'eau a une "
                    "tension superficielle élevée."
                ),
            },
            {
                "id": "doc_3",
                "title": "Propriétés chimiques de l'eau",
                "text": (
                    "La molécule d'eau est composée de deux atomes "
                    "d'hydrogène et d'un atome d'oxygène. Sa polarité "
                    "crée des forces d'attraction."
                ),
            },
        ]

        fake_path = "test_corpus.json"
        with open(fake_path, "w", encoding="utf-8") as f:
            json.dump(fake_corpus, f)

        return fake_path

    def _load_corpus(self):
        """Charge le corpus depuis le fichier JSON."""
        try:
            with open(self.corpus_path, encoding="utf-8") as f:
                data = json.load(f)

            self.documents = [
                Document(id=doc.get("id", str(i)), title=doc.get("title", "Document inconnu"), text=doc.get("text", ""))
                for i, doc in enumerate(data)
            ]

            print(f"📚 Corpus chargé : {len(self.documents)} documents.")

        except FileNotFoundError:
            print(f"⚠️ Fichier {self.corpus_path} introuvable, création d'un corpus factice...")
            self.corpus_path = self._create_fake_corpus()
            self._load_corpus()

    def _init_embedding_model(self):
        """Initialise le modèle d'embedding pour la recherche sémantique."""
        print("⏳ Chargement du modèle d'embedding...")
        self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        print("✅ Modèle d'embedding chargé.")

    def _compute_embeddings(self):
        """Calcule les embeddings de tous les documents."""
        if not self.documents:
            return

        texts = [doc.text for doc in self.documents]
        embeddings = self.embedding_model.encode(texts, convert_to_numpy=True)

        for doc, emb in zip(self.documents, embeddings, strict=False):
            doc.embedding = emb

        self.embedding_matrix = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

    def search(self, query: str, top_k: int = 3) -> list[tuple[Document, float]]:
        """
        Recherche les documents les plus similaires à la requête.

        Args:
            query: La requête de recherche
            top_k: Nombre de résultats à retourner

        Returns:
            Liste de tuples (Document, score_similarité)
        """
        if not self.documents or self.embedding_model is None:
            return []

        query_embedding = self.embedding_model.encode(query, convert_to_numpy=True)
        query_embedding = query_embedding / np.linalg.norm(query_embedding)

        similarities = np.dot(self.embedding_matrix, query_embedding)

        top_indices = similarities.argsort()[-top_k:][::-1]

        results = []
        for idx in top_indices:
            if similarities[idx] > 0.1:  # Seuil minimum de similarité
                results.append((self.documents[idx], float(similarities[idx])))

        return results


class RagVerifier:
    """
    Vérificateur RAG qui évalue les affirmations contre un corpus de documents.
    """

    def __init__(self, corpus_manager: CorpusManager = None):
        """
        Initialise le vérificateur RAG.

        Args:
            corpus_manager: Gestionnaire de corpus à utiliser
        """
        self.corpus_manager = corpus_manager or CorpusManager()

        self.similarity_threshold = {"supported": 0.7, "contradicted": 0.6, "not_enough_info": 0.0}

    def _retrieve_evidence(self, claim: Claim, top_k: int = 3) -> list[Evidence]:
        """
        Récupère les preuves pertinentes pour une affirmation.

        Args:
            claim: L'affirmation à vérifier
            top_k: Nombre de preuves à récupérer

        Returns:
            Liste d'objets Evidence
        """
        search_results = self.corpus_manager.search(claim.text, top_k=top_k)

        evidence_list = []
        for doc, score in search_results:
            if score > 0.1:
                evidence = Evidence(text=doc.text, source=doc.title, similarity_score=score)
                evidence_list.append(evidence)

        return evidence_list

    def _determine_verdict(self, claim: Claim, evidence_list: list[Evidence]) -> tuple[Verdict, float]:
        """
        Détermine le verdict basé sur les preuves récupérées.

        Args:
            claim: L'affirmation à vérifier
            evidence_list: Liste des preuves récupérées

        Returns:
            Tuple (Verdict, confiance)
        """
        if not evidence_list:
            return Verdict.NOT_ENOUGH_INFO, 0.5

        best_evidence = max(evidence_list, key=lambda e: e.similarity_score)

        if best_evidence.similarity_score >= self.similarity_threshold["supported"]:
            return Verdict.SUPPORTED, best_evidence.similarity_score

        if best_evidence.similarity_score >= self.similarity_threshold["contradicted"]:
            contradiction_likelihood = 0.8
            return Verdict.CONTRADICTED, contradiction_likelihood

        return Verdict.NOT_ENOUGH_INFO, best_evidence.similarity_score

    def verify_claim(self, claim: Claim, top_k: int = 3) -> RagVerdict:
        """
        Vérifie une seule affirmation.

        Args:
            claim: L'affirmation à vérifier
            top_k: Nombre de preuves à récupérer

        Returns:
            Un objet RagVerdict
        """
        evidence_list = self._retrieve_evidence(claim, top_k)

        verdict, confidence = self._determine_verdict(claim, evidence_list)

        best_evidence = evidence_list[0] if evidence_list else None

        return RagVerdict(claim_id=claim.id, verdict=verdict, confidence=confidence, evidence=best_evidence)

    def verify_claims(self, claims: list[Claim]) -> list[RagVerdict]:
        """
        Vérifie une liste d'affirmations.

        Args:
            claims: Liste des affirmations à vérifier

        Returns:
            Liste d'objets RagVerdict
        """
        print(f"🔍 Vérification RAG de {len(claims)} affirmations...")

        results = []
        for i, claim in enumerate(claims, 1):
            print(f"   - Vérification de l'affirmation {i}/{len(claims)}...")
            result = self.verify_claim(claim)
            results.append(result)

        return results


class EnhancedRagVerifier(RagVerifier):
    """
    Version améliorée du vérificateur RAG avec analyse de contradiction.
    """

    def __init__(self, corpus_manager: CorpusManager = None, llm_client=None):
        """
        Initialise le vérificateur RAG amélioré.

        Args:
            corpus_manager: Gestionnaire de corpus
            llm_client: Client LLM pour l'analyse approfondie
        """
        super().__init__(corpus_manager)
        self.llm_client = llm_client

    def _analyze_contradiction(self, claim: Claim, evidence: Evidence) -> tuple[Verdict, float]:
        """
        Analyse approfondie des contradictions avec le LLM.

        Args:
            claim: L'affirmation
            evidence: La preuve

        Returns:
            Tuple (Verdict, confiance)
        """
        if self.llm_client is None:
            return super()._determine_verdict(claim, [evidence])

        prompt = f"""
        Analyse la relation entre l'affirmation suivante et la preuve fournie.

        Affirmation: "{claim.text}"

        Preuve: "{evidence.text}"

        Détermine si la preuve SUPPORTE, CONTREDIT ou ne fournit pas assez
        d'information (NOT_ENOUGH_INFO) sur l'affirmation.

        Réponds UNIQUEMENT au format: VERDICT|CONFIANCE
        où VERDICT est "supported", "contradicted" ou "not_enough_info"
        et CONFIANCE est un nombre entre 0 et 1.

        Exemple: "supported|0.85"
        """

        try:
            response = self.llm_client.generate(prompt, temperature=0.0)

            parts = response.strip().split("|")
            if len(parts) == 2:
                verdict_str, confidence_str = parts
                verdict = Verdict(verdict_str.strip().lower())
                confidence = float(confidence_str.strip())
                return verdict, confidence

        except Exception as e:
            print(f"⚠️ Erreur lors de l'analyse LLM: {e}")

        return super()._determine_verdict(claim, [evidence])

    def verify_claim(self, claim: Claim, top_k: int = 3) -> RagVerdict:
        """
        Vérifie une affirmation avec analyse avancée.
        """
        evidence_list = self._retrieve_evidence(claim, top_k)

        if not evidence_list:
            return RagVerdict(claim_id=claim.id, verdict=Verdict.NOT_ENOUGH_INFO, confidence=0.5, evidence=None)

        best_evidence = evidence_list[0]

        if self.llm_client is not None:
            verdict, confidence = self._analyze_contradiction(claim, best_evidence)
        else:
            verdict, confidence = self._determine_verdict(claim, evidence_list)

        return RagVerdict(claim_id=claim.id, verdict=verdict, confidence=confidence, evidence=best_evidence)


if __name__ == "__main__":
    print("🧪 Test du module RAG...")

    corpus = CorpusManager()

    verifier = RagVerifier(corpus)

    test_claim = Claim(
        id="test_1",
        text="L'eau mouille à cause de sa polarité",
        source_answer="L'eau mouille parce que ses molécules sont polaires.",
    )

    result = verifier.verify_claim(test_claim)

    print("\n📊 Résultat du test:")
    print(f"   - Affirmation: {test_claim.text}")
    print(f"   - Verdict: {result.verdict}")
    print(f"   - Confiance: {result.confidence:.2f}")
    if result.evidence:
        print(f"   - Preuve: {result.evidence.text}")
        print(f"   - Source: {result.evidence.source}")
    else:
        print("   - Preuve: Aucune")
