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
    assert "invoke_only" in reasons
    assert "user_grant" in reasons


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
    assert "无边" in result.reason


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
    tm.rebac.delete("agent:expense-orchestrator", "can_invoke", "agent:invoice-ocr")
    result = _eval(tm, amount=100)
    assert result.allow is False
    assert "can_invoke" in result.reason


def test_terminal_requires_user_grant():
    tm = build_demo()
    tm.rebac.delete("pack:expense-orch#grantee", "grant", "agent:erp-docs")
    tm.rebac.delete("agent:erp-docs", "user_granted", "pack:expense-orch")
    result = _eval(tm, amount=100)
    assert result.allow is False
    assert "require_user_grant" in result.reason


def test_tool_agent_cannot_hit_resource():
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


def test_scheme2_requires_grant_on_ocr():
    tm = build_demo()
    tm.rebac.delete("pack:expense-strict#grantee", "grant", "agent:invoice-ocr")
    tm.rebac.delete("agent:invoice-ocr", "user_granted", "pack:expense-strict")
    result = _eval(tm, amount=100, pack_id="expense-strict")
    assert result.allow is False
    allowed = _eval(build_demo(), amount=100, pack_id="expense-strict")
    assert allowed.allow is True


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


def test_user_grant_without_invoke_cannot_skip():
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


def test_max_depth():
    tm = build_demo()
    tm.packs["expense-orch"].max_depth = 1
    result = _eval(tm, amount=100)
    assert result.allow is False
    assert "max_depth" in result.reason
