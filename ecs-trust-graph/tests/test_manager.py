from ecs_trust.seed import build_demo


CHAIN = ["expense-orchestrator", "invoice-ocr", "erp-docs"]


def _eval(tm, **kwargs):
    body = {
        "initiator_human_id": "zhangsan",
        "actor_agent_id": "erp-docs",
        "action": "submit",
        "resource_id": "expense-api",
        "delegation_chain": CHAIN,
        "pack_id": "expense-orch",
        **kwargs,
    }
    return tm.evaluate(body)


def test_self_submit_allowed():
    result = _eval(build_demo(), amount=1200)
    assert result.allow is True
    assert result.decision == "allow"
    assert result.effective_identity["executing_sp"] == "service_principal:erp-docs-prod"
    reasons = " ".join(t["enter_reason"] for t in result.enter_trace)
    assert "topology_hop" in reasons
    assert "start_task" in reasons


def test_cross_person_denied_without_share():
    result = _eval(build_demo(), amount=1200, data_owner_id="lisi")
    assert result.allow is False
    assert "跨人" in result.reason


def test_cross_person_allowed_after_share():
    tm = build_demo()
    tm.share_data("lisi", "zhangsan")
    result = _eval(tm, action="query", data_owner_id="lisi", document_id="lisi-expense-doc")
    assert result.allow is True


def test_bank_pay_denied_no_edge():
    result = _eval(build_demo(), resource_id="bank-pay-api", amount=1200)
    assert result.allow is False
    assert result.allow is False


def test_over_limit_requires_approval_then_token_allows():
    tm = build_demo()
    pending = _eval(tm, amount=8000)
    assert pending.decision == "require_approval"
    assert pending.obligations[0]["type"] == "human_approval"
    token = tm.issue_approval(
        {
            "initiator_human_id": "zhangsan",
            "actor_agent_id": "erp-docs",
            "action": "submit",
            "resource_id": "expense-api",
            "amount": 8000,
        }
    )
    allowed = _eval(tm, amount=8000, obligation_tokens=[token.id])
    assert allowed.allow is True


def test_missing_invoke_edge_blocks_chain():
    tm = build_demo()
    pack = tm.graph.packs["expense-orch"]
    pack.workflow = [e for e in pack.workflow if e != ("agent:expense-orchestrator", "agent:invoice-ocr")]
    result = _eval(tm, amount=100)
    assert result.allow is False


def test_worker_cannot_egress():
    tm = build_demo()
    result = tm.evaluate(
        {
            "initiator_human_id": "zhangsan",
            "actor_agent_id": "invoice-ocr",
            "action": "submit",
            "resource_id": "expense-api",
            "amount": 100,
            "delegation_chain": ["expense-orchestrator", "invoice-ocr"],
        }
    )
    assert result.allow is False


def test_skip_ocr_blocked():
    tm = build_demo()
    result = tm.evaluate(
        {
            "initiator_human_id": "zhangsan",
            "actor_agent_id": "erp-docs",
            "action": "query",
            "resource_id": "expense-api",
            "delegation_chain": ["expense-orchestrator", "erp-docs"],
        }
    )
    assert result.allow is False


def test_offboard_zhangsan_keeps_lisi():
    tm = build_demo()
    tm.offboard_user("zhangsan")
    denied = _eval(tm, amount=1200)
    assert denied.allow is False
    lisi = tm.evaluate(
        {
            "initiator_human_id": "lisi",
            "actor_agent_id": "erp-docs",
            "action": "submit",
            "resource_id": "expense-api",
            "amount": 900,
            "delegation_chain": CHAIN,
        }
    )
    assert lisi.allow is True


def test_seed_rejects_worker_with_resource_edge():
    tm = build_demo()
    tm.graph.edge("service_principal:ocr-prod", "CAN_SUBMIT", "resource:expense-api")
    errors = tm.graph.validate()
    assert any("worker" in e for e in errors)
