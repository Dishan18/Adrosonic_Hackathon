"""
Test isolation: point persistent stores at a throwaway directory.

app.config reads these at import time, and tests approve mappings (which are
written to ChromaDB memory) and export files. Without this, every test run
writes "human-approved" mappings into the real ./chroma_db, and those then
steer Stage 0 of schema mapping for real uploads.
"""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="sov_tests_")
os.environ["CHROMA_PERSIST_DIR"] = os.path.join(_TMP, "chroma_db")
os.environ["OUTPUT_DIR"] = os.path.join(_TMP, "outputs")
os.environ["UPLOAD_DIR"] = os.path.join(_TMP, "uploads")
os.environ["CHECKPOINT_DB"] = os.path.join(_TMP, "checkpoints.sqlite")
