import os
from pathlib import Path

# Chemins
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"

# Données brutes
RAW_DIR = DATA_DIR / "raw"
FEVER_DATA_PATH = RAW_DIR / "fever.jsonl"

# Index vectoriel
INDEX_DIR = DATA_DIR / "index"
VECTOR_DB_PATH = INDEX_DIR / "fever_faiss"

# Modèles
EMBEDDING_MODEL = "all-mpnet-base-v2"
