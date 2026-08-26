"""Runtime policy layer: depth, amount, risk, environment, obligations.

OpenFGA answers relationship questions. Amount caps, L0–L5 risk duties,
and max_depth live here (equivalent to an OPA/Cedar policy bundle).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .packs import RISK_RANK, CapabilityPack
from .registry import AgentRecord, ResourceRecord


@dataclass
class PolicyDecision:
    ok: bool
    obligations: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    risk_level: str = "L0"

    def deny(self, reason: str) -> "PolicyDecision":
        self.ok = False
        self.reasons.append(reason)
        return self

    def require(self, obligation: dict, reason: str) -> "PolicyDecision":
        self.ok = False
        self.obligations.append(obligation)
        self.reasons.append(reason)
        return self


def evaluate_policy(
    *,
    pack: CapabilityPack,
    chain: list[str],
    action: str,
    amount: float | None,
    env: str,
    resource: ResourceRecord,
    actor: AgentRecord,
    approval_ok: bool,
) -> PolicyDecision:
    decision = PolicyDecision(ok=True, risk_level=resource.risk_level)

    if env != pack.env:
        return decision.deny(f"环境不匹配: request.env={env} pack.env={pack.env}")

    hops = max(0, len(chain) - 1)
    if hops > pack.max_depth:
        return decision.deny(f"超过能力包 max_depth={pack.max_depth}（当前 {hops} 跳）")

    if action not in pack.actions:
        return decision.deny(f"动作 {action} 不在能力包 {pack.id} 允许列表 {pack.actions} 中")

    res_rank = RISK_RANK[resource.risk_level]
    cap_rank = RISK_RANK[pack.risk_cap]
    if res_rank > cap_rank:
        return decision.deny(
            f"资源风险 {resource.risk_level} 超过能力包上限 {pack.risk_cap}"
        )

    if not actor.require_user_grant and res_rank >= RISK_RANK["L3"]:
        return decision.deny("免检节点不得直连 L3+ 资源")

    if res_rank >= RISK_RANK["L5"]:
        return decision.deny("L5 工业/生命安全动作禁止模型或 Agent 直接执行")

    if res_rank >= RISK_RANK["L4"]:
        if approval_ok:
            decision.reasons.append("已持有双人审批票据，放行 L4")
        else:
            return decision.require(
                {
                    "type": "dual_control",
                    "resource": resource.object_id,
                    "risk_level": resource.risk_level,
                },
                "L4 高价值/不可逆动作需要双人审批",
            )

    if res_rank >= RISK_RANK["L3"] and not approval_ok:
        return decision.require(
            {
                "type": "human_approval",
                "resource": resource.object_id,
                "risk_level": resource.risk_level,
            },
            "L3 财务/客户/生产动作需要人工审批",
        )

    limit = pack.amount_limit
    if amount is not None and limit is not None and amount > limit:
        if approval_ok:
            decision.reasons.append(f"金额 {amount} 超过档位 {limit}，但已持有审批票据")
        else:
            return decision.require(
                {
                    "type": "human_approval",
                    "reason": "amount_limit",
                    "amount": amount,
                    "limit": limit,
                    "pack": pack.id,
                },
                f"金额 {amount} 超过能力包档位上限 {limit}，需要人工审批",
            )

    return decision
