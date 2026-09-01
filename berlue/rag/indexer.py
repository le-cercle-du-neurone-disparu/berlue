"""Indexation du corpus FEVER en base vectorielle (FAISS). À lancer une fois avant la démo."""

import json
import logging
import pickle
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

from berlue.params import FEVER_DATA_PATH, RAG_EMBEDDING_MODEL, RAG_VECTOR_DB_PATH

logger = logging.getLogger(__name__)


def load_fever_data(fever_path: str) -> pd.DataFrame:
    """Charge le dataset FEVER depuis un fichier JSONL."""
    data = []
    with open(fever_path) as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    df = pd.DataFrame(data)
    logger.info("✅ Chargé %d exemples depuis %s", len(df), fever_path)
    return df


def build_index(
    fever_path: str = FEVER_DATA_PATH,
    out_path: str = RAG_VECTOR_DB_PATH,
    embedding_model: str = RAG_EMBEDDING_MODEL,
    batch_size: int = 32,
) -> None:
    """Construit l'index vectoriel du corpus FEVER et le sauvegarde sur disque."""
    # 1. Charger les données
    df = load_fever_data(fever_path)

    # 2. Filtrer : ne garder que les exemples avec preuves
    filtered = df[df["label"].isin(["SUPPORTS", "REFUTES"]) & (df["id"] != -1)]
    logger.info("🔍 %d exemples avec preuves conservés", len(filtered))

    # 3. Charger le modèle d'embedding
    model = SentenceTransformer(embedding_model)
    logger.info("🤖 Modèle d'embedding : %s", embedding_model)

    # 4. Générer les embeddings en batch
    claims = filtered["claim"].tolist()
    labels = filtered["label"].tolist()
    evidence_ids = filtered["id"].tolist()
    evidence_urls = filtered["evidence"].tolist()

    embeddings = []
    for i in tqdm(range(0, len(claims), batch_size), desc="Génération des embeddings"):
        batch = claims[i : i + batch_size]
        emb = model.encode(batch, convert_to_numpy=True)
        embeddings.append(emb)

    embeddings = np.vstack(embeddings)
    logger.info("📊 Embeddings générés : %s", embeddings.shape)

    # 5. Créer l'index FAISS
    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embeddings)
    logger.info("📁 Index FAISS créé avec %d vecteurs", index.ntotal)

    # 6. Sauvegarder l'index et les métadonnées
    out_path = Path(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    faiss.write_index(index, str(out_path / "index.faiss"))

    metadata = {
        "claims": claims,
        "labels": labels,
        "evidence_ids": evidence_ids,
        "evidence_urls": evidence_urls,
    }
    with open(out_path / "metadata.pkl", "wb") as f:
        pickle.dump(metadata, f)

    logger.info("✅ Index sauvegardé dans %s", out_path)


if __name__ == "__main__":
    build_index()
