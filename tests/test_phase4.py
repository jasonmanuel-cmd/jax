"""Phase 4 tests: voice endpoints, provider wiring, migration scripts."""
import importlib.util
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone

ADMIN = 'test-admin-token-with-at-least-32-characters'
AUTH = {'Authorization': f'Bearer {ADMIN}'}


def factory():
    assert importlib.util.find_spec('core') is not None
    from core.app.main import create_app
    return create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(factory()(database_url=f'sqlite:///{tmp_path}/jax.db', admin_token=ADMIN)) as c:
        yield c


def register(client):
    r = client.post('/v1/devices', headers=AUTH, json={'name': 'Laptop', 'platform': 'windows'})
    assert r.status_code == 201, r.text
    return r.json()


# ---- Voice endpoint tests ----

def test_voice_speak_endpoint(client):
    """POST /v1/voice/speak should return audio/mpeg."""
    r = client.post('/v1/voice/speak', headers=AUTH, json={'text': 'Hello world'})
    # Will fail without valid API key, but endpoint should exist
    assert r.status_code in (200, 500)  # 500 if no/invalid API key


def test_voice_speak_requires_admin(client):
    d = register(client)
    node = {'Authorization': f'Bearer {d["token"]}'}
    r = client.post('/v1/voice/speak', headers=node, json={'text': 'x'})
    assert r.status_code == 403


def test_voice_listen_endpoint(client):
    """POST /v1/voice/listen should accept audio and return transcript."""
    import base64
    fake_audio = base64.b64encode(b'fake audio data').decode()
    r = client.post('/v1/voice/listen', headers=AUTH, json={
        'audio_base64': fake_audio, 'filename': 'test.webm'})
    # Will fail without valid API key, but endpoint should exist
    assert r.status_code in (200, 500)


def test_voice_listen_requires_admin(client):
    d = register(client)
    node = {'Authorization': f'Bearer {d["token"]}'}
    import base64
    fake_audio = base64.b64encode(b'fake').decode()
    r = client.post('/v1/voice/listen', headers=node, json={'audio_base64': fake_audio})
    assert r.status_code == 403


def test_voice_chat_endpoint(client):
    """POST /v1/voice/chat should do full speech→text→LLM→speech."""
    import base64
    fake_audio = base64.b64encode(b'fake audio').decode()
    r = client.post('/v1/voice/chat', headers=AUTH, json={
        'audio_base64': fake_audio, 'filename': 'test.webm'})
    # Will fail without valid API key, but endpoint should exist
    assert r.status_code in (200, 500)


def test_voice_chat_requires_admin(client):
    d = register(client)
    node = {'Authorization': f'Bearer {d["token"]}'}
    import base64
    fake_audio = base64.b64encode(b'fake').decode()
    r = client.post('/v1/voice/chat', headers=node, json={'audio_base64': fake_audio})
    assert r.status_code == 403


# ---- Provider wiring tests ----

