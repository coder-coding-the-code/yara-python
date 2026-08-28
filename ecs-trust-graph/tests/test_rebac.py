from ecs_trust.packs import EXPENSE_ORCH
from ecs_trust.seed import build_demo


def test_no_user_to_internal_agent_grant_edges():
    tm = build_demo()
    grants = [
        (u, d.get("relation"), v)
        for u, v, d in tm.graph.g.edges(data=True)
        if d.get("relation") == "GRANTED"
    ]
    assert ("user:zhangsan", "GRANTED", "pack:expense-orch") in grants
    assert not any(v == "agent:invoice-ocr" for _u, _r, v in grants)
    assert not any(v == "agent:erp-docs" for _u, _r, v in grants)


def test_snapshot_covers_expense_not_bank():
    tm = build_demo()
    snap = tm.graph.effective_snapshot("zhangsan", "expense-orch")
    assert "resource:expense-api" in snap["resources"]
    assert "resource:bank-pay-api" not in snap["resources"]
    assert "agent:erp-docs" in snap["egress"]
    assert "agent:invoice-ocr" not in snap["egress"]


def test_pack_members_match_roles():
    pack = EXPENSE_ORCH
    assert pack.entry == "agent:expense-orchestrator"
    assert "agent:invoice-ocr" in pack.workers
    assert set(pack.workers).isdisjoint(pack.egress_agents())
