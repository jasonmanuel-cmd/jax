"""Hosted entrypoint: healthy start and fail-closed startup errors."""
import importlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from core.app import asgi


@pytest.fixture
def reload_asgi(monkeypatch):
    for name in ('JAX_DATABASE_URL', 'SUPABASE_DATABASE_URL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('JAX_PROVIDER', 'stub')
    yield lambda: importlib.reload(asgi)
    monkeypatch.undo()
    importlib.reload(asgi)


def test_missing_admin_token_serves_503_naming_the_variable(monkeypatch, reload_asgi):
    monkeypatch.delenv('JAX_ADMIN_TOKEN', raising=False)
    app = reload_asgi().app
    with TestClient(app) as client:
        for path in ('/', '/v1/anything'):
            response = client.get(path)
            assert response.status_code == 503
            assert 'JAX_ADMIN_TOKEN' in response.json()['detail']


def test_healthy_start_is_the_real_app(monkeypatch, tmp_path, reload_asgi):
    monkeypatch.setenv('JAX_ADMIN_TOKEN', 'x' * 40)
    monkeypatch.setenv('JAX_DATABASE_URL', f'sqlite:///{(tmp_path / "a.db").as_posix()}')
    app = reload_asgi().app
    assert app.title == 'JAX Core'
    app.state.engine.dispose()


def test_database_driver_errors_are_not_echoed():
    exc = OperationalError('SELECT 1', {}, Exception('host db.secret.supabase.co refused'))
    message = asgi.describe_startup_failure(exc)
    assert 'secret' not in message
    assert 'JAX_DATABASE_URL' in message


def test_unknown_errors_report_only_the_type():
    message = asgi.describe_startup_failure(KeyError('s3cr3t'))
    assert 's3cr3t' not in message
    assert 'KeyError' in message
