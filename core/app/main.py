"""JAX private local-first core. Use create_app as an ASGI factory."""
import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

from .privacy import safe_text
from .self_improve import analyze_project, proposal_to_json, proposal_from_json, LEVEL_DRAFT
from .self_improve_apply import classify_target, materialize_as_patch, validate_proposal
from .retrieval import retrieve_context
from .providers.base import ModelProvider, LocalProvider
from .providers.openrouter import OpenRouterProvider
from .providers.openai_provider import OpenAIProvider
from .providers.groq import GroqProvider
from .providers.ollama_provider import OllamaProvider
from .providers.base import ProviderError, ProviderUnavailable
from .voice import VoiceProvider
from .agents import build_registry
from .audit.approvals import ApprovalStore, AuditLog
from .policy_engine import PolicyDenied, default_registry
from .core.session_manager import LaunchRefused, SessionManager
from sqlalchemy import select
from .db import database_url_from_env, devices, events, improvement_proposals, make_engine
from .tables2 import (
    workspaces, projects, memories, memory_deletion_audit,
    tasks, decisions, handoffs, documents, daily_summaries,
    tool_permissions, tool_runs, agent_runs, kill_switch as kill_switch_table,
    leads as leads_table,
)
from .kill_switch import is_kill_active
from .leads import LeadFinder
from datetime import datetime, timezone
from typing import Literal, Optional
from sqlalchemy.exc import IntegrityError

# ---------------------------------------------------------------------------
# Prompt version constant
# ---------------------------------------------------------------------------
PROMPT_VERSION = 'chat_v1'

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class EventIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: UUID
    device_id: UUID
    type: Literal['git_context']
    summary: str = Field(min_length=1, max_length=1000)
    app: str | None = Field(default=None, max_length=80)
    metadata: dict = Field(default_factory=dict)
    occurred_at: datetime

    @field_validator('summary', 'app')
    @classmethod
    def private_text(cls, value):
        return safe_text(value) if value is not None else value

    @field_validator('occurred_at')
    @classmethod
    def utc_only(cls, value):
        if value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
            raise ValueError('UTC timestamp required')
        return value

    @field_validator('metadata')
    @classmethod
    def narrow_metadata(cls, value):
        for key, item in value.items():
            if key in ('dirty_count', 'changed_files'):
                if type(item) is not int or not 0 <= item <= 1000000:
                    raise ValueError('Invalid count')
            elif key in ('branch', 'commit_hash'):
                if not isinstance(item, str) or len(item) > 256:
                    raise ValueError('Invalid metadata text')
                safe_text(item)
            else:
                raise ValueError('Unsupported metadata field')
        return value


class DeviceIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    platform: str = Field(min_length=1, max_length=32)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None


class MemoryIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str = Field(min_length=1, max_length=40)
    content: str = Field(min_length=1, max_length=10000)
    confidence: float = Field(default=1.0, ge=0, le=1)
    project_id: str | None = None
    source_event_id: int | None = None
    expires_at: datetime | None = None

    @field_validator('kind', 'content')
    @classmethod
    def reject_memory_secrets(cls, value):
        return safe_text(value)


class TaskIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_id: str | None = None
    title: str = Field(min_length=1, max_length=300)
    status: str = Field(default='open')
    priority: str = Field(default='medium')
    due_at: datetime | None = None
    source: str | None = None


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_id: str | None = None
    decision: str = Field(min_length=1, max_length=5000)
    rationale: str | None = None
    supersedes_id: str | None = None


class HandoffIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_id: str | None = None
    summary: str = Field(min_length=1, max_length=5000)
    next_action: str | None = None


class WorkspaceIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(default='personal')
    status: str = Field(default='active')


