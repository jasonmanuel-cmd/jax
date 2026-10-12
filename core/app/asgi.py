"""ASGI entrypoint for hosted deployments (Vercel).

main.py builds the app inside create_app() so tests can inject a database and
admin token. Hosts that import a module-level `app` get it from here instead.
Importing this module requires JAX_ADMIN_TOKEN (32+ chars) and the database/
provider settings from .env.example to be present in the environment.

If startup fails, the host would show an opaque 500 page. Instead serve a
fail-closed 503 that names the configuration problem, and log the traceback.
Only messages this codebase raises itself are shown; anything else (database
driver errors can carry hostnames) is reduced to a category.
"""
import json
import logging

from core.app.main import create_app

log = logging.getLogger('jax.asgi')


def describe_startup_failure(exc):
    """A message safe to show publicly for a failed create_app()."""
    if isinstance(exc, (ValueError, RuntimeError)):
        return f'{type(exc).__name__}: {exc}'
    if type(exc).__module__.startswith('sqlalchemy'):
        return ('Database connection failed. Check JAX_DATABASE_URL (use the '
                'Supabase pooler URL on Vercel). See runtime logs.')
    return f'Startup failed ({type(exc).__name__}). See runtime logs.'


def failed_app(message):
    body = json.dumps({'error': 'JAX failed to start', 'detail': message}).encode()

    async def app(scope, receive, send):
        if scope['type'] == 'lifespan':
            while True:
                event = await receive()
                if event['type'] == 'lifespan.startup':
                    await send({'type': 'lifespan.startup.complete'})
                elif event['type'] == 'lifespan.shutdown':
                    await send({'type': 'lifespan.shutdown.complete'})
                    return
        if scope['type'] == 'http':
            await send({'type': 'http.response.start', 'status': 503,
                        'headers': [(b'content-type', b'application/json'),
                                    (b'cache-control', b'no-store')]})
            await send({'type': 'http.response.body', 'body': body})

    return app


try:
    app = create_app()
except Exception as exc:
    log.exception('create_app() failed')
    app = failed_app(describe_startup_failure(exc))
