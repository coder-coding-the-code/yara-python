"""Seed the v2 expense graph."""

from __future__ import annotations

from .cedar_authz import CedarEngine
from .graphstore import TrustGraph
from .manager import TrustManager
from .packs import default_packs, _oid


def build_demo() -> TrustManager:
    g = TrustGraph()
    g.add("user:zhangsan", "user", "张三", org="org:finance-demo", role="employee", status="active")
    g.add("user:lisi", "user", "李四", org="org:finance-demo", role="employee", status="active")
    g.add("user:wangwu", "user", "王五", org="org:finance-demo", role="finance_bp", status="active")
    g.add("user:zhaoliu", "user", "赵六", org="org:finance-demo", role="manager", status="active")

    g.add("agent:expense-orchestrator", "agent", "报销编排助手", role="entry")
    g.add("agent:invoice-ocr", "agent", "发票识别", role="worker")
    g.add("agent:erp-docs", "agent", "ERP 单据 Agent", role="egress")

    g.add("service_principal:orch-prod", "service_principal", "orch-prod", env="prod", status="active", agent="expense-orchestrator")
    g.add("service_principal:ocr-prod", "service_principal", "ocr-prod", env="prod", status="active", agent="invoice-ocr")
    g.add("service_principal:erp-docs-prod", "service_principal", "erp-docs-prod", env="prod", status="active", agent="erp-docs")

    g.add("connector:erp", "connector", "ERP 财务连接器")
    g.add("resource:expense-api", "resource", "报销单 API", classification="internal", risk_level="L2")
    g.add("resource:bank-pay-api", "resource", "银行付款 API", classification="restricted", risk_level="L4")
    g.add("resource:lisi-expense-doc", "resource", "李四报销单", classification="pii", risk_level="L2", personal=True)
    g.add("resource:zhangsan-expense-doc", "resource", "张三报销单", classification="pii", risk_level="L2", personal=True)

    g.edge("user:zhaoliu", "MANAGER", "user:zhangsan")
    g.edge("user:zhaoliu", "MANAGER", "user:lisi")
    g.edge("user:wangwu", "OWNS", "agent:expense-orchestrator")
    g.edge("user:wangwu", "OWNS", "agent:invoice-ocr")
    g.edge("user:wangwu", "OWNS", "agent:erp-docs")
    g.edge("agent:expense-orchestrator", "RUNS_AS", "service_principal:orch-prod")
    g.edge("agent:invoice-ocr", "RUNS_AS", "service_principal:ocr-prod")
    g.edge("agent:erp-docs", "RUNS_AS", "service_principal:erp-docs-prod")
    g.edge("service_principal:erp-docs-prod", "CAN_QUERY", "resource:expense-api")
    g.edge("service_principal:erp-docs-prod", "CAN_SUBMIT", "resource:expense-api")
    g.edge("user:zhangsan", "OWNS", "resource:zhangsan-expense-doc")
    g.edge("user:lisi", "OWNS", "resource:lisi-expense-doc")

    for pack in default_packs().values():
        g.put_pack(pack)
    g.grant("zhangsan", "expense-orch")
    g.grant("lisi", "expense-orch")

    errors = g.validate()
    if errors:
        raise ValueError("invalid trust graph: " + "; ".join(errors))
    return TrustManager(g, CedarEngine())
