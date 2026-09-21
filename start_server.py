"""Start JAX server with environment loaded from .env."""
import os
import sys
from pathlib import Path

# Load .env
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

# Start server
from core.app.main import create_app
import uvicorn

app = create_app()
uvicorn.run(app, host="127.0.0.1", port=8788, log_level="info")
