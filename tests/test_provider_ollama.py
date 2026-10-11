"""Local model provider (Ollama) — SPEC_AUDIT R9.

Two defects motivated this:

1. Providers returned an ordinary answer object when they were not configured
   or the call failed, so a caller could not tell a model reply from an error.
   These tests assert failures raise.
2. The Ollama adapter is loopback-only in its default and allow-lists the
   model response, so a runaway 'thinking' payload cannot be mistaken for an
   answer.
"""
import asyncio
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.app.providers.base import (  # noqa: E402
    ProviderError, ProviderUnavailable,
)
from core.app.providers.ollama_provider import OllamaProvider  # noqa: E402


def run(coro):
    """Run a coroutine without disturbing the global event loop.

    asyncio.run() calls set_event_loop(None) on exit, which makes the
    deprecated asyncio.get_event_loop() in other tests raise instead
    of warn. A private loop leaves global state untouched.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

ADMIN = 'test-admin-token-that-is-long-enough-0123456789'
AUTH = {'Authorization': f'Bearer {ADMIN}'}


@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    module = importlib.import_module('core.app.main')
    with TestClient(module.create_app(
            database_url=f'sqlite:///{tmp_path}/jax.db',
            admin_token=ADMIN), headers=AUTH) as c:
        yield c


# -- failure is a failure, not an answer ---------------------------------

def test_unavailable_is_a_typed_error():
    """Unreachable backend raises, never returns a placeholder answer."""
    p = OllamaProvider(model='qwen3-coder:30b',
                       base_url='http://127.0.0.1:59999')
    with pytest.raises(ProviderUnavailable):
        run(p.complete([{'role': 'user', 'content': 'hi'}]))


def test_unavailable_subclasses_provider_error():
    """Callers can catch one type and still catch every provider fault."""
    assert issubclass(ProviderUnavailable, ProviderError)


def test_healthcheck_never_raises():
    """Diagnostics must work even when the backend is down."""
    p = OllamaProvider(base_url='http://127.0.0.1:59999')
    report = run(p.healthcheck())
    assert report['available'] is False
    assert 'error' in report


# -- defaults are safe ----------------------------------------------------

def test_defaults_to_loopback():
    p = OllamaProvider()
    assert p.base_url == 'http://127.0.0.1:11434'
    assert '127.0.0.1' in p.base_url


def test_env_overrides_model():
    import os
    os.environ['JAX_MODEL'] = 'deepseek-r1:32b'
    try:
        assert OllamaProvider().model == 'deepseek-r1:32b'
    finally:
        del os.environ['JAX_MODEL']


# -- app wiring -----------------------------------------------------------

def test_ollama_is_selectable(tmp_path, monkeypatch):
    monkeypatch.setenv('JAX_PROVIDER', 'ollama')
    from fastapi.testclient import TestClient
    module = importlib.import_module('core.app.main')
    with TestClient(module.create_app(
            database_url=f'sqlite:///{tmp_path}/jax.db',
            admin_token=ADMIN), headers=AUTH) as c:
        assert isinstance(c.app.state.provider, OllamaProvider)


def test_unknown_provider_fails_loudly(tmp_path, monkeypatch):
    """A typo in JAX_PROVIDER must not look like a working deployment."""
    monkeypatch.setenv('JAX_PROVIDER', 'openroutr')  # typo
    from fastapi.testclient import TestClient
    module = importlib.import_module('core.app.main')
    with pytest.raises(RuntimeError, match='Unknown JAX_PROVIDER'):
        module.create_app(database_url=f'sqlite:///{tmp_path}/jax.db',
                         admin_token=ADMIN)


def test_chat_returns_503_when_backend_down(client, monkeypatch):
    """A model outage is a 503, not a 200 with an error string in 'answer'."""
    monkeypatch.setenv('JAX_PROVIDER', 'ollama')
    from core.app.main import create_app
    app = create_app(database_url='sqlite:///unused.db', admin_token=ADMIN)
    app.state.provider.base_url = 'http://127.0.0.1:59999'
    from fastapi.testclient import TestClient
    with TestClient(app, headers=AUTH) as c:
        r = c.post('/v1/chat', json={'query': 'hello'})
        assert r.status_code == 503
        assert 'unavailable' in r.json()['detail'].lower()
        # Critically: no 'answer' key masquerading as a reply.
        assert 'answer' not in r.json()


def test_package_exports_the_adapter():
    pkg = importlib.import_module('core.app.providers')
    assert hasattr(pkg, 'OllamaProvider')
    assert hasattr(pkg, 'ProviderError')