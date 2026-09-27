"""Canonical specification regressions; isolated database, no remote providers."""
import pytest
from fastapi.testclient import TestClient
from core.app.main import create_app

TOKEN = 'isolated-spec-test-admin-token-long-enough'
AUTH = {'Authorization': f'Bearer {TOKEN}'}

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(database_url=f'sqlite:///{tmp_path}/test.db', admin_token=TOKEN)) as client:
        yield client

def test_memory_rejects_secret_before_persistence(client):
    response = client.post('/v1/memories', headers=AUTH, json={
        'kind': 'semantic', 'content': 'password: test-only-not-a-real-secret'})
    assert response.status_code == 422
    assert client.get('/v1/memories', headers=AUTH).json() == []


def test_chat_receives_identity_and_retrieved_evidence(client):
    class CaptureProvider:
        async def complete(self, messages):
            self.messages = messages
            return {'answer': 'test response', 'model_used': 'isolated-test'}
    provider = CaptureProvider()
    client.app.state.provider = provider
    client.post('/v1/memories', headers=AUTH, json={
        'kind': 'semantic', 'content': 'The lighthouse milestone is continuity.'})
    response = client.post('/v1/chat', headers=AUTH, json={'query': 'lighthouse'})
    assert response.status_code == 200
    assert 'Turn Your Chaos Into Code' in provider.messages[0]['content']
    assert any('The lighthouse milestone is continuity.' in m['content'] for m in provider.messages)
    assert provider.messages[-1] == {'role': 'user', 'content': 'lighthouse'}


def test_voice_chat_receives_same_identity_and_context(client):
    import base64
    class CaptureProvider:
        async def complete(self, messages):
            self.messages = messages
            return {'answer': 'test response', 'model_used': 'isolated-test'}
    class FakeVoice:
        async def speech_to_text(self, audio, filename):
            return 'lighthouse'
        async def text_to_speech(self, text, voice):
            return b'test-audio'
    provider = CaptureProvider()
    client.app.state.provider = provider
    client.app.state.voice = FakeVoice()
    client.post('/v1/memories', headers=AUTH, json={
        'kind': 'semantic', 'content': 'The lighthouse milestone is continuity.'})
    response = client.post('/v1/voice/chat', headers=AUTH, json={
        'audio_base64': base64.b64encode(b'test-input').decode()})
    assert response.status_code == 200
    assert 'Turn Your Chaos Into Code' in provider.messages[0]['content']
    assert any('The lighthouse milestone is continuity.' in m['content'] for m in provider.messages)




def test_preflight_requires_authentication(client):
    assert client.post('/v1/sessions/preflight', json={
        'project_id': '00000000-0000-0000-0000-000000000001'}).status_code == 401


def test_preflight_rejects_missing_project(client):
    assert client.post('/v1/sessions/preflight', headers=AUTH, json={
        'project_id': '00000000-0000-0000-0000-000000000001'}).status_code == 404


def test_preflight_refuses_unconfigured_root(client, tmp_path):
    project = client.post('/v1/projects', headers=AUTH, json={
        'name': 'isolated', 'path_hint': str(tmp_path)}).json()
    assert client.post('/v1/sessions/preflight', headers=AUTH, json={
        'project_id': project['id']}).status_code == 403

