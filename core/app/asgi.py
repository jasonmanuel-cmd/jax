"""ASGI entrypoint for hosted deployments (Vercel).

main.py builds the app inside create_app() so tests can inject a database and
admin token. Hosts that import a module-level `app` get it from here instead.
Importing this module requires JAX_ADMIN_TOKEN (32+ chars) and the database/
provider settings from .env.example to be present in the environment.
"""
from core.app.main import create_app

app = create_app()
