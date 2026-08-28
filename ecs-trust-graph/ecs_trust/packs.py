"""v2 capability packs: entitlement snapshot, not User→Agent expansion."""

from __future__ import annotations

from dataclasses import dataclass
import json

RISK_RANK = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}
LIMIT_TIERS = {"standard": 5000.0, "elevated": 20000.0, "unlimited": None}


def _oid(prefix: str, value: str) -> str:
    return value if ":" in value and value.split(":", 1)[0] in {
        "user", "agent", "pack", "resource", "service_principal", "connector",
    } else f"{prefix}:{value}"


@dataclass
class CapabilityPack:
    id: str
    display_name: str
    version: str
    entry: str
    workers: list[str]
    egress: dict[str, list[str]]
    workflow: list[tuple[str, str]]
    actions: list[str]
    resources: list[str]
    data_scope: str = "self"
    limit_tier: str = "standard"
    risk_cap: str = "L2"
    env: str = "prod"
    notes: str = ""

    def __post_init__(self) -> None:
        self.entry = _oid("agent", self.entry)
        self.workers = [_oid("agent", w) for w in self.workers]
        self.egress = {
            _oid("agent", a): [_oid("resource", r) for r in rs] for a, rs in self.egress.items()
        }
        self.workflow = [(_oid("agent", a), _oid("agent", b)) for a, b in self.workflow]
        self.resources = [_oid("resource", r) for r in self.resources]

    @property
    def object_id(self) -> str:
        return f"pack:{self.id}"

    @property
    def amount_limit(self) -> float | None:
        return LIMIT_TIERS[self.limit_tier]

    def members(self) -> set[str]:
        return {self.entry, *self.workers, *self.egress.keys()}

    def egress_agents(self) -> set[str]:
        return set(self.egress.keys())

    def capability_snapshot(self) -> dict:
        return {
            "resources": sorted(self.resources),
            "actions": sorted(self.actions),
            "data_scope": self.data_scope,
            "amount_limit": self.amount_limit,
            "risk_cap": self.risk_cap,
            "egress": {k: sorted(v) for k, v in sorted(self.egress.items())},
        }

    def capability_fingerprint(self) -> str:
        return json.dumps(self.capability_snapshot(), sort_keys=True, separators=(",", ":"))

    def topology_fingerprint(self) -> str:
        payload = {
            "entry": self.entry,
            "workers": sorted(self.workers),
            "workflow": [list(e) for e in self.workflow],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def intersect_snapshot(grant: dict, current: dict) -> dict:
    grant_e = grant.get("egress") or {}
    cur_e = current.get("egress") or {}
    egress = {}
    for agent, resources in grant_e.items():
        if agent in cur_e:
            egress[agent] = sorted(set(resources) & set(cur_e[agent]))
    g_limit = grant.get("amount_limit")
    c_limit = current.get("amount_limit")
    if g_limit is None:
        limit = c_limit
    elif c_limit is None:
        limit = g_limit
    else:
        limit = min(g_limit, c_limit)
    g_rank = RISK_RANK[grant["risk_cap"]]
    c_rank = RISK_RANK[current["risk_cap"]]
    risk_cap = grant["risk_cap"] if g_rank <= c_rank else current["risk_cap"]
    return {
        "resources": sorted(set(grant["resources"]) & set(current["resources"])),
        "actions": sorted(set(grant["actions"]) & set(current["actions"])),
        "data_scope": grant["data_scope"],
        "amount_limit": limit,
        "risk_cap": risk_cap,
        "egress": egress,
    }


def make_expense_orch() -> CapabilityPack:
    return CapabilityPack(
        id="expense-orch",
        display_name="报销编排包",
        version="1.0.0",
        entry="expense-orchestrator",
        workers=["invoice-ocr"],
        egress={"erp-docs": ["expense-api"]},
        workflow=[
            ("expense-orchestrator", "invoice-ocr"),
            ("invoice-ocr", "erp-docs"),
        ],
        actions=["query", "submit"],
        resources=["expense-api"],
        notes="A 入口 / B worker / C 出站；银行付款不在快照内",
    )


EXPENSE_ORCH = make_expense_orch()


def default_packs() -> dict[str, CapabilityPack]:
    return {"expense-orch": make_expense_orch()}
