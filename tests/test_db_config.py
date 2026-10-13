"""Database URL resolution and the no-database failure mode."""
from pathlib import Path

import pytest

from core.app.db import database_url_from_env, make_engine
from core.app.main import create_app

TOKEN = 'x' * 40


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv('JAX_DATABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_DATABASE_URL', raising=False)
    monkeypatch.setenv('JAX_PROVIDER', 'stub')


def test_unset_resolves_to_none():
    assert database_url_from_env() is None


def test_empty_values_resolve_to_none(monkeypatch):
    monkeypatch.setenv('JAX_DATABASE_URL', '')
    monkeypatch.setenv('SUPABASE_DATABASE_URL', '')
    assert database_url_from_env() is None


def test_supabase_name_is_honoured(monkeypatch):
    monkeypatch.setenv('SUPABASE_DATABASE_URL', 'postgresql://supabase')
    assert database_url_from_env() == 'postgresql://supabase'


def test_jax_name_wins_over_supabase_name(monkeypatch):
    monkeypatch.setenv('JAX_DATABASE_URL', 'postgresql://jax')
    monkeypatch.setenv('SUPABASE_DATABASE_URL', 'postgresql://supabase')
    assert database_url_from_env() == 'postgresql://jax'


def test_create_app_uses_supabase_url(monkeypatch, tmp_path):
    db_file = tmp_path / 'supabase.db'
    monkeypatch.setenv('SUPABASE_DATABASE_URL', f'sqlite:///{db_file.as_posix()}')
    app = create_app(admin_token=TOKEN)
    assert Path(app.state.engine.url.database) == db_file
    app.state.engine.dispose()


@pytest.mark.parametrize('scheme', ['postgres://', 'postgresql://'])
def test_postgres_urls_use_psycopg_without_prepared_statements(monkeypatch, scheme):
    import core.app.db as db
    seen = {}

    def fake_create_engine(url, **options):
        seen['url'], seen['options'] = url, options

        class Engine:
            dialect = type('D', (), {'name': 'postgresql'})
        return Engine()

    monkeypatch.setattr(db, 'create_engine', fake_create_engine)
    monkeypatch.setattr(db.metadata, 'create_all', lambda engine: None)
    db.make_engine(scheme + 'u:p@host:5432/db')
    assert seen['url'] == 'postgresql+psycopg://u:p@host:5432/db'
    assert seen['options']['connect_args'] == {'prepare_threshold': None}
    assert seen['options']['pool_pre_ping'] is True


def test_no_database_on_read_only_fs_says_what_to_set(monkeypatch):
    def deny(self, *args, **kwargs):
        raise OSError(30, 'Read-only file system')

    monkeypatch.setattr(Path, 'mkdir', deny)
    with pytest.raises(RuntimeError, match='JAX_DATABASE_URL'):
        make_engine(None)
