"""Indexation du corpus FEVER en base vectorielle (FAISS par défaut). À lancer une
fois avant la démo, pas à chaque run de l'app."""

import json
import os
import pickle

import faiss
import requests
from sentence_transformers import SentenceTransformer

from berlue.params import EMBEDDING_MODEL, FEVER_DATA_PATH, VECTOR_DB_PATH


def build_index(
    fever_path: str = FEVER_DATA_PATH,
    out_path: str = VECTOR_DB_PATH,
    embedding_model: str = EMBEDDING_MODEL,
) -> None:
    """Construit l'index vectoriel du corpus FEVER et le sauvegarde sur disque."""

    print(f"📦 1. Chargement du modèle d'embedding : {embedding_model}...")
    model = SentenceTransformer(embedding_model)

    documents = []
    metadata = []

    print(f"📖 2. Lecture des données depuis : {fever_path}...")

    if fever_path.startswith("http://") or fever_path.startswith("https://"):
        print("   -> 🌐 URL détectée : téléchargement en cours...")
        response = requests.get(fever_path)
        response.raise_for_status()
        lignes = response.text.strip().split("\n")
    else:
        print("   -> 📁 Fichier local détecté.")
        with open(fever_path, encoding="utf-8") as f:
            lignes = f.readlines()

    print("   -> 🔨 Parsing des données...")
    for line in lignes:
        line = line.strip()
        if line:
            item = json.loads(line)
            claim_text = item.get("claim", "")

            if claim_text:
                documents.append(claim_text)
                metadata.append({"id": str(item.get("id", "")), "claim": claim_text, "label": item.get("label", "")})

    print(f"   -> {len(documents)} affirmations prêtes à être indexées.")

    print("🧠 3. Calcul des vecteurs (Embeddings)...")

    embeddings = model.encode(documents, show_progress_bar=True)

    print("🏗️ 4. Création de l'index FAISS...")
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)

    print(f"💾 5. Sauvegarde sur le disque dans {out_path}...")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    faiss.write_index(index, out_path)
    with open(out_path + ".meta", "wb") as f_meta:
        pickle.dump(metadata, f_meta)

    print("✅ Terminé ! Index prêt.")


if __name__ == "__main__":
    build_index()
