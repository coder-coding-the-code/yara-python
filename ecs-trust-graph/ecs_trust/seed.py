"""Seed the expense-assistant Trust Graph used across design-doc scenarios."""

from __future__ import annotations

from pathlib import Path

from .manager import TrustManager
from .packs import default_packs
from .rebac import ReBAC
from .registry import (
    AgentRecord,
    AgentRegistry,
    ConnectorRecord,
    HumanPrincipal,
    ResourceRecord,
    ServicePrincipalRecord,
)

MODEL_PATH = Path(__file__).resolve().parent.parent / "openfga" / "model.fga"


def build_demo() -> TrustManager:
    rebac = ReBAC.from_model_file(MODEL_PATH)
    registry = AgentRegistry()
    packs = default_packs()
    tm = TrustManager(rebac, registry, packs)

    registry.put_human(HumanPrincipal("zhangsan", "张三", "org:finance-demo", "张三", "employee"))
    registry.put_human(HumanPrincipal("lisi", "李四", "org:finance-demo", "李四", "employee"))
    registry.put_human(HumanPrincipal("wangwu", "王五", "org:finance-demo", "王五", "finance_bp"))
    registry.put_human(HumanPrincipal("zhaoliu", "赵六", "org:finance-demo", "赵六", "manager"))

    registry.put_agent(
        AgentRecord(
            "expense-orchestrator",
            "报销编排助手",
            "orchestrator",
            require_user_grant=True,
            is_entry=True,
            risk_level="L1",
        )
    )
    registry.put_agent(
        AgentRecord(
            "invoice-ocr",
            "发票识别",
            "tool",
            require_user_grant=False,
            risk_level="L1",
        )
    )
    registry.put_agent(
        AgentRecord(
            "erp-docs",
            "ERP 单据 Agent",
            "resource_access",
            require_user_grant=True,
            risk_level="L2",
        )
    )

    registry.put_sp(ServicePrincipalRecord("orch-prod", "expense-orchestrator", scopes=["orchestrate"]))
    registry.put_sp(ServicePrincipalRecord("ocr-prod", "invoice-ocr", scopes=["ocr"]))
    registry.put_sp(ServicePrincipalRecord("erp-docs-prod", "erp-docs", scopes=["expense.query", "expense.submit"]))

    registry.put_connector(ConnectorRecord("erp", "ERP 财务连接器", "ERP"))
    registry.put_resource(ResourceRecord("expense-api", "报销单 API", "internal", "L2"))
    registry.put_resource(ResourceRecord("bank-pay-api", "银行付款 API", "restricted", "L4"))
    registry.put_resource(ResourceRecord("lisi-expense-doc", "李四报销单", "pii", "L2", personal=True))
    registry.put_resource(ResourceRecord("zhangsan-expense-doc", "张三报销单", "pii", "L2", personal=True))

    r = rebac.write
    r("user:zhaoliu", "manager", "user:zhangsan")
    r("user:zhaoliu", "manager", "user:lisi")

    r("user:wangwu", "owner", "agent:expense-orchestrator")
    r("user:wangwu", "owner", "agent:invoice-ocr")
    r("user:wangwu", "owner", "agent:erp-docs")

    r("agent:expense-orchestrator", "entry", "pack:expense-orch")
    r("agent:expense-orchestrator", "member", "pack:expense-orch")
    r("agent:invoice-ocr", "member", "pack:expense-orch")
    r("agent:erp-docs", "member", "pack:expense-orch")
    r("agent:expense-orchestrator", "user_granted", "pack:expense-orch")
    r("agent:erp-docs", "user_granted", "pack:expense-orch")

    r("agent:expense-orchestrator", "entry", "pack:expense-strict")
    for agent in (
        "agent:expense-orchestrator",
        "agent:invoice-ocr",
        "agent:erp-docs",
    ):
        r(agent, "member", "pack:expense-strict")
        r(agent, "user_granted", "pack:expense-strict")

    r("user:zhangsan", "grantee", "pack:expense-orch")
    r("user:lisi", "grantee", "pack:expense-orch")
    r("user:zhangsan", "grantee", "pack:expense-strict")

    r("pack:expense-orch#grantee", "grant", "agent:expense-orchestrator")
    r("pack:expense-orch#grantee", "grant", "agent:erp-docs")
    r("pack:expense-strict#grantee", "grant", "agent:expense-orchestrator")
    r("pack:expense-strict#grantee", "grant", "agent:invoice-ocr")
    r("pack:expense-strict#grantee", "grant", "agent:erp-docs")

    r("agent:expense-orchestrator", "can_invoke", "agent:invoice-ocr")
    r("agent:invoice-ocr", "can_invoke", "agent:erp-docs")

    r("service_principal:orch-prod", "runs_as", "agent:expense-orchestrator")
    r("service_principal:ocr-prod", "runs_as", "agent:invoice-ocr")
    r("service_principal:erp-docs-prod", "runs_as", "agent:erp-docs")
    r("agent:expense-orchestrator", "in_pack", "pack:expense-orch")
    r("agent:invoice-ocr", "in_pack", "pack:expense-orch")
    r("agent:erp-docs", "in_pack", "pack:expense-orch")

    r("service_principal:erp-docs-prod", "can_use_connector", "connector:erp")
    r("service_principal:erp-docs-prod", "allowed_sp", "connector:erp")
    r("resource:expense-api", "can_access", "connector:erp")
    r("connector:erp#allowed_sp", "can_query", "resource:expense-api")
    r("connector:erp#allowed_sp", "can_submit", "resource:expense-api")

    r("user:zhangsan", "owner", "resource:zhangsan-expense-doc")
    r("user:lisi", "owner", "resource:lisi-expense-doc")
    return tm
