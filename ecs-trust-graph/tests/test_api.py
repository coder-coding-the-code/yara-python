from fastapi.testclient import TestClient

from ecs_trust.api import create_app
from ecs_trust.seed import build_demo


def test_health_and_evaluate_via_http():
    client = TestClient(create_app(build_demo()))
    assert client.get("/api/health").json()["engine"] == "cedar-graph"
    payload = {
        "initiator_human_id": "zhangsan",
        "actor_agent_id": "erp-docs",
        "action": "submit",
        "resource_id": "expense-api",
        "amount": 1200,
        "delegation_chain": ["expense-orchestrator", "invoice-ocr", "erp-docs"],
    }
    res = client.post("/api/evaluate", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["allow"] is True
    graph = client.get("/api/graph").json()
    assert any(n["kind"] == "agent" for n in graph["nodes"])
    page = client.get("/")
    assert page.status_code == 200
    assert "Guardian Trust" in page.text
