from fastapi.testclient import TestClient

from main import app


def test_health_default():
    c = TestClient(app)
    r = c.get('/api/health')
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['astrometry'] in ('up', 'mock', 'down')
    assert body['ai_provider'] in ('up', 'disabled', 'down')
    assert 'ai_model' in body


def test_health_astrometry_mock(monkeypatch):
    monkeypatch.setattr('routers.health.ASTROMETRY_MOCK', True)
    c = TestClient(app)
    r = c.get('/api/health')
    assert r.json()['astrometry'] == 'mock'


def test_health_when_disabled(monkeypatch):
    """无 AI_API_KEY 时 ai_provider='disabled'（从 test_story.py 迁出：依赖 Task 5 挂载的 /api/health）"""
    monkeypatch.setattr('routers.health.AI_API_KEY', '')
    monkeypatch.setattr('routers.health.AGENTARTS_API_KEY', '')
    monkeypatch.setattr('routers.health.AGENTARTS_RUNTIME_NAME', '')

    c = TestClient(app)
    r = c.get('/api/health')
    assert r.status_code == 200
    data = r.json()
    assert data['ai_provider'] == 'disabled'
    # ai_model 在 disabled 时为 'none' 或空串
    assert data.get('ai_model') in (None, 'none', '')


def test_health_ai_disabled(monkeypatch):
    monkeypatch.setattr('routers.health.AI_API_KEY', '')
    monkeypatch.setattr('routers.health.AGENTARTS_API_KEY', '')
    monkeypatch.setattr('routers.health.AGENTARTS_RUNTIME_NAME', '')
    c = TestClient(app)
    r = c.get('/api/health')
    assert r.json()['ai_provider'] == 'disabled'


def test_health_ai_provider_up(monkeypatch):
    """AI_API_KEY 有值且 ping 通过 → ai_provider='up'"""
    monkeypatch.setattr('routers.health.AI_API_KEY', 'sk-test')

    class FakeProvider:
        async def health(self):
            return True

    monkeypatch.setattr('services.ai_provider.make_provider', lambda: FakeProvider())
    c = TestClient(app)
    r = c.get('/api/health')
    assert r.json()['ai_provider'] == 'up'


def test_health_ai_provider_down(monkeypatch):
    """AI_API_KEY 有值但 ping 失败 → ai_provider='down'"""
    monkeypatch.setattr('routers.health.AI_API_KEY', 'sk-test')

    class FakeProvider:
        async def health(self):
            return False

    monkeypatch.setattr('services.ai_provider.make_provider', lambda: FakeProvider())
    c = TestClient(app)
    r = c.get('/api/health')
    assert r.json()['ai_provider'] == 'down'