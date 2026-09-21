"""SQLAlchemy storage. Tokens are digests; SQLite enforces foreign keys."""
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


def make_engine(url):
    # Import phase-2 tables here so they register on the same metadata
    # BEFORE create_all is called, but AFTER metadata is defined.
    from . import tables2  # noqa: F401

    if url is None:
        path = Path(__file__).resolve().parents[2] / 'data'
        path.mkdir(parents=True, exist_ok=True)
        url = 'sqlite:///' + (path / 'jax.db').as_posix()
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    options = {}
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
