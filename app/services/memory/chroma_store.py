"""
ChromaDB persistent vector memory for approved column mappings.
Only human-approved mappings are stored.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection

    try:
        import chromadb
        from app.config import config

        _client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_DIR)
        _collection = _client.get_or_create_collection(
            name=config.CHROMA_COLLECTION,
            metadata={"description": "Approved SOV column mappings"},
        )
        logger.info("ChromaDB collection ready: %s", config.CHROMA_COLLECTION)
        return _collection
    except Exception as e:
        logger.error("ChromaDB init failed: %s", e)
        return None


def normalize_header(header: str) -> str:
    """Normalize a header string for memory lookup."""
    import re
    h = header.lower().strip()
    h = re.sub(r"[\s_\-\.]+", " ", h)
    h = re.sub(r"[^\w\s]", "", h)
    return h.strip()


def store_approved_mapping(
    source_column: str,
    target_field: str,
    confidence: float,
    method: str,
    reviewer_id: str = "human",
) -> bool:
    """Store a human-approved mapping in ChromaDB."""
    collection = _get_collection()
    if collection is None:
        return False

    try:
        norm = normalize_header(source_column)
        doc_id = f"map_{norm}_{target_field}".replace(" ", "_")[:128]

        collection.upsert(
            ids=[doc_id],
            documents=[f"{source_column} -> {target_field}"],
            metadatas=[{
                "source_column": source_column,
                "normalized_source": norm,
                "target_field": target_field,
                "confidence": confidence,
                "method": method,
                "approved_by": reviewer_id,
                "timestamp": datetime.now().isoformat(),
            }],
        )
        logger.info("Stored approved mapping: %s -> %s", source_column, target_field)
        return True
    except Exception as e:
        logger.error("Failed to store mapping: %s", e)
        return False


def retrieve_mapping(
    source_column: str,
    top_k: int = 3,
) -> List[Dict]:
    """
    Retrieve previously approved mappings for a source column.
    Returns a list of matches sorted by relevance.
    """
    collection = _get_collection()
    if collection is None:
        return []

    try:
        norm = normalize_header(source_column)

        # First: exact normalized match
        results = collection.query(
            query_texts=[source_column],
            n_results=min(top_k, max(1, collection.count())),
            include=["metadatas", "distances", "documents"],
        )

        matches = []
        if results and results.get("metadatas"):
            for i, meta in enumerate(results["metadatas"][0]):
                dist = results["distances"][0][i] if results.get("distances") else 1.0
                # ChromaDB returns L2 distance; convert to similarity score
                similarity = max(0.0, 1.0 - dist / 2.0)
                matches.append({
                    "source_column": meta.get("source_column", ""),
                    "target_field": meta.get("target_field", ""),
                    "confidence": float(meta.get("confidence", 0.0)),
                    "method": meta.get("method", ""),
                    "approved_by": meta.get("approved_by", ""),
                    "timestamp": meta.get("timestamp", ""),
                    "similarity": similarity,
                    "normalized_source": meta.get("normalized_source", ""),
                })

        # Filter to reasonable similarity
        matches = [m for m in matches if m["similarity"] > 0.5]
        return sorted(matches, key=lambda x: x["similarity"], reverse=True)

    except Exception as e:
        logger.error("Memory retrieval failed: %s", e)
        return []


def get_exact_memory_mapping(source_column: str) -> Optional[Dict]:
    """Return the best exact/near-exact memory match for a source column."""
    matches = retrieve_mapping(source_column, top_k=1)
    if not matches:
        return None
    best = matches[0]
    # Only trust high-similarity hits
    if best["similarity"] > 0.85:
        return best
    return None
