"""3 个新端点单测。"""
import pytest
from fastapi.testclient import TestClient

from main import app
from services import traditions as _t

client = TestClient(app)


@pytest.fixture
def http_client():
    """复用模块级 TestClient，避免重新启动 app。"""
    return TestClient(app)


def test_traditions_endpoint():
    r = client.get("/api/traditions")
    assert r.status_code == 200
    by_key = {i["key"]: i for i in r.json()}
    assert "western" in by_key
    assert "chinese" in by_key
    assert by_key["western"]["count"] >= 5


def test_constellations_with_query():
    r = client.get("/api/constellations?tradition=western")
    assert r.status_code == 200
    body = r.json()
    assert body["tradition"] == "western"
    abbrs = {i["abbr"] for i in body["items"]}
    assert "ori" in abbrs


def test_constellations_missing_tradition():
    r = client.get("/api/constellations")
    assert r.status_code == 422


def test_constellation_detail_ok():
    r = client.get("/api/constellation/western/ori")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["abbr"] == "ori"
    assert body["tradition"] == "western"
    assert "stars" in body


def test_constellation_detail_404():
    r = client.get("/api/constellation/western/xxx")
    assert r.status_code == 404
    assert r.json()["code"] == "CONSTELLATION_NOT_FOUND"


def test_constellation_include_stories_default(http_client):
    """默认 include_stories=true，stories 不为 null。"""
    resp = http_client.get("/api/constellation/western/ori")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stories"] is not None
    assert "myth" in data["stories"]


def test_constellation_include_stories_false(http_client):
    """include_stories=false → stories 为 null。"""
    resp = http_client.get("/api/constellation/western/ori?include_stories=false")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stories"] is None


def test_constellations_includes_tradition_meta(http_client):
    """/api/constellations 响应顶层含 tradition_meta。"""
    resp = http_client.get("/api/constellations?tradition=western")
    assert resp.status_code == 200
    data = resp.json()
    assert "tradition_meta" in data
    assert data["tradition_meta"]["label"] == "西方星座"
    # 不应包含 count / key
    assert "count" not in data["tradition_meta"]
    assert "key" not in data["tradition_meta"]


def test_list_chinese_includes_group(monkeypatch):
    """list_constellations 返回每条带 group 字段（中国按四象/三垣/近南极分组）。"""
    monkeypatch.setattr(_t, "_load_all", lambda: None)
    monkeypatch.setattr(_t, "_DATA", {
        "chinese": {
            "shen_xiu": {"abbr": "shen_xiu", "name": "参宿", "latin": "Three Stars",
                         "season": "", "caption": "", "stars": {}, "stories": {}},
            "zi_wei_yuan": {"abbr": "zi_wei_yuan", "name": "紫微垣", "latin": "Purple Forbidden",
                            "season": "", "caption": "", "stars": {}, "stories": {},
                            "asterism_id": "zi_wei_yuan"},
        }
    })
    items = _t.list_constellations("chinese")
    groups = {it["abbr"]: it["group"] for it in items}
    assert groups["shen_xiu"] == "西方七宿"
    assert groups["zi_wei_yuan"] == "紫微垣"