class KillActivate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=1000)
    device_id: str | None = None


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_app(database_url=None, admin_token=None):
    token = admin_token if admin_token is not None else os.environ.get('JAX_ADMIN_TOKEN', '')
    if len(token) < 32:
        raise ValueError('JAX_ADMIN_TOKEN must contain at least 32 characters')
    engine = make_engine(database_url or database_url_from_env())

    # Wire real model provider based on env vars
    provider_name = os.environ.get('JAX_PROVIDER', 'openrouter').lower()
    if provider_name == 'openrouter' or not provider_name:
        provider: ModelProvider = OpenRouterProvider(
            model=os.environ.get('JAX_MODEL', 'openai/gpt-4o-mini')
        )
    elif provider_name == 'openai':
        provider = OpenAIProvider(
            model=os.environ.get('JAX_MODEL', 'gpt-4o-mini')
        )
    elif provider_name == 'groq':
        provider = GroqProvider(
            model=os.environ.get('JAX_MODEL', 'llama-3.3-70b-versatile')
        )
    elif provider_name == 'ollama':
        # Local inference. No API key, nothing leaves the machine. The model
        # default matches what is usually pulled; override with JAX_MODEL.
        provider = OllamaProvider(
            model=os.environ.get('JAX_MODEL', 'qwen3-coder:30b')
        )
    elif provider_name == 'stub':
        provider = LocalProvider()
    else:
        # Previously any unrecognised name silently produced LocalProvider,
        # so a typo in JAX_PROVIDER looked like a working deployment that
        # returned "Model provider not yet configured." Fail loudly instead.
        raise RuntimeError(
            f'Unknown JAX_PROVIDER {provider_name!r}. Expected one of: '
            'ollama, openrouter, openai, groq, stub.')

    voice = VoiceProvider()

    # Managed-session control plane: adapters, policy, session lifecycle.
    adapters = build_registry()
    policy = default_registry()
    audit = AuditLog(engine)
    approvals = ApprovalStore(engine, policy)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title='JAX Core', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.engine = engine
    app.state.provider = provider
    app.state.voice = voice
    app.state.adapters = adapters
    app.state.policy = policy
    app.state.sessions = SessionManager(engine, adapters, policy)
    app.state.audit = audit
    app.state.approvals = approvals

    # Serve the web UI
    _ui_path = Path(__file__).resolve().parent.parent / 'static' / 'index.html'

    @app.get('/', response_class=HTMLResponse, include_in_schema=False)
    def ui():
        return _ui_path.read_text(encoding='utf-8')

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(status_code=422, content={'detail': 'Invalid or privacy-rejected request'})

    bearer = HTTPBearer(auto_error=False)

    def identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        unauthorized = HTTPException(401, 'Invalid bearer token', headers={'WWW-Authenticate': 'Bearer'})
        if credentials is None:
            raise unauthorized
        hashed = digest(credentials.credentials)
        if secrets.compare_digest(hashed, digest(token)):
            return {'role': 'admin', 'id': 'admin'}
        with engine.connect() as db:
            device = db.execute(select(devices).where(devices.c.token_hash == hashed, devices.c.revoked.is_(False))).mappings().first()
        if device is None:
            raise unauthorized
        return {'role': 'device', 'id': device['id']}

    def admin(actor=Depends(identity)):
        if actor['role'] != 'admin':
            raise HTTPException(403, 'Admin required')
        return actor

    def guard_kill(db_conn, device_id=None, global_only=False):
        """Refuse while a kill switch applies. Raise so callers cannot forget."""
        if is_kill_active(db_conn, device_id, global_only=global_only):
            scope = 'globally' if global_only else f'for device {device_id}'
            raise HTTPException(
                423, f'Kill switch active {scope}: execution is suspended. '
                     'Deactivate it to resume.')

    def live(actor=Depends(identity)):
        """Identity + kill-switch gate, for endpoints that cause side effects.

        The kill switch must stop *execution*, not merely ingestion, or an
        operator who activates it during an incident gets false assurance.
        Read-only endpoints deliberately do not use this, so status can still
        be inspected and the switch can be lifted.

        A device-scoped switch only halts that device. Only a global switch
        halts admin work, so one compromised machine does not freeze the core.
        """
        device_id = actor['id'] if actor['role'] == 'device' else None
        with engine.connect() as db:
            guard_kill(db, device_id, global_only=device_id is None)
        return actor

    def live_admin(actor=Depends(live)):
        if actor['role'] != 'admin':
            raise HTTPException(403, 'Admin required')
        return actor

    # -----------------------------------------------------------------------
    # Health
    # -----------------------------------------------------------------------

    @app.get('/health')
    def health():
        return {'status': 'ok', 'service': 'jax-core'}

    @app.get('/v1/provider/health')
    async def provider_health(actor=Depends(admin)):
        """Report model-provider reachability.

        Deliberately a read and deliberately not kill-gated: 'why is chat
        failing' is exactly the question you ask during an incident. The
        provider reports itself rather than this endpoint guessing, and it
        never raises, so a dead backend yields available=false rather than a
        500 that hides the cause.
        """
        report = await app.state.provider.healthcheck()
        return {'provider': type(app.state.provider).__name__,
                'report': report}

    # -----------------------------------------------------------------------
    # Devices
    # -----------------------------------------------------------------------

    @app.post('/v1/devices', status_code=201)
    def create_device(body: DeviceIn, actor=Depends(admin)):
        raw_token = secrets.token_urlsafe(32)
        device_id = str(uuid4())
        with engine.begin() as db:
            db.execute(devices.insert().values(id=device_id, **body.model_dump(), token_hash=digest(raw_token), revoked=False))
        return {'id': device_id, 'token': raw_token}

    @app.get('/v1/devices')
    def list_devices(actor=Depends(admin)):
        with engine.connect() as db:
            return [dict(row) for row in db.execute(select(devices.c.id, devices.c.name, devices.c.platform, devices.c.revoked)).mappings()]

    @app.post('/v1/devices/{device_id}/revoke')
    def revoke_device(device_id: UUID, actor=Depends(live_admin)):
        with engine.begin() as db:
            result = db.execute(devices.update().where(devices.c.id == str(device_id)).values(revoked=True))
            if not result.rowcount:
                raise HTTPException(404, 'Device not found')
        return {'id': str(device_id), 'revoked': True}

    # -----------------------------------------------------------------------
    # Events
    # -----------------------------------------------------------------------

    @app.post('/v1/events')
    def ingest(body: EventIn, actor=Depends(identity)):
        if actor['role'] != 'device' or actor['id'] != str(body.device_id):
            raise HTTPException(403, 'Device identity mismatch')
        with engine.connect() as db:
            if is_kill_active(db, actor['id']):
                raise HTTPException(403, 'Kill switch active for this device')
        payload = body.model_dump(mode='json')
        event_id = str(body.event_id)
        occurred_at = body.occurred_at
        try:
            with engine.begin() as db:
                db.execute(events.insert().values(id=event_id, device_id=actor['id'], payload=payload, occurred_at=occurred_at))
        except IntegrityError:
            with engine.connect() as db:
                old = db.execute(select(events).where(events.c.id == event_id)).mappings().first()
            if old is None or old['device_id'] != actor['id'] or old['payload'] != payload:
                raise HTTPException(409, 'Event ID conflict')
        return {'id': event_id, 'accepted': True}

    @app.get('/v1/events')
    def list_events(actor=Depends(admin)):
        with engine.connect() as db:
            return [dict(row['payload']) for row in db.execute(select(events)).mappings()]

    # -----------------------------------------------------------------------
    # Workspaces  (admin CRUD)
    # -----------------------------------------------------------------------

    @app.post('/v1/workspaces', status_code=201)
    def create_workspace(body: WorkspaceIn, actor=Depends(live_admin)):
        wid = str(uuid4())
        now = datetime.now(timezone.utc)
        with engine.begin() as db:
            db.execute(workspaces.insert().values(
                id=wid, user_id=actor['id'], name=body.name,
                type=body.type, status=body.status, created_at=now))
        return {'id': wid, 'name': body.name, 'type': body.type, 'status': body.status}

    @app.get('/v1/workspaces')
    def list_workspaces(actor=Depends(admin)):
        with engine.connect() as db:
            rows = db.execute(select(workspaces)).mappings().all()
        return [dict(r) for r in rows]

    @app.delete('/v1/workspaces/{workspace_id}')
    def delete_workspace(workspace_id: UUID, actor=Depends(live_admin)):
        with engine.begin() as db:
            result = db.execute(workspaces.delete().where(workspaces.c.id == str(workspace_id)))
            if not result.rowcount:
                raise HTTPException(404, 'Workspace not found')
        return {'id': str(workspace_id), 'deleted': True}

    # -----------------------------------------------------------------------
    # Projects  (admin CRUD)
    # -----------------------------------------------------------------------

    @app.post('/v1/projects', status_code=201)
    def create_project(body: dict, actor=Depends(live_admin)):
        pid = str(uuid4())
        now = datetime.now(timezone.utc)
        with engine.begin() as db:
            db.execute(projects.insert().values(
                id=pid, user_id=actor['id'], name=body['name'],
                workspace_id=body.get('workspace_id'),
                path_hint=body.get('path_hint'),
                repo_url=body.get('repo_url'),
                status=body.get('status', 'active'),
                created_at=now))
        return {'id': pid, 'name': body['name'], 'status': 'active'}

    @app.get('/v1/projects')
    def list_projects(actor=Depends(admin)):
        with engine.connect() as db:
            rows = db.execute(select(projects)).mappings().all()
        return [dict(r) for r in rows]

    @app.get('/v1/projects/{project_id}')
    def get_project(project_id: UUID, actor=Depends(admin)):
        with engine.connect() as db:
            row = db.execute(select(projects).where(projects.c.id == str(project_id))).mappings().first()
        if row is None:
            raise HTTPException(404, 'Project not found')
        return dict(row)

    @app.put('/v1/projects/{project_id}')
    def update_project(project_id: UUID, body: dict, actor=Depends(live_admin)):
        with engine.begin() as db:
            result = db.execute(
                projects.update().where(projects.c.id == str(project_id)).values(**body))
            if not result.rowcount:
                raise HTTPException(404, 'Project not found')
        return {'id': str(project_id), 'updated': True}

    @app.delete('/v1/projects/{project_id}')
    def delete_project(project_id: UUID, actor=Depends(live_admin)):
        with engine.begin() as db:
            result = db.execute(projects.delete().where(projects.c.id == str(project_id)))
            if not result.rowcount:
                raise HTTPException(404, 'Project not found')
        return {'id': str(project_id), 'deleted': True}

    # Canonical preflight is deliberately narrower than project CRUD: only
    # server-configured exact repository roots may reach local Git.
    class PreflightIn(BaseModel):
        model_config = ConfigDict(extra='forbid')
        project_id: UUID
        fetch: bool = True
        fast_forward: bool = False

    @app.post('/v1/sessions/preflight')
    def session_preflight(body: PreflightIn, actor=Depends(live_admin)):
        with engine.connect() as db:
            if is_kill_active(db, None):
                raise HTTPException(403, 'Kill switch active')
            project = db.execute(select(projects).where(
                projects.c.id == str(body.project_id))).mappings().first()
        if project is None:
            raise HTTPException(404, 'Project not found')
        if project['status'] != 'active':
            raise HTTPException(409, 'Project is not active')
        if not project['path_hint']:
            raise HTTPException(409, 'Project has no configured local path')
        try:
            root = Path(project['path_hint']).resolve(strict=True)
            allowed = [Path(p).resolve(strict=True) for p in
                       os.environ.get('JAX_PROJECT_ROOTS', '').split(os.pathsep) if p.strip()]
        except (OSError, RuntimeError):
            raise HTTPException(403, 'Project path is unavailable or not allowed')
        if root not in allowed:
            raise HTTPException(403, 'Project root is not allowlisted')
        if body.fast_forward and not body.fetch:
            raise HTTPException(422, 'Fast-forward requires remote verification')
        from .git_control import inspect_repository
        try:
            state = inspect_repository(root, fetch=body.fetch, fast_forward=body.fast_forward)
        except (ValueError, OSError, RuntimeError):
            raise HTTPException(409, 'Repository preflight failed')
        return {'project_id': str(body.project_id), **state}

    # -----------------------------------------------------------------------
    # Memories  (explicit save/delete only)
    # -----------------------------------------------------------------------

    @app.post('/v1/memories', status_code=201)
    def save_memory(body: MemoryIn, actor=Depends(live_admin)):
        mid = str(uuid4())
        now = datetime.now(timezone.utc)
        with engine.begin() as db:
            db.execute(memories.insert().values(
                id=mid, user_id=actor['id'], kind=body.kind,
                content=body.content, confidence=body.confidence,
                source_event_id=body.source_event_id,
                project_id=body.project_id,
                created_at=now, expires_at=body.expires_at))
        return {'id': mid, 'kind': body.kind}

    @app.get('/v1/memories')
    def list_memories(kind: Optional[str] = None, actor=Depends(admin)):
        stmt = select(memories)
        if kind:
            stmt = stmt.where(memories.c.kind == kind)
        with engine.connect() as db:
            rows = db.execute(stmt).mappings().all()
        return [dict(r) for r in rows]

    @app.delete('/v1/memories/{memory_id}')
    def delete_memory(memory_id: UUID, actor=Depends(live_admin)):
        now = datetime.now(timezone.utc)
        with engine.begin() as db:
            row = db.execute(select(memories).where(memories.c.id == str(memory_id))).mappings().first()
            if row is None:
                raise HTTPException(404, 'Memory not found')
            # Audit record
            db.execute(memory_deletion_audit.insert().values(
                id=str(uuid4()), memory_id=str(memory_id),
                kind=row['kind'], user_id=row['user_id'], deleted_at=now))
            # Hard delete content
            db.execute(memories.delete().where(memories.c.id == str(memory_id)))
        return {'id': str(memory_id), 'deleted': True, 'audit_id': True}

    # -----------------------------------------------------------------------
    # Tasks  (admin CRUD)
    # -----------------------------------------------------------------------

    @app.post('/v1/tasks', status_code=201)
    def create_task(body: TaskIn, actor=Depends(live_admin)):
        tid = str(uuid4())
        now = datetime.now(timezone.utc)
        with engine.begin() as db:
            db.execute(tasks.insert().values(
                id=tid, user_id=actor['id'], project_id=body.project_id,
                title=body.title, status=body.status, priority=body.priority,
                due_at=body.due_at, source=body.source, created_at=now))
        return {'id': tid, 'title': body.title, 'status': body.status}

    @app.get('/v1/tasks')
    def list_tasks(status: Optional[str] = None, actor=Depends(admin)):
        stmt = select(tasks)
        if status:
            stmt = stmt.where(tasks.c.status == status)
        with engine.connect() as db:
            rows = db.execute(stmt).mappings().all()
        return [dict(r) for r in rows]

    @app.put('/v1/tasks/{task_id}')
    def update_task(task_id: UUID, body: dict, actor=Depends(live_admin)):
        with engine.begin() as db:
            result = db.execute(tasks.update().where(tasks.c.id == str(task_id)).values(**body))
            if not result.rowcount:
                raise HTTPException(404, 'Task not found')
        return {'id': str(task_id), 'updated': True}

    @app.delete('/v1/tasks/{task_id}')
    def delete_task(task_id: UUID, actor=Depends(live_admin)):
        with engine.begin() as db:
            result = db.execute(tasks.delete().where(tasks.c.id == str(task_id)))
            if not result.rowcount:
                raise HTTPException(404, 'Task not found')
        return {'id': str(task_id), 'deleted': True}

    # -----------------------------------------------------------------------
    # Decisions  (admin CRUD)
    # -----------------------------------------------------------------------

    @app.post('/v1/decisions', status_code=201)
    def create_decision(body: DecisionIn, actor=Depends(live_admin)):
        did = str(uuid4())
        now = datetime.now(timezone.utc)
        with engine.begin() as db:
            db.execute(decisions.insert().values(
                id=did, user_id=actor['id'], project_id=body.project_id,
                decision=body.decision, rationale=body.rationale,
                supersedes_id=body.supersedes_id, decided_at=now))
        return {'id': did, 'decision': body.decision[:100]}

    @app.get('/v1/decisions')
    def list_decisions(actor=Depends(admin)):
        with engine.connect() as db:
            rows = db.execute(select(decisions)).mappings().all()
        return [dict(r) for r in rows]

    # -----------------------------------------------------------------------
    # Handoffs  (admin CRUD)
    # -----------------------------------------------------------------------

    @app.post('/v1/handoffs', status_code=201)
    def create_handoff(body: HandoffIn, actor=Depends(live_admin)):
        hid = str(uuid4())
        now = datetime.now(timezone.utc)
        with engine.begin() as db:
            db.execute(handoffs.insert().values(
                id=hid, from_device=actor['id'], project_id=body.project_id,
                summary=body.summary, next_action=body.next_action, created_at=now))
        return {'id': hid, 'summary': body.summary[:100]}

    @app.get('/v1/handoffs')
    def list_handoffs(actor=Depends(admin)):
        with engine.connect() as db:
            rows = db.execute(select(handoffs)).mappings().all()
        return [dict(r) for r in rows]

    # -----------------------------------------------------------------------
    # Retrieval
    # -----------------------------------------------------------------------

    @app.post('/v1/retrieve')
    def retrieve(body: ChatRequest, actor=Depends(live_admin)):
        with engine.connect() as db:
            ctx = retrieve_context(
                body.query,
                project_id=body.project_id,
                user_id=actor['id'],
                db_conn=db,
            )
        return ctx

    # -----------------------------------------------------------------------
    # Chat
    # -----------------------------------------------------------------------

    @app.post('/v1/chat')
    async def chat(body: ChatRequest, actor=Depends(live_admin)):
        with engine.connect() as db:
            ctx = retrieve_context(
                body.query,
                project_id=body.project_id,
                user_id=actor['id'],
                db_conn=db,
            )
        from .context_messages import build_messages
        messages = build_messages(body.query, ctx)
        # A provider failure must surface as a failure. Returning an error
        # string in 'answer' would make an outage indistinguishable from a
        # model reply (SPEC_AUDIT R9).
        try:
            result = await app.state.provider.complete(messages)
        except ProviderUnavailable as exc:
            raise HTTPException(503, f'Model provider unavailable: {exc}',
                                headers={'Retry-After': '30'})
        except ProviderError as exc:
            raise HTTPException(502, f'Model provider error: {exc}')
        return {
            'answer': result['answer'],
            'sources': ctx['sources'],
            'model_used': result['model_used'],
            'prompt_version': PROMPT_VERSION,
        }

    # -----------------------------------------------------------------------
    # Approvals and audit
    # -----------------------------------------------------------------------

    class ApprovalRequestIn(BaseModel):
        model_config = ConfigDict(extra='forbid')
        tool: str = Field(min_length=1, max_length=80)
        arguments: dict = Field(default_factory=dict)
        device_id: str | None = None
        reason: str | None = Field(default=None, max_length=500)
        ttl_minutes: int | None = Field(default=None, ge=1, le=1440)

    @app.get('/v1/approvals')
    def list_approvals(state: Optional[str] = None, actor=Depends(admin)):
        """List approval requests. Listing never grants anything."""
        return {'approvals': app.state.approvals.list(state)}

    @app.post('/v1/approvals', status_code=201)
    def request_approval(body: ApprovalRequestIn, actor=Depends(live_admin)):
        """Request approval for one L4 action. Grants nothing by itself."""
        try:
            result = app.state.approvals.request(
                actor['id'], body.tool, body.arguments, body.device_id,
                ttl=timedelta(minutes=body.ttl_minutes) if body.ttl_minutes else None,
                reason=body.reason)
        except PolicyDenied as exc:
            app.state.audit.record(actor['id'], 'approval.request',
                                   body.tool, exc.code)
            raise HTTPException(400, exc.detail)
        app.state.audit.record(actor['id'], 'approval.request', body.tool,
                               'pending', {'approval_id': result['id']})
        return result

    class ApprovalDecisionIn(BaseModel):
        model_config = ConfigDict(extra='forbid')
        approve: bool

    @app.post('/v1/approvals/{approval_id}/decide')
    def decide_approval(approval_id: str, body: ApprovalDecisionIn,
                        actor=Depends(admin)):
        """Approve or deny. The decision is recorded either way."""
        try:
            result = app.state.approvals.decide(approval_id, body.approve,
                                                actor['id'])
        except KeyError:
            raise HTTPException(404, 'Approval not found')
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        app.state.audit.record(
            actor['id'], 'approval.decide' if body.approve else 'approval.deny',
            result['tool'], result['state'], {'approval_id': approval_id})
        return result

    @app.get('/v1/audit')
    def list_audit(limit: int = Query(default=100, ge=1, le=500),
                   action: Optional[str] = None, actor=Depends(admin)):
        """Append-only audit trail."""
        return {'events': app.state.audit.list(limit=limit, action=action)}

    # -----------------------------------------------------------------------
    # Managed sessions and agent adapters
    # -----------------------------------------------------------------------

    @app.get('/v1/agents')
    def list_agents(actor=Depends(admin)):
        """Adapter health. Availability is probed, never assumed."""
        return {'adapters': app.state.adapters.healthcheck()}

    @app.get('/v1/tools')
    def list_tools(actor=Depends(admin)):
        """Registered tools with their autonomy level and gating."""
        return {'tools': [
            {'name': p.name, 'level': p.level, 'description': p.description,
             'requires_approval': p.requires_approval, 'reversible': p.reversible}
            for p in app.state.policy.registry.values()]}

    class LaunchAgentRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        agent: str = Field(min_length=1, max_length=80)
        objective: str = Field(min_length=1, max_length=4000)
        machine_id: str = Field(min_length=1, max_length=120)

    @app.post('/v1/sessions/{session_id}/launch-agent')
    def launch_agent(session_id: str, body: LaunchAgentRequest, actor=Depends(live_admin)):
        """Launch an adapter after the policy and kill-switch checks."""
        try:
            return app.state.sessions.launch(
                session_id, body.machine_id, body.agent, body.objective)
        except LaunchRefused as exc:
            raise HTTPException(exc.status, exc.detail)

    class VerifySessionRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        root: str | None = None
        fetch: bool = False
        test_commands: list[str] = Field(default_factory=list, max_length=20)

    @app.post('/v1/sessions/{session_id}/verify')
    def verify_session(session_id: str, body: VerifySessionRequest,
                       actor=Depends(live_admin)):
        """Run configured verification, then write a truthful handoff."""
        try:
            return app.state.sessions.verify_and_close(
                session_id, body.root, body.test_commands, fetch=body.fetch)
        except LaunchRefused as exc:
            raise HTTPException(exc.status, exc.detail)

    @app.post('/v1/sessions/{session_id}/handoff')
    def close_session(session_id: str, body: VerifySessionRequest,
                      actor=Depends(live_admin)):
        """Close the session. Same evidence contract as verify.

        Gated: a close writes a handoff and can run verification commands, so
        it is an action rather than a read.
        """
        return app.state.sessions.verify_and_close(
            session_id, body.root, body.test_commands, fetch=body.fetch)

    # -----------------------------------------------------------------------
    # Voice endpoints
    # -----------------------------------------------------------------------

    class SpeakRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        text: str = Field(min_length=1, max_length=4000)
        voice: str = Field(default='alloy')

    class ListenRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        audio_base64: str = Field(min_length=1)
        filename: str = Field(default='audio.webm')

    class VoiceChatRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        audio_base64: str = Field(min_length=1)
        filename: str = Field(default='audio.webm')
        voice: str = Field(default='alloy')
        project_id: str | None = None

    @app.post('/v1/voice/speak')
    async def speak(body: SpeakRequest, actor=Depends(live_admin)):
        """Convert text to speech. Returns audio/mpeg bytes."""
        try:
            audio = await app.state.voice.text_to_speech(body.text, body.voice)
        except ValueError as e:
            raise HTTPException(500, str(e))
        from fastapi.responses import Response
        return Response(content=audio, media_type='audio/mpeg')

    @app.post('/v1/voice/listen')
    async def listen(body: ListenRequest, actor=Depends(live_admin)):
        """Convert speech to text. Returns transcript."""
        import base64
        audio_bytes = base64.b64decode(body.audio_base64)
        try:
            transcript = await app.state.voice.speech_to_text(audio_bytes, body.filename)
        except ValueError as e:
            raise HTTPException(500, str(e))
        return {'transcript': transcript}

    @app.post('/v1/voice/chat')
    async def voice_chat(body: VoiceChatRequest, actor=Depends(live_admin)):
        """Full voice chat: speech → text → LLM → speech."""
        import base64
        audio_bytes = base64.b64decode(body.audio_base64)
        try:
            transcript = await app.state.voice.speech_to_text(audio_bytes, body.filename)
        except ValueError as e:
            raise HTTPException(500, str(e))

        with engine.connect() as db:
            ctx = retrieve_context(
                transcript,
                project_id=body.project_id,
                user_id=actor['id'],
                db_conn=db,
            )
        from .context_messages import build_messages
        messages = build_messages(transcript, ctx)
        result = await app.state.provider.complete(messages)

        try:
            audio = await app.state.voice.text_to_speech(result['answer'], body.voice)
        except ValueError as e:
            raise HTTPException(500, str(e))

        from fastapi.responses import Response
        return Response(
            content=audio,
            media_type='audio/mpeg',
            headers={
                'X-Transcript': transcript,
                'X-Answer': result['answer'][:500],
                'X-Model-Used': result['model_used'],
                'X-Prompt-Version': PROMPT_VERSION,
            },
        )

    # -----------------------------------------------------------------------
    # Kill switch
    # -----------------------------------------------------------------------

    @app.post('/v1/kill/activate', status_code=201)
    def activate_kill(body: KillActivate, actor=Depends(admin)):
        kid = str(uuid4())
        now = datetime.now(timezone.utc)
        with engine.begin() as db:
            db.execute(kill_switch_table.insert().values(
                id=kid, device_id=body.device_id, reason=body.reason,
                activated_at=now, activated_by=actor['id']))
        return {'id': kid, 'activated': True, 'device_id': body.device_id}

    @app.post('/v1/kill/deactivate/{kill_id}')
    def deactivate_kill(kill_id: UUID, actor=Depends(admin)):
        now = datetime.now(timezone.utc)
        with engine.begin() as db:
            result = db.execute(
                kill_switch_table.update()
                .where(kill_switch_table.c.id == str(kill_id))
                .where(kill_switch_table.c.deactivated_at.is_(None))
                .values(deactivated_at=now))
            if not result.rowcount:
                raise HTTPException(404, 'Kill switch not found or already deactivated')
        return {'id': str(kill_id), 'deactivated': True}

    @app.get('/v1/kill/status')
    def kill_status(actor=Depends(admin)):
        with engine.connect() as db:
            rows = db.execute(
                select(kill_switch_table)
                .where(kill_switch_table.c.deactivated_at.is_(None))
            ).mappings().all()
        return {'active': len(rows) > 0, 'entries': [dict(r) for r in rows]}

    # -----------------------------------------------------------------------
    # Self-improvement endpoints (Level-2 permission: proposals only)
    # -----------------------------------------------------------------------

    class AnalyzeRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        project_root: Optional[str] = None

    @app.post('/v1/self-improve/analyze')
    def run_analysis(body: AnalyzeRequest | None = None, actor=Depends(live_admin)):
        root = body.project_root if body and body.project_root else str(Path(__file__).resolve().parents[2])
        proposals = analyze_project(root)
        now = datetime.now(timezone.utc)
        stored = []
        with engine.begin() as db:
            for p in proposals:
                pid = str(uuid4())
                db.execute(improvement_proposals.insert().values(
                    id=pid, file_path=p.file_path,
                    proposal_json=proposal_to_json(p), status='pending',
                    created_at=now,
                ))
                stored.append({**p.to_dict(), 'id': pid})
        return {'level': LEVEL_DRAFT, 'count': len(stored), 'proposals': stored}

    @app.get('/v1/self-improve/proposals')
    def list_proposals(status: Optional[str] = None, actor=Depends(admin)):
        stmt = select(improvement_proposals)
        if status:
            stmt = stmt.where(improvement_proposals.c.status == status)
        with engine.connect() as db:
            rows = list(db.execute(stmt).mappings())
        result = []
        for row in rows:
            d = dict(row)
            d['proposal'] = proposal_from_json(d.pop('proposal_json'))
            result.append(d)
        return {'count': len(result), 'proposals': result}

    class ApplyRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        confirm: bool

    @app.post('/v1/self-improve/proposals/{proposal_id}/apply', status_code=202)
    def apply_proposal(proposal_id: UUID, body: ApplyRequest, actor=Depends(live_admin)):
        """Materialize a proposal as a reviewable patch.

        This does NOT change any file. JAX may propose and test, but it must not
        silently rewrite its own code, so the response reports applied=false
        and requires_review=true. Use the returned patch_ref to review and merge.
        """
        if not body.confirm:
            raise HTTPException(400, 'Explicit confirm=True is required to apply a proposal')
        with engine.connect() as db:
            row = db.execute(
                select(improvement_proposals)
                .where(improvement_proposals.c.id == str(proposal_id))
            ).mappings().first()
        if row is None:
            raise HTTPException(404, 'Proposal not found')
        if row['status'] != 'pending':
            raise HTTPException(409, f"Proposal is {row['status']}, not pending")

        proposal = proposal_from_json(row['proposal_json'])
        project_root = Path(os.environ.get('JAX_PROJECT_ROOTS', '.')).parts[0:1]
        root = Path(project_root[0]) if project_root else Path('.')
        # Prefer a configured root that actually contains the target.
        for candidate in os.environ.get('JAX_PROJECT_ROOTS', '').split(os.pathsep):
            if not candidate.strip():
                continue
            base = Path(candidate.strip())
            if base.exists() and proposal.get('file_path', '').startswith(str(base)):
                root = base
                break
        else:
            root = Path(row['file_path']).parent if row['file_path'] else Path('.')

        outcome = materialize_as_patch(proposal, root)
        now = datetime.now(timezone.utc)
        with engine.begin() as db:
            db.execute(
                improvement_proposals.update()
                .where(improvement_proposals.c.id == str(proposal_id))
                .where(improvement_proposals.c.status == 'pending')
                .values(status='applied', applied_at=now,
                        reviewer_note=outcome.reason[:500])
            )
        app.state.audit.record(actor['id'], 'self_improve.apply',
                               row['file_path'] or str(proposal_id),
                               outcome.status,
                               {'patch_ref': outcome.patch_ref,
                                'applied': outcome.applied})
        return {'id': str(proposal_id), **outcome.to_dict(),
                'applied_at': now.isoformat(),
                'note': 'No file was modified. Review the patch and merge it yourself.'}

    class RejectRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        note: str = ''

    @app.post('/v1/self-improve/proposals/{proposal_id}/reject')
    def reject_proposal(proposal_id: UUID, body: RejectRequest, actor=Depends(live_admin)):
        now = datetime.now(timezone.utc)
        with engine.begin() as db:
            result = db.execute(
                improvement_proposals.update()
                .where(improvement_proposals.c.id == str(proposal_id))
                .where(improvement_proposals.c.status == 'pending')
                .values(status='rejected', reviewer_note=body.note, applied_at=now)
            )
            if not result.rowcount:
                raise HTTPException(404, 'Proposal not found or not in pending state')
        return {'id': str(proposal_id), 'status': 'rejected', 'note': body.note}

    # -----------------------------------------------------------------------
    # Real estate leads — foreclosure / distressed seller finder
    # -----------------------------------------------------------------------

    lead_finder = LeadFinder()

    class LeadSearchRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        location: str = Field(min_length=2, max_length=200, description='City, state or zip code')
        search_type: str = Field(default='foreclosure')
        limit: int = Field(default=20, ge=1, le=50)
        analyze: bool = Field(default=True, description='Use LLM to extract and analyze leads')

    class LeadUpdateRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        status: Optional[str] = None
        notes: Optional[str] = None
        contact_info: Optional[str] = None

    @app.post('/v1/leads/search')
    async def search_leads(body: LeadSearchRequest, actor=Depends(live_admin)):
        """Search public web data for distressed property sellers."""
        search_data = await lead_finder.search(
            location=body.location,
            search_type=body.search_type,
            limit=body.limit,
        )

        analysis = None
        if body.analyze and search_data['results']:
            prompt = lead_finder.build_lead_prompt(
                body.location, search_data['results'], body.search_type
            )
            messages = [
                {'role': 'system', 'content': 'You are JAX, a real estate lead intelligence assistant. Be direct, specific, and actionable.'},
                {'role': 'user', 'content': prompt},
            ]
            try:
                result = await app.state.provider.complete(messages)
                analysis = result['answer']
            except Exception:
                analysis = None

        return {
            **search_data,
            'analysis': analysis,
        }

    @app.post('/v1/leads', status_code=201)
    def save_lead(body: dict, actor=Depends(live_admin)):
        """Manually save a lead to the database."""
        lid = str(uuid4())
        now = datetime.now(timezone.utc)
        with engine.begin() as db:
            db.execute(leads_table.insert().values(
                id=lid,
                user_id=actor['id'],
                address=body.get('address'),
                city=body.get('city'),
                state=body.get('state'),
                zip_code=body.get('zip_code'),
                owner_name=body.get('owner_name'),
                situation=body.get('situation', 'foreclosure'),
                contact_info=body.get('contact_info'),
                source_url=body.get('source_url'),
                source_query=body.get('source_query'),
                notes=body.get('notes'),
                status='new',
                raw_data=body.get('raw_data'),
                created_at=now,
            ))
        return {'id': lid, 'status': 'new'}

    @app.get('/v1/leads')
    def list_leads(status: Optional[str] = None, actor=Depends(admin)):
        """List saved leads, optionally filtered by status."""
        stmt = select(leads_table)
        if status:
            stmt = stmt.where(leads_table.c.status == status)
        stmt = stmt.order_by(leads_table.c.created_at.desc())
        with engine.connect() as db:
            rows = db.execute(stmt).mappings().all()
        return [dict(r) for r in rows]

    @app.put('/v1/leads/{lead_id}')
    def update_lead(lead_id: UUID, body: LeadUpdateRequest, actor=Depends(live_admin)):
        """Update lead status or notes."""
        now = datetime.now(timezone.utc)
        updates: dict = {'updated_at': now}
        if body.status is not None:
            updates['status'] = body.status
        if body.notes is not None:
            updates['notes'] = body.notes
        if body.contact_info is not None:
            updates['contact_info'] = body.contact_info
        with engine.begin() as db:
            result = db.execute(
                leads_table.update()
                .where(leads_table.c.id == str(lead_id))
                .values(**updates)
            )
            if not result.rowcount:
                raise HTTPException(404, 'Lead not found')
        return {'id': str(lead_id), 'updated': True}

    @app.delete('/v1/leads/{lead_id}')
    def delete_lead(lead_id: UUID, actor=Depends(live_admin)):
        with engine.begin() as db:
            result = db.execute(leads_table.delete().where(leads_table.c.id == str(lead_id)))
            if not result.rowcount:
                raise HTTPException(404, 'Lead not found')
        return {'id': str(lead_id), 'deleted': True}

    return app
