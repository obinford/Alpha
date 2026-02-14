"""Re-export app from api.main so both `main:app` and `api.main:app` work."""

from api.main import app  # noqa: F401
