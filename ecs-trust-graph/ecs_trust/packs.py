"""Capability packs: user-facing grants expanded into OpenFGA tuples."""

from __future__ import annotations

from dataclasses import dataclass

LIMIT_TIERS = {
    "standard": 5000.0,
    "elevated": 20000.0,
    "unlimited": None,
}

RISK_RANK = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}


@dataclass
class CapabilityPack:
    id: str
    display_name: str
    version: str
    entry: str
    members: list[str]
    user_granted: list[str]
    invoke_graph: list[tuple[str, str]]
    actions: list[str]
    data_scope: str = "self"
    limit_tier: str = "standard"
    risk_cap: str = "L2"
    max_depth: int = 2
    env: str = "prod"
    mode: str = "scheme1"
    notes: str = ""

    @property
    def object_id(self) -> str:
        return f"pack:{self.id}"

    @property
    def amount_limit(self) -> float | None:
        return LIMIT_TIERS[self.limit_tier]


EXPENSE_ORCH = CapabilityPack(
    id="expense-orch",
    display_name="报销编排包",
    version="1.0.0",
    entry="agent:expense-orchestrator",
    members=[
        "agent:expense-orchestrator",
        "agent:invoice-ocr",
        "agent:erp-docs",
    ],
    user_granted=[
        "agent:expense-orchestrator",
        "agent:erp-docs",
    ],
    invoke_graph=[
        ("agent:expense-orchestrator", "agent:invoice-ocr"),
        ("agent:invoice-ocr", "agent:erp-docs"),
    ],
    actions=["query", "submit"],
    data_scope="self",
    limit_tier="standard",
    risk_cap="L2",
    max_depth=2,
    notes="入口 A 强检，内部 OCR B 免检，末端 ERP C 强检",
)

EXPENSE_STRICT = CapabilityPack(
    id="expense-strict",
    display_name="报销强合规包（方案二）",
    version="1.0.0",
    entry="agent:expense-orchestrator",
    members=list(EXPENSE_ORCH.members),
    user_granted=list(EXPENSE_ORCH.members),
    invoke_graph=list(EXPENSE_ORCH.invoke_graph),
    actions=["query", "submit"],
    data_scope="self",
    limit_tier="standard",
    risk_cap="L2",
    max_depth=2,
    mode="scheme2",
    notes="包内全部节点 require_user_grant 等效：进入任一 Agent 都查 User→Agent",
)


def default_packs() -> dict[str, CapabilityPack]:
    return {p.id: p for p in (EXPENSE_ORCH, EXPENSE_STRICT)}
