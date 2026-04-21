import numpy as np
from sentence_transformers import SentenceTransformer
import config

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"  Loading SciNCL model '{config.SCINCL_MODEL}' …")
        _model = SentenceTransformer(
            config.SCINCL_MODEL,
            cache_folder=config.SCINCL_CACHE_DIR,
        )
        print("  Model ready.")
    return _model


def encode(texts: list[str]) -> np.ndarray:
    """
    Encode a list of strings → (N, 768) float32 array.
    Embeddings are L2-normalised so cosine similarity == dot product.
    """
    if not texts:
        return np.empty((0, 768), dtype=np.float32)
    return get_model().encode(
        texts,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype(np.float32)
