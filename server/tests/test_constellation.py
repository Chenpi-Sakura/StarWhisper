"""Tests for GET /api/constellation/{tradition}/{abbr} (T7 atlas tradition).

Covers:
- happy path on canonical `ori` (200 + unified envelope + atlas payload)
- case-insensitive lookup (ORI must succeed)
- 404 on unknown abbr (HTTP status AND envelope)
"""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_get_orion_ok():
    r = client.get("/api/constellation/western/ori")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["abbr"] == "ori"
    assert data["tradition"] == "western"
    # Batch D: name 改用简化后的中文 CSV.zh（"猎户座"），不再是英文 "Orion"
    assert data["name"] == "猎户座"
    assert data["name_zh"] == "猎户座"
    assert data["name_en"] == "Orion"
    # T9 (Batch C): stars/lines 数量从 MVP 5 的 8/10 扩展到 line endpoint 全量
    assert len(data["stars"]) >= 8
    assert len(data["lines"]) >= 10
    # Bayer 现在是 starnames.csv 的希腊字母（"α" / "β" 等），不再是 "Alpha Ori"
    bayer_values = [s["bayer"] for s in data["stars"].values()]
    non_empty_bayers = [b for b in bayer_values if b]
    # 至少要有 Betelgeuse (α) / Rigel (β) / Bellatrix (γ) / Mintaka (δ) / Alnilam (ε) / Alnitak (ζ) / Saiph (κ) / Meissa (λ)
    expected = {"α", "β", "γ", "δ", "ε", "ζ", "κ", "λ"}
    assert expected.issubset(set(non_empty_bayers)), (
        f"猎户 8 主星 bayer 缺失：expected-exists={expected - set(non_empty_bayers)}"
    )


def test_case_insensitive():
    """大写也能查到。"""
    r = client.get("/api/constellation/WESTERN/ORI")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["abbr"] == "ori"


def test_not_found_returns_404():
    r = client.get("/api/constellation/western/xyz")
    assert r.status_code == 404
    body = r.json()
    assert body["ok"] is False
    assert body["code"] == "CONSTELLATION_NOT_FOUND"
    assert "advice" in body


def test_wrong_tradition_returns_404():
    """不存在的 tradition（如 chxxx）→ 404 而非 422。"""
    r = client.get("/api/constellation/chxxx/ori")
    assert r.status_code == 404


def test_health_endpoint():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
