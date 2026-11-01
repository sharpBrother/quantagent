from fastapi.testclient import TestClient

from quantagent_frankenstein.api.app import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_analyze():
    r = client.post("/api/analyze", json={"symbol": "DEMO", "lookback_days": 90})
    assert r.status_code == 200
    body = r.json()
    assert "signals" in body and "brief" in body
    assert len(body["brief"]["risks"]) >= 2
