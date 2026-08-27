"""Vérification d'une affirmation par recherche de preuves dans l'index FEVER (RAG inversé)."""

import pickle
from pathlib import Path

import faiss
from sentence_transformers import SentenceTransformer

from berlue.core.schemas import Claim, Evidence, RagVerdict, Verdict
from berlue.params import RAG_EMBEDDING_MODEL, RAG_VECTOR_DB_PATH

# Labels FEVER (str du dataset) -> Verdict (enum du contrat interne berlue.core.schemas).
# "NOT ENOUGH INFO" n'apparaît jamais parmi les labels indexés (indexer.build_index ne
# garde que SUPPORTS/REFUTES) ; gardé ici pour les retours anticipés de verify_claim.
FEVER_LABEL_TO_VERDICT = {
    "SUPPORTS": Verdict.SUPPORTED,
    "REFUTES": Verdict.CONTRADICTED,
    "NOT ENOUGH INFO": Verdict.NOT_ENOUGH_INFO,
}


class RagRetriever:
    """Charge l'index FEVER (construit par `indexer.build_index`) et vérifie des affirmations."""

    def __init__(self, index_path: str = RAG_VECTOR_DB_PATH, embedding_model: str = RAG_EMBEDDING_MODEL):
        self.index_path = Path(index_path)

        # 1. Charger l'index FAISS
        self.index = faiss.read_index(str(self.index_path / "index.faiss"))

        # 2. Charger les métadonnées
        with open(self.index_path / "metadata.pkl", "rb") as f:
            self.metadata = pickle.load(f)

        # 3. Charger le modèle d'embedding
        self.model = SentenceTransformer(embedding_model)

        print(f"✅ Index chargé : {self.index.ntotal} vecteurs")
        print(f"✅ Métadonnées : {len(self.metadata['claims'])} exemples")

    def retrieve(self, claim: Claim, top_k: int = 5) -> list[dict]:
        """Recherche les `top_k` passages les plus proches de l'affirmation."""
        # ## Renvoie des dicts bruts (text/label/distance/evidence_url), pas des Evidence :
        # ## verify_claim (seul appelant, cf. grep) a besoin du label et de la distance de
        # ## chaque candidat pour son vote majoritaire, des champs que Evidence (le contrat de
        # ## core.schemas) n'a pas. Seule la preuve finalement citée devient une vraie Evidence.
        # 1. Générer l'embedding de l'affirmation
        claim_embedding = self.model.encode(claim.text, convert_to_numpy=True).reshape(1, -1)

        # 2. Recherche dans l'index
        distances, indices = self.index.search(claim_embedding, top_k)

        # 3. Construire les résultats
        evidences = []
        for i in range(len(distances[0])):
            dist = distances[0][i]
            idx = indices[0][i]
            if idx < len(self.metadata["claims"]):
                evidences.append(
                    {
                        "text": self.metadata["claims"][idx],
                        "label": self.metadata["labels"][idx],
                        "distance": float(dist),
                        "evidence_url": self.metadata["evidence_urls"][idx],
                    }
                )
        return evidences

    def verify_claim(self, claim: Claim) -> RagVerdict:
        """
        Vérifie une affirmation et retourne un verdict avec un score de confiance.

        Stratégie de scoring :
        - On récupère les 5 preuves les plus proches.
        - On compte le nombre de SUPPORTS vs REFUTES parmi les plus proches.
        - Score de confiance = proportion du label majoritaire / top_k.
        """
        evidences = self.retrieve(claim, top_k=5)

        # ## claim_id identifie l'affirmation évaluée pour l'appelant (fusion.py) ; evidence=None
        # ## car rien n'a été trouvé, il n'y a donc aucune preuve à citer.
        if not evidences:
            return RagVerdict(claim_id=claim.id, verdict=Verdict.NOT_ENOUGH_INFO, confidence=0.0, evidence=None)
        threshold = 0.2
        relevant = [ev for ev in evidences if ev["distance"] < threshold]

        # Si plus de preuves après filtrage, on continue avec celles-ci
        if relevant:
            evidences = relevant
        else:
            # Si toutes les preuves sont trop éloignées, on garde la plus proche
            # ou on retourne NOT ENOUGH INFO
            # ## evidences est une liste de dicts (retrieve() les construit ainsi, cf.
            # ## plus haut), pas d'objets à attributs : x["distance"], pas x.distance.
            closest = min(evidences, key=lambda x: x["distance"])
            if closest["distance"] < 1.0:  # seuil large de secours
                evidences = [closest]
            else:
                # ## Même chose ici : evidence=None plutôt que de citer une preuve trop éloignée
                # ## pour être pertinente.
                return RagVerdict(claim_id=claim.id, verdict=Verdict.NOT_ENOUGH_INFO, confidence=0.0, evidence=None)

        # Compter les labels
        label_counts = {"SUPPORTS": 0, "REFUTES": 0, "NOT ENOUGH INFO": 0}
        for ev in evidences:
            label_counts[ev["label"]] += 1

        # Déterminer le verdict majoritaire
        majority_label = max(label_counts, key=label_counts.get)

        # Score de confiance : proportion du label majoritaire
        confidence = label_counts[majority_label] / len(evidences)

        # Ajustement : si les preuves sont très éloignées, on baisse la confiance
        # (les distances sont en L2, normalisées par la dimension)
        avg_distance = sum(ev["distance"] for ev in evidences) / len(evidences)
        # Plus la distance est grande, plus on réduit la confiance
        distance_penalty = min(1.0, 1.0 / (1.0 + avg_distance / 10))
        confidence = confidence * distance_penalty

        # ## RagVerdict.evidence est singulier dans le contrat (cf. core/schemas.py) : on ne
        # ## cite que la preuve la plus proche parmi celles retenues.
        closest = min(evidences, key=lambda x: x["distance"])
        try:
            source = closest["evidence_url"][0][0][2]
        except IndexError, TypeError:
            source = "FEVER"
        evidence = Evidence(text=closest["text"], source=source, similarity_score=1.0 / (1.0 + closest["distance"]))

        # ## FEVER_LABEL_TO_VERDICT convertit le label FEVER (str) en Verdict (enum) attendu
        # ## par fusion.py — les deux vocabulaires ne partagent pas les mêmes valeurs.
        return RagVerdict(
            claim_id=claim.id,
            verdict=FEVER_LABEL_TO_VERDICT[majority_label],
            confidence=confidence,
            evidence=evidence,
        )
