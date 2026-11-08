"""SQLAlchemy storage. Tokens are digests; SQLite enforces foreign keys."""
import os
from pathlib import Path
from sqlalchemy import Table, Column, String, Boolean, JSON, ForeignKey, create_engine, event, DateTime, Text
from sqlalchemy.pool import StaticPool
from .metadata import metadata

devices = Table('devices', metadata,
    Column('id', String(36), primary_key=True),
    Column('name', String(100), nullable=False),
    Column('platform', String(32), nullable=False),
    Column('token_hash', String(64), nullable=False, unique=True),
    Column('revoked', Boolean, nullable=False, default=False))


events = Table('events', metadata,
    Column('id', String(36), primary_key=True),
    Column('device_id', String(36), ForeignKey('devices.id'), nullable=False),
    Column('payload', JSON, nullable=False),
    Column('occurred_at', DateTime(timezone=True), nullable=True))

improvement_proposals = Table('improvement_proposals', metadata,
    Column('id', String(36), primary_key=True),
    Column('file_path', String(512), nullable=False),
    Column('proposal_json', Text, nullable=False),
    Column('status', String(20), nullable=False, default='pending'),
    Column('created_at', DateTime(timezone=True), nullable=False),
    Column('applied_at', DateTime(timezone=True), nullable=True),
    Column('reviewer_note', Text, nullable=True))


def database_url_from_env():
    """JAX_DATABASE_URL wins; SUPABASE_DATABASE_URL is the name .env.example
    documents, so honour it too rather than silently ignoring it."""
    return (os.environ.get('JAX_DATABASE_URL')
            or os.environ.get('SUPABASE_DATABASE_URL')
            or None)


def make_engine(url):
    # Import phase-2 tables here so they register on the same metadata
    # BEFORE create_all is called, but AFTER metadata is defined.
    from . import tables2  # noqa: F401

    if url is None:
        path = Path(__file__).resolve().parents[2] / 'data'
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # Read-only deployments (e.g. Vercel) cannot use the local SQLite
            # fallback. Say what to set instead of crashing on mkdir.
            raise RuntimeError(
                'No database configured: set JAX_DATABASE_URL (or '
                f'SUPABASE_DATABASE_URL). The local SQLite fallback at {path} '
                f'is not writable here ({exc}).') from exc
        url = 'sqlite:///' + (path / 'jax.db').as_posix()
    # Hosts hand out both spellings; SQLAlchemy only knows "postgresql".
    for scheme in ('postgres://', 'postgresql://'):
        if url.startswith(scheme):
            url = 'postgresql+psycopg://' + url[len(scheme):]
            break
    options = {}
    if url.startswith('postgresql+psycopg:'):
        # Supabase's pooler (pgbouncer, transaction mode) cannot keep psycopg's
        # server-side prepared statements, which it creates after a few
        # repeats of a query. Disable them; also drop stale pooled connections.
        options['connect_args'] = {'prepare_threshold': None}
        options['pool_pre_ping'] = True
    if url.startswith('sqlite:'):
        options['connect_args'] = {'check_same_thread': False}
        if url in ('sqlite://', 'sqlite:///:memory:'):
            options['poolclass'] = StaticPool
    engine = create_engine(url, **options)
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine, 'connect')
        def enforce_foreign_keys(connection, _):
            cursor = connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()
    metadata.create_all(engine)
    return engine
