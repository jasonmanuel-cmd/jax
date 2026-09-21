"""Phase-2 tables: workspaces, projects, memories, tasks, decisions,
handoffs, documents, daily_summaries, tool_permissions, tool_runs,
agent_runs, kill_switch, memory_deletion_audit.
"""
from sqlalchemy import Column, String, Boolean, Integer, JSON, ForeignKey, Text, DateTime, BigInteger, Float, Table
from .metadata import metadata  # shared metadata so create_all builds everything


def _uuid_pk(name: str, **kw) -> Column:
    return Column(name, String(36), primary_key=True, **kw)


workspaces = Table(
    'workspaces', metadata,
    _uuid_pk('id'),
    Column('user_id', String(36), nullable=False),
    Column('name', String(120), nullable=False),
    Column('type', String(40), nullable=False, default='personal'),
    Column('status', String(20), nullable=False, default='active'),
    Column('created_at', DateTime(timezone=True), nullable=False),
)

projects = Table(
    'projects', metadata,
    _uuid_pk('id'),
    Column('workspace_id', String(36), ForeignKey('workspaces.id'), nullable=True),
    Column('user_id', String(36), nullable=False),
    Column('name', String(200), nullable=False),
    Column('path_hint', String(512), nullable=True),
    Column('repo_url', String(512), nullable=True),
    Column('status', String(20), nullable=False, default='active'),
    Column('created_at', DateTime(timezone=True), nullable=False),
)

memories = Table(
    'memories', metadata,
    _uuid_pk('id'),
    Column('user_id', String(36), nullable=False),
    Column('kind', String(40), nullable=False),
    Column('content', Text, nullable=False),
    Column('confidence', Float, nullable=False, default=1.0),
    Column('source_event_id', BigInteger, ForeignKey('events.id'), nullable=True),
    Column('project_id', String(36), ForeignKey('projects.id'), nullable=True),
    Column('created_at', DateTime(timezone=True), nullable=False),
    Column('expires_at', DateTime(timezone=True), nullable=True),
)

memory_deletion_audit = Table(
    'memory_deletion_audit', metadata,
    _uuid_pk('id'),
    Column('memory_id', String(36), nullable=False),
    Column('kind', String(40), nullable=False),
    Column('user_id', String(36), nullable=False),
    Column('deleted_at', DateTime(timezone=True), nullable=False),
)

tasks = Table(
    'tasks', metadata,
    _uuid_pk('id'),
    Column('project_id', String(36), ForeignKey('projects.id'), nullable=True),
    Column('user_id', String(36), nullable=False),
    Column('title', String(300), nullable=False),
    Column('status', String(20), nullable=False, default='open'),
    Column('priority', String(10), nullable=False, default='medium'),
    Column('due_at', DateTime(timezone=True), nullable=True),
    Column('source', String(40), nullable=True),
    Column('created_at', DateTime(timezone=True), nullable=False),
)

decisions = Table(
    'decisions', metadata,
    _uuid_pk('id'),
    Column('project_id', String(36), ForeignKey('projects.id'), nullable=True),
    Column('user_id', String(36), nullable=False),
    Column('decision', Text, nullable=False),
    Column('rationale', Text, nullable=True),
    Column('decided_at', DateTime(timezone=True), nullable=False),
    Column('supersedes_id', String(36), ForeignKey('decisions.id'), nullable=True),
)

handoffs = Table(
    'handoffs', metadata,
    _uuid_pk('id'),
    Column('from_device', String(36), nullable=True),
    Column('project_id', String(36), ForeignKey('projects.id'), nullable=True),
    Column('summary', Text, nullable=False),
    Column('next_action', Text, nullable=True),
    Column('created_at', DateTime(timezone=True), nullable=False),
)

documents = Table(
    'documents', metadata,
    _uuid_pk('id'),
    Column('project_id', String(36), ForeignKey('projects.id'), nullable=True),
    Column('user_id', String(36), nullable=False),
    Column('title', String(300), nullable=False),
    Column('source', String(512), nullable=True),
    Column('text_ref', String(512), nullable=True),
    Column('checksum', String(64), nullable=True),
    Column('created_at', DateTime(timezone=True), nullable=False),
)

daily_summaries = Table(
    'daily_summaries', metadata,
    _uuid_pk('id'),
    Column('user_id', String(36), nullable=False),
    Column('date', String(10), nullable=False),
    Column('accomplishments', JSON, nullable=False, default=list),
    Column('blockers', JSON, nullable=False, default=list),
    Column('next_actions', JSON, nullable=False, default=list),
    Column('created_at', DateTime(timezone=True), nullable=False),
)

tool_permissions = Table(
    'tool_permissions', metadata,
    _uuid_pk('id'),
    Column('user_id', String(36), nullable=False),
    Column('device_id', String(36), ForeignKey('devices.id'), nullable=True),
    Column('tool_name', String(80), nullable=False),
    Column('level', Integer, nullable=False, default=0),
    Column('enabled', Boolean, nullable=False, default=False),
)

tool_runs = Table(
    'tool_runs', metadata,
    _uuid_pk('id'),
    Column('tool_name', String(80), nullable=False),
    Column('arguments_hash', String(64), nullable=True),
    Column('reason', Text, nullable=True),
    Column('approval_state', String(20), nullable=False, default='pending'),
    Column('result', Text, nullable=True),
    Column('device_id', String(36), ForeignKey('devices.id'), nullable=True),
    Column('created_at', DateTime(timezone=True), nullable=False),
)

agent_runs = Table(
    'agent_runs', metadata,
    _uuid_pk('id'),
    Column('agent_name', String(80), nullable=False),
    Column('objective', Text, nullable=False),
    Column('status', String(20), nullable=False, default='running'),
    Column('model', String(80), nullable=True),
    Column('started_at', DateTime(timezone=True), nullable=False),
    Column('finished_at', DateTime(timezone=True), nullable=True),
    Column('device_id', String(36), ForeignKey('devices.id'), nullable=True),
)

kill_switch = Table(
    'kill_switch', metadata,
    Column('id', String(36), primary_key=True),
    Column('device_id', String(36), ForeignKey('devices.id'), nullable=True),
    Column('reason', Text, nullable=False),
    Column('activated_at', DateTime(timezone=True), nullable=False),
    Column('deactivated_at', DateTime(timezone=True), nullable=True),
    Column('activated_by', String(36), nullable=False),
)

leads = Table(
    'leads', metadata,
    _uuid_pk('id'),
    Column('user_id', String(36), nullable=False),
    Column('address', String(500), nullable=True),
    Column('city', String(100), nullable=True),
    Column('state', String(50), nullable=True),
    Column('zip_code', String(20), nullable=True),
    Column('owner_name', String(200), nullable=True),
    Column('situation', String(80), nullable=True),  # foreclosure, pre-foreclosure, tax-lien, bankruptcy, etc.
    Column('contact_info', Text, nullable=True),
    Column('source_url', String(1000), nullable=True),
    Column('source_query', String(500), nullable=True),
    Column('notes', Text, nullable=True),
    Column('status', String(30), nullable=False, default='new'),  # new, contacted, interested, closed, dead
    Column('raw_data', JSON, nullable=True),
    Column('created_at', DateTime(timezone=True), nullable=False),
    Column('updated_at', DateTime(timezone=True), nullable=True),
)
