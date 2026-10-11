"""Start JAX server with environment loaded from .env.

Uses the same loader as the app (core.app.main calls load_dotenv), so values
are parsed consistently whether you start via this script or via uvicorn.
"""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import uvicorn  # noqa: E402

from core.app.main import create_app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8788, log_level="info")
