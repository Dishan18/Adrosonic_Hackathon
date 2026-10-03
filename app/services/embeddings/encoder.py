"""
Embedding service using sentence-transformers (bge-small-en-v1.5).
Runs locally on CPU. Cached singleton.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

_model = None
_model_name: Optional[str] = None


def get_embedding_model():
    global _model, _model_name
    from app.config import config
    target = config.EMBEDDING_MODEL

    if _model is not None and _model_name == target:
        return _model

    try:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model: %s", target)
        _model = SentenceTransformer(target)
        _model_name = target
        logger.info("Embedding model loaded.")
        return _model
    except Exception as e:
        logger.error("Failed to load embedding model: %s", e)
        return None


def embed_texts(texts: List[str]) -> Optional[np.ndarray]:
    """Embed a list of strings. Returns numpy array or None on failure."""
    model = get_embedding_model()
    if model is None:
        return None
    try:
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.array(embeddings)
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        return None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two unit-normalised vectors."""
    try:
        return float(np.dot(a, b))
    except Exception:
        return 0.0


def batch_similarity(query: np.ndarray, candidates: np.ndarray) -> List[float]:
    """Return cosine similarity of query against each candidate row."""
    try:
        return [float(np.dot(query, c)) for c in candidates]
    except Exception:
        return [0.0] * len(candidates)
