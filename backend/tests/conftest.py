"""Test setup: point the shared engine at a throwaway SQLite file BEFORE any
backend module is imported (usage_log creates the engine at import time)."""
import os
import sys
import tempfile

_db_fd, _db_path = tempfile.mkstemp(prefix="mm_test_", suffix=".db")
os.close(_db_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
for p in (_PROJECT_ROOT, _BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)
