from ecs_trust.dsl import DirectUserset, UnionRewrite, parse_dsl, parse_rewrite
from ecs_trust.seed import MODEL_PATH, build_demo


def test_type_restriction_keeps_hash_userset():
    rewrite = parse_rewrite("[user, pack#grantee]")
    assert rewrite == DirectUserset(("user", "pack#grantee"))


def test_model_parses_resource_viewer():
    model = parse_dsl(MODEL_PATH.read_text(encoding="utf-8"))
    viewer = model.rewrite("resource", "viewer")
    assert isinstance(viewer, UnionRewrite)
    kinds = [type(c).__name__ for c in viewer.children]
    assert "ComputedUserset" in kinds
    assert "TupleToUserset" in kinds


def test_pack_grant_expands_to_entry_and_terminal():
    tm = build_demo()
    orch = tm.pack("expense-orch")
    strict = tm.pack("expense-strict")
    assert tm.has_user_grant("user:zhangsan", "agent:expense-orchestrator", orch)
    assert tm.has_user_grant("user:zhangsan", "agent:erp-docs", orch)
    assert not tm.has_user_grant("user:zhangsan", "agent:invoice-ocr", orch)
    assert tm.has_user_grant("user:zhangsan", "agent:invoice-ocr", strict)


def test_invoke_edges():
    tm = build_demo()
    assert tm.check("agent:expense-orchestrator", "can_invoke", "agent:invoice-ocr")
    assert tm.check("agent:invoice-ocr", "can_invoke", "agent:erp-docs")
    assert not tm.check("agent:expense-orchestrator", "can_invoke", "agent:erp-docs")


def test_sp_can_submit_expense_not_bank():
    tm = build_demo()
    sp = "service_principal:erp-docs-prod"
    assert tm.check(sp, "can_submit", "resource:expense-api")
    assert tm.check(sp, "can_query", "resource:expense-api")
    assert not tm.check(sp, "can_submit", "resource:bank-pay-api")
    assert not tm.check("service_principal:ocr-prod", "can_submit", "resource:expense-api")


def test_document_viewer_owner_manager_share():
    tm = build_demo()
    assert tm.check("user:lisi", "viewer", "resource:lisi-expense-doc")
    assert not tm.check("user:zhangsan", "viewer", "resource:lisi-expense-doc")
    assert tm.check("user:zhaoliu", "viewer", "resource:lisi-expense-doc")
    tm.share_data("lisi", "zhangsan")
    assert tm.check("user:zhangsan", "viewer", "resource:lisi-expense-doc")
