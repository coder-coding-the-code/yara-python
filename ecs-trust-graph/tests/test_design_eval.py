"""Design scorecard: fail the suite if v2 regressions re-introduce v1 smells."""

from ecs_trust.seed import build_demo


def test_adding_worker_does_not_require_regrant():
    tm = build_demo()
    fp_before = tm.graph.grants[("user:zhangsan", "expense-orch")]["fingerprint"]
    tm.graph.add("agent:pdf-normalize", "agent", "PDF 规范化", role="worker")
    tm.graph.add(
        "service_principal:pdf-prod",
        "service_principal",
        "pdf-prod",
        env="prod",
        status="active",
        agent="pdf-normalize",
    )
    tm.graph.edge("agent:pdf-normalize", "RUNS_AS", "service_principal:pdf-prod")
    tm.add_worker("expense-orch", "pdf-normalize", "invoice-ocr")
    fp_after = tm.graph.packs["expense-orch"].capability_fingerprint()
    assert fp_before == fp_after
    assert tm.graph.validate() == []
    result = tm.evaluate(
        {
            "initiator_human_id": "zhangsan",
            "actor_agent_id": "erp-docs",
            "action": "submit",
            "resource_id": "expense-api",
            "amount": 500,
            "delegation_chain": [
                "expense-orchestrator",
                "invoice-ocr",
                "pdf-normalize",
                "erp-docs",
            ],
        }
    )
    assert result.allow is True


def test_expanding_capability_blocks_old_grant():
    tm = build_demo()
    tm.graph.edge("service_principal:erp-docs-prod", "CAN_SUBMIT", "resource:bank-pay-api")
    tm.graph.packs["expense-orch"].risk_cap = "L4"
    tm.expand_capability("expense-orch", "erp-docs", "bank-pay-api")
    old_fp = tm.graph.grants[("user:zhangsan", "expense-orch")]["fingerprint"]
    new_fp = tm.graph.packs["expense-orch"].capability_fingerprint()
    assert old_fp != new_fp
    result = tm.evaluate(
        {
            "initiator_human_id": "zhangsan",
            "actor_agent_id": "erp-docs",
            "action": "submit",
            "resource_id": "bank-pay-api",
            "amount": 100,
            "delegation_chain": ["expense-orchestrator", "invoice-ocr", "erp-docs"],
        }
    )
    assert result.allow is False
    tm.graph.grant("zhangsan", "expense-orch")
    allowed = tm.evaluate(
        {
            "initiator_human_id": "zhangsan",
            "actor_agent_id": "erp-docs",
            "action": "submit",
            "resource_id": "bank-pay-api",
            "amount": 100,
            "delegation_chain": ["expense-orchestrator", "invoice-ocr", "erp-docs"],
        }
    )
    assert allowed.decision in {"allow", "require_approval"}


def test_start_task_and_egress_are_split():
    tm = build_demo()
    started = tm.start_task("zhangsan", "expense-orch")
    assert started.allow and started.task_id
    assert tm.hop(started.task_id, "invoice-ocr").allow
    assert tm.hop(started.task_id, "erp-docs").allow
    egress = tm.authorize_egress(
        started.task_id,
        {"actor_agent_id": "erp-docs", "action": "submit", "resource_id": "expense-api", "amount": 200},
    )
    assert egress.allow is True


def test_cedar_reasons_present_on_allow():
    tm = build_demo()
    result = tm.evaluate(
        {
            "initiator_human_id": "zhangsan",
            "actor_agent_id": "erp-docs",
            "action": "query",
            "resource_id": "expense-api",
            "delegation_chain": ["expense-orchestrator", "invoice-ocr", "erp-docs"],
        }
    )
    assert result.allow
    assert result.reasons
