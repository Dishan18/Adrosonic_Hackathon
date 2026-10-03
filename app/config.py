"""
Application configuration: reads from environment variables / .env file.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root
load_dotenv(Path(__file__).parent.parent / ".env")


class Config:
    # LLM provider: "groq" or "ollama"
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama")

    # Groq settings
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

    # Gemini settings (fallback or primary)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # Ollama settings
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "mistral")

    # Embedding model
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

    # ChromaDB
    CHROMA_PERSIST_DIR: str = os.getenv(
        "CHROMA_PERSIST_DIR",
        str(Path(__file__).parent.parent / "chroma_db"),
    )
    CHROMA_COLLECTION: str = os.getenv("CHROMA_COLLECTION", "sov_mappings")

    # SQLite checkpoint
    CHECKPOINT_DB: str = os.getenv(
        "CHECKPOINT_DB",
        str(Path(__file__).parent.parent / "checkpoints.sqlite"),
    )

    # Output directory
    OUTPUT_DIR: str = os.getenv(
        "OUTPUT_DIR",
        str(Path(__file__).parent.parent / "outputs"),
    )

    # Fuzzy matching threshold
    FUZZY_THRESHOLD: float = float(os.getenv("FUZZY_THRESHOLD", "0.75"))

    # Semantic similarity threshold
    SEMANTIC_THRESHOLD: float = float(os.getenv("SEMANTIC_THRESHOLD", "0.60"))

    # High-confidence threshold (eligible for Approve All)
    HIGH_CONFIDENCE_THRESHOLD: float = float(os.getenv("HIGH_CONFIDENCE_THRESHOLD", "0.90"))

    # Max LLM re-reason attempts before escalation
    MAX_REREASON_ATTEMPTS: int = int(os.getenv("MAX_REREASON_ATTEMPTS", "2"))

    # Max rows to send to LLM as sample (data minimisation)
    LLM_SAMPLE_ROWS: int = int(os.getenv("LLM_SAMPLE_ROWS", "5"))

    # Temp upload directory
    UPLOAD_DIR: str = os.getenv(
        "UPLOAD_DIR",
        str(Path(__file__).parent.parent / "uploads"),
    )

    @classmethod
    def is_llm_available(cls) -> bool:
        if cls.LLM_PROVIDER == "groq":
            return bool(cls.GROQ_API_KEY or cls.GEMINI_API_KEY)
        if cls.LLM_PROVIDER == "gemini":
            return bool(cls.GEMINI_API_KEY)
        if cls.LLM_PROVIDER == "ollama":
            return True  # Assume reachable; will fail gracefully at call time
        return bool(cls.GROQ_API_KEY or cls.GEMINI_API_KEY)


config = Config()
