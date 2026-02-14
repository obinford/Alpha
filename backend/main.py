"""Re-export app from api.main so both `main:app` and `api.main:app` work."""

import os
import sys

_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from api.main import app  # noqa: F401