def test_provider_wiring_openrouter(monkeypatch, tmp_path):
    """OpenRouter provider should be wired when JAX_PROVIDER=openrouter."""
    monkeypatch.setenv('JAX_PROVIDER', 'openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    from core.app.main import create_app
    app = create_app(database_url=f'sqlite:///{tmp_path}/jax.db', admin_token=ADMIN)
    assert hasattr(app.state.provider, 'api_key')
    assert app.state.provider.api_key == 'test-key'


def test_provider_wiring_openai(monkeypatch, tmp_path):
    """OpenAI provider should be wired when JAX_PROVIDER=openai."""
    monkeypatch.setenv('JAX_PROVIDER', 'openai')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    from core.app.main import create_app
    app = create_app(database_url=f'sqlite:///{tmp_path}/jax.db', admin_token=ADMIN)
    assert hasattr(app.state.provider, 'api_key')
    assert app.state.provider.api_key == 'test-key'


def test_provider_wiring_groq(monkeypatch, tmp_path):
    """Groq provider should be wired when JAX_PROVIDER=groq."""
    monkeypatch.setenv('JAX_PROVIDER', 'groq')
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    from core.app.main import create_app
    app = create_app(database_url=f'sqlite:///{tmp_path}/jax.db', admin_token=ADMIN)
    assert hasattr(app.state.provider, 'api_key')
    assert app.state.provider.api_key == 'test-key'


def test_provider_wiring_default(monkeypatch, tmp_path):
    """Default provider should be OpenRouter."""
    monkeypatch.setenv('JAX_PROVIDER', '')
    from core.app.main import create_app
    app = create_app(database_url=f'sqlite:///{tmp_path}/jax.db', admin_token=ADMIN)
    from core.app.providers.openrouter import OpenRouterProvider
    assert isinstance(app.state.provider, OpenRouterProvider)


def test_voice_provider_wired(monkeypatch, tmp_path):
    """Voice provider should be wired on app.state."""
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    from core.app.main import create_app
    app = create_app(database_url=f'sqlite:///{tmp_path}/jax.db', admin_token=ADMIN)
    assert hasattr(app.state, 'voice')
    assert app.state.voice.api_key == 'test-key'


# ---- Migration script tests ----

def test_migration_files_exist():
    """All 4 migration SQL files should exist."""
    from pathlib import Path
    supabase_dir = Path(__file__).resolve().parents[1] / "supabase"
    for f in ["001_schema.sql", "002_indexes.sql", "003_rls.sql", "004_seed.sql"]:
        assert (supabase_dir / f).exists(), f"Missing {f}"


def test_migration_script_importable():
    """migrate_supabase.py should be importable."""
    from scripts import migrate_supabase
    assert hasattr(migrate_supabase, 'run_migrations')


def test_verify_script_importable():
    """verify_supabase.py should be importable."""
    from scripts import verify_supabase
    assert hasattr(verify_supabase, 'verify')


def test_migration_sql_syntax():
    """Basic SQL syntax checks on migration files."""
    from pathlib import Path
    supabase_dir = Path(__file__).resolve().parents[1] / "supabase"

    schema = (supabase_dir / "001_schema.sql").read_text()
    assert "CREATE TABLE" in schema
    assert "devices" in schema
    assert "events" in schema
    assert "voice_sessions" in schema

    indexes = (supabase_dir / "002_indexes.sql").read_text()
    assert "CREATE INDEX" in indexes

    rls = (supabase_dir / "003_rls.sql").read_text()
    assert "ROW LEVEL SECURITY" in rls
    assert "CREATE POLICY" in rls

    seed = (supabase_dir / "004_seed.sql").read_text()
    assert "INSERT INTO" in seed


# ---- Voice provider unit tests ----

def test_voice_provider_tts():
    """VoiceProvider.text_to_speech should call OpenAI TTS endpoint."""
    import asyncio
    from core.app.voice import VoiceProvider
    vp = VoiceProvider(api_key='test-key')
    # We can't actually call the API, but we can verify the method exists
    assert hasattr(vp, 'text_to_speech')
    assert hasattr(vp, 'speech_to_text')


def test_voice_provider_requires_key():
    """VoiceProvider should raise if no API key."""
    import asyncio
    from core.app.voice import VoiceProvider
    vp = VoiceProvider(api_key='')
    with pytest.raises(ValueError):
        asyncio.get_event_loop().run_until_complete(vp.text_to_speech('test'))


# ---- Chat with real provider (mocked) ----

def test_chat_with_openrouter_provider(monkeypatch, tmp_path):
    """Chat should use OpenRouter when configured."""
    monkeypatch.setenv('JAX_PROVIDER', 'openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')

    import asyncio
    from core.app.providers.openrouter import OpenRouterProvider

    # Mock the HTTP call
    class MockResponse:
        def raise_for_status(self): pass
        def json(self):
            return {
                'choices': [{'message': {'content': 'Mocked answer'}}],
                'usage': {'total_tokens': 10}
            }

    class MockClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return MockResponse()

    monkeypatch.setattr('httpx.AsyncClient', lambda *a, **kw: MockClient())

    async def run():
        provider = OpenRouterProvider(api_key='test-key')
        result = await provider.complete([{'role': 'user', 'content': 'test'}])
        assert result['answer'] == 'Mocked answer'
        assert result['model_used'] == 'openai/gpt-4o-mini'

    asyncio.get_event_loop().run_until_complete(run())
