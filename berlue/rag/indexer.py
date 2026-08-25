"""Indexation du corpus FEVER en base vectorielle (FAISS par défaut). À lancer une
fois avant la démo, pas à chaque run de l'app."""

from berlue.params import EMBEDDING_MODEL, FEVER_DATA_PATH, VECTOR_DB_PATH


def build_index(
    fever_path: str = FEVER_DATA_PATH,
    out_path: str = VECTOR_DB_PATH,
    embedding_model: str = EMBEDDING_MODEL,
) -> None:
    """Construit l'index vectoriel du corpus FEVER et le sauvegarde sur disque."""
    # TODO(rag)
    raise NotImplementedError


if __name__ == "__main__":
    build_index()
