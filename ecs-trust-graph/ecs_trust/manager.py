"""Trust Manager: orchestrates OpenFGA Checks + Registry + policy (scheme 1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import uuid

import networkx as nx

from .packs import CapabilityPack
from .policy import evaluate_policy
from .rebac import ReBAC
from .registry import AgentRegistry, _bare


def _oid(prefix: str, value: str) -> str:
    return value if value.startswith(prefix + ":") else f"{prefix}:{value}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ObligationToken:
    id: str
    initiator: str
    actor_agent: str
    action: str
    resource: str
    amount: float | None
    expires_at: datetime
    kind: str = "human_approval"

    def valid_at(self, ts: datetime) -> bool:
        return ts <= self.expires_at


@dataclass
class AuditRecord:
    id: str
    ts: str
    decision: str
    allow: bool
    initiator: str
    actor: str
    action: str
    resource: str
    payload: dict


@dataclass
class EvaluateResult:
    allow: bool
    decision: str
    reason: str
    reasons: list[str]
    effective_identity: dict
    effective_scope: dict
    risk_level: str
    obligations: list[dict]
    path: list[dict]
    enter_trace: list[dict]
    pack_id: str | None
    pack_version: str | None
    audit_id: str


class TrustManager:
    def __init__(self, rebac: ReBAC, registry: AgentRegistry, packs: dict[str, CapabilityPack]):
        self.rebac = rebac
        self.registry = registry
        self.packs = packs
        self.tokens: dict[str, ObligationToken] = {}
        self.audit: list[AuditRecord] = []

    def check(self, user: str, relation: str, object_: str) -> bool:
        return self.rebac.check(user, relation, object_)

    def has_tuple(self, user: str, relation: str, object_: str) -> bool:
        return any(
            t.user == user and t.relation == relation and t.object == object_ for t in self.rebac.tuples()
        )

    def has_user_grant(self, user: str, agent: str, pack: CapabilityPack) -> bool:
        """User grant scoped to the current pack (direct DELEGATES_TO or pack expansion)."""
        user = _oid("user", user)
        agent = _oid("agent", agent)
        if self.has_tuple(user, "grant", agent):
            return True
        return self.check(user, "grantee", pack.object_id) and (
            self.check(agent, "user_granted", pack.object_id)
            or self.has_tuple(f"{pack.object_id}#grantee", "grant", agent)
        )

    def pack(self, pack_id: str | None) -> CapabilityPack:
        pid = pack_id or "expense-orch"
        pid = pid.split(":", 1)[-1] if pid.startswith("pack:") else pid
        if pid not in self.packs:
            raise KeyError(f"unknown pack {pack_id}")
        return self.packs[pid]

    def can_enter(
        self,
        user: str,
        agent: str,
        *,
        caller: str | None = None,
        pack_id: str | None = None,
        chain: list[str] | None = None,
    ) -> dict:
        pack = self.pack(pack_id)
        user = _oid("user", user)
        agent = _oid("agent", agent)
        caller = _oid("agent", caller) if caller else None
        reasons: list[str] = []
        rec = self.registry.agent(agent)

        if rec.status != "active":
            return _deny_enter("agent_inactive", f"Agent {agent} 已停用", pack)

        if not self.check(agent, "member", pack.object_id):
            return _deny_enter("not_in_pack", f"{agent} 不在能力包 {pack.id} 白名单中", pack)

        hops = max(0, len(chain or [agent]) - 1)
        if hops > pack.max_depth:
            return _deny_enter("max_depth", f"超过 max_depth={pack.max_depth}", pack)

        require_grant = rec.require_user_grant or pack.mode == "scheme2"

        if caller is None:
            if not rec.is_entry and agent != pack.entry:
                return _deny_enter("not_entry", f"{agent} 不是能力包入口 {pack.entry}", pack)
            if not self.has_user_grant(user, agent, pack):
                return _deny_enter("missing_user_grant", f"缺少 {user} → {agent} 授权（含能力包展开）", pack)
            return {
                "allow": True,
                "enter_reason": "user_grant",
                "require_user_grant": True,
                "reasons": [f"入口检查通过: {user} can_use {agent}"],
                "pack_id": pack.id,
            }

        if not self.check(caller, "can_invoke", agent):
            return _deny_enter("missing_invoke", f"缺少调用边 {caller} can_invoke {agent}", pack)

        if require_grant:
            if not self.has_user_grant(user, agent, pack):
                return _deny_enter(
                    "missing_user_grant",
                    f"{agent} 标记 require_user_grant，但缺少 {user} 对本包内 {agent} 的授权",
                    pack,
                )
            enter_reason = "user_grant+invoke"
            reasons.append(f"调用边 {caller}→{agent} 成立，且用户强检通过")
        else:
            enter_reason = "invoke_only"
            reasons.append(f"调用边 {caller}→{agent} 成立，{agent} 免检（不查 User→Agent）")

        return {
            "allow": True,
            "enter_reason": enter_reason,
            "require_user_grant": require_grant,
            "reasons": reasons,
            "pack_id": pack.id,
        }

    def evaluate(self, request: dict) -> EvaluateResult:
        initiator = _oid("user", request["initiator_human_id"])
        actor = _oid("agent", request["actor_agent_id"])
        action = request["action"]
        resource = _oid("resource", request["resource_id"])
        data_owner = request.get("data_owner_id")
        data_owner = _oid("user", data_owner) if data_owner else initiator
        amount = request.get("amount")
        env = request.get("env") or "prod"
        pack = self.pack(request.get("pack_id"))
        caller = request.get("caller_agent_id")
        chain = [_oid("agent", a) for a in (request.get("delegation_chain") or [actor])]
        if chain[-1] != actor:
            chain.append(actor)
        now = request.get("now") or _now()
        if isinstance(now, str):
            now = datetime.fromisoformat(now.replace("Z", "+00:00"))

        path: list[dict] = []
        enter_trace: list[dict] = []
        reasons: list[str] = []

        for idx, agent in enumerate(chain):
            hop_caller = chain[idx - 1] if idx else None
            if idx == 0:
                hop_caller = None
            entered = self.can_enter(
                initiator,
                agent,
                caller=hop_caller,
                pack_id=pack.id,
                chain=chain[: idx + 1],
            )
            enter_trace.append({"agent": agent, "caller": hop_caller, **entered})
            if not entered["allow"]:
                return self._finish(
                    False,
                    "deny",
                    entered["reason"],
                    entered.get("reasons", [entered["reason"]]),
                    initiator,
                    actor,
                    action,
                    resource,
                    {},
                    {},
                    "L0",
                    [],
                    path,
                    enter_trace,
                    pack,
                    request,
                )
            path.append(
                {
                    "kind": "enter",
                    "agent": agent,
                    "caller": hop_caller,
                    "enter_reason": entered["enter_reason"],
                }
            )
            reasons.extend(entered.get("reasons") or [])

        sp = self.registry.sp_for_agent(actor, env)
        if sp is None:
            return self._finish(
                False,
                "deny",
                f"{actor} 在 {env} 没有可用 Service Principal",
                [f"{actor} 在 {env} 没有可用 Service Principal"],
                initiator,
                actor,
                action,
                resource,
                {},
                {},
                "L0",
                [],
                path,
                enter_trace,
                pack,
                request,
            )

        sp_id = sp.object_id
        relation = "can_submit" if action == "submit" else "can_query"
        if action not in ("query", "submit"):
            return self._finish(
                False,
                "deny",
                f"不支持的动作 {action}",
                [f"不支持的动作 {action}，FGA 粗关系仅 can_query/can_submit"],
                initiator,
                actor,
                action,
                resource,
                {"initiator": initiator, "agent": actor, "sp": sp_id},
                {},
                "L0",
                [],
                path,
                enter_trace,
                pack,
                request,
            )

        if not self.check(sp_id, relation, resource):
            return self._finish(
                False,
                "deny",
                f"无边：{sp_id} {relation} {resource}（零信任默认拒绝）",
                [f"Service Principal {sp_id} 不能 {relation} {resource}"],
                initiator,
                actor,
                action,
                resource,
                {"initiator": initiator, "agent": actor, "sp": sp_id, "env": env},
                {},
                self.registry.resource(_bare(resource, "resource")).risk_level,
                [],
                path,
                enter_trace,
                pack,
                request,
            )
        path.append({"kind": "access", "sp": sp_id, "relation": relation, "resource": resource})
        reasons.append(f"资源路径成立: {sp_id} {relation} {resource}")

        if pack.data_scope == "self" and data_owner != initiator:
            doc = request.get("document_id")
            viewer_ok = False
            viewer_obj = None
            if doc:
                viewer_obj = _oid("resource", doc)
                viewer_ok = self.check(initiator, "viewer", viewer_obj)
            if not viewer_ok:
                return self._finish(
                    False,
                    "deny",
                    "跨人数据访问缺少独立依据（组织权 / 分享 / 审批）",
                    [
                        f"data_owner={data_owner} ≠ initiator={initiator}",
                        "能力包 data_scope=self，且不存在 resource.viewer 关系",
                    ],
                    initiator,
                    actor,
                    action,
                    resource,
                    {"initiator": initiator, "agent": actor, "sp": sp_id, "data_owner": data_owner},
                    {"owners": [initiator], "actions": pack.actions},
                    self.registry.resource(_bare(resource, "resource")).risk_level,
                    [],
                    path,
                    enter_trace,
                    pack,
                    request,
                )
            path.append({"kind": "cross_person", "viewer": initiator, "document": viewer_obj})
            reasons.append(f"跨人访问依据: {initiator} viewer {viewer_obj}")
        else:
            reasons.append(f"数据范围匹配: owners 含 {data_owner}")

        actor_rec = self.registry.agent(actor)
        resource_rec = self.registry.resource(resource)
        approval_ok = self._approval_ok(request, initiator, actor, action, resource, amount, now)
        policy = evaluate_policy(
            pack=pack,
            chain=chain,
            action=action,
            amount=amount,
            env=env,
            resource=resource_rec,
            actor=actor_rec,
            approval_ok=approval_ok,
        )
        reasons.extend(policy.reasons)
        identity = {
            "initiator": initiator,
            "entry_agent": chain[0],
            "calling_agent": chain[-2] if len(chain) > 1 else None,
            "executing_agent": actor,
            "executing_sp": sp_id,
            "data_owner": data_owner,
            "env": env,
        }
        scope = {
            "actions": pack.actions,
            "owners": [initiator] if pack.data_scope == "self" else ["*"],
            "amount_limit": pack.amount_limit,
            "risk_cap": pack.risk_cap,
            "pack": pack.id,
        }
        if not policy.ok:
            decision = "require_approval" if policy.obligations else "deny"
            return self._finish(
                False,
                decision,
                policy.reasons[-1] if policy.reasons else "策略拒绝",
                reasons,
                initiator,
                actor,
                action,
                resource,
                identity,
                scope,
                policy.risk_level,
                policy.obligations,
                path,
                enter_trace,
                pack,
                request,
            )

        return self._finish(
            True,
            "allow",
            "允许",
            reasons,
            initiator,
            actor,
            action,
            resource,
            identity,
            scope,
            policy.risk_level,
            policy.obligations,
            path,
            enter_trace,
            pack,
            request,
        )

    def issue_approval(self, request: dict, ttl_seconds: int = 3600) -> ObligationToken:
        now = _now()
        token = ObligationToken(
            id=f"ob-{uuid.uuid4().hex[:12]}",
            initiator=_oid("user", request["initiator_human_id"]),
            actor_agent=_oid("agent", request["actor_agent_id"]),
            action=request["action"],
            resource=_oid("resource", request["resource_id"]),
            amount=request.get("amount"),
            expires_at=now + timedelta(seconds=ttl_seconds),
            kind=request.get("kind") or "human_approval",
        )
        self.tokens[token.id] = token
        return token

    def offboard_user(self, user_id: str) -> dict:
        user = _oid("user", user_id)
        removed = self.rebac.delete_matching(user=user)
        human = self.registry.humans.get(_bare(user, "user"))
        if human:
            human.status = "offboarded"
        blast = self.blast_radius(user)
        return {"user": user, "tuples_removed": removed, "blast_radius": blast}

    def share_data(self, owner: str, viewer: str) -> None:
        owner = _oid("user", owner)
        viewer = _oid("user", viewer)
        self.rebac.write(viewer, "data_viewer", owner)

    def blast_radius(self, node: str) -> dict:
        graph = self.as_networkx()
        if node not in graph:
            return {"node": node, "reachable": [], "edges": 0}
        reachable = nx.descendants(graph, node)
        subgraph = graph.subgraph({node, *reachable})
        return {
            "node": node,
            "reachable": sorted(reachable),
            "node_count": subgraph.number_of_nodes(),
            "edge_count": subgraph.number_of_edges(),
            "agents": sorted(n for n in reachable if n.startswith("agent:")),
            "packs": sorted(n for n in reachable if n.startswith("pack:")),
            "resources": sorted(n for n in reachable if n.startswith("resource:")),
        }

    def as_networkx(self) -> nx.DiGraph:
        g = nx.DiGraph()
        for h in self.registry.humans.values():
            g.add_node(h.object_id, kind="user", label=h.display_name, status=h.status)
        for a in self.registry.agents.values():
            g.add_node(
                a.object_id,
                kind="agent",
                label=a.display_name,
                require_user_grant=a.require_user_grant,
                status=a.status,
            )
        for sp in self.registry.sps.values():
            g.add_node(sp.object_id, kind="service_principal", label=sp.id, env=sp.env)
        for c in self.registry.connectors.values():
            g.add_node(c.object_id, kind="connector", label=c.display_name)
        for r in self.registry.resources.values():
            g.add_node(r.object_id, kind="resource", label=r.display_name, risk=r.risk_level)
        for p in self.packs.values():
            g.add_node(p.object_id, kind="pack", label=p.display_name)
        for t in self.rebac.tuples():
            src = t.user.split("#", 1)[0]
            g.add_node(src, kind=src.split(":", 1)[0])
            g.add_node(t.object, kind=t.object.split(":", 1)[0])
            g.add_edge(src, t.object, relation=t.relation, userset=t.user)
        return g

    def graph_payload(self) -> dict:
        g = self.as_networkx()
        kind_order = ["user", "pack", "agent", "service_principal", "connector", "resource", "organization"]
        buckets: dict[str, list[str]] = {k: [] for k in kind_order}
        for nid, data in g.nodes(data=True):
            kind = data.get("kind") or nid.split(":", 1)[0]
            buckets.setdefault(kind, []).append(nid)
        positions: dict[str, tuple[float, float]] = {}
        row_gap, col_gap, x0, y0 = 150.0, 88.0, 70.0, 48.0
        for row, kind in enumerate([k for k in kind_order if buckets.get(k)]):
            nodes = sorted(buckets[kind])
            for col, nid in enumerate(nodes):
                positions[nid] = (x0 + col * col_gap, y0 + row * row_gap)
        nodes = []
        for nid, data in g.nodes(data=True):
            x, y = positions.get(nid, (40.0, 40.0))
            nodes.append(
                {
                    "id": nid,
                    "kind": data.get("kind") or nid.split(":", 1)[0],
                    "label": data.get("label") or nid,
                    "status": data.get("status"),
                    "require_user_grant": data.get("require_user_grant"),
                    "risk": data.get("risk"),
                    "x": x,
                    "y": y,
                }
            )
        edges = [
            {
                "from": u,
                "to": v,
                "relation": d.get("relation"),
            }
            for u, v, d in g.edges(data=True)
        ]
        return {"nodes": nodes, "edges": edges, "width": 980, "height": 620}

    def _approval_ok(
        self,
        request: dict,
        initiator: str,
        actor: str,
        action: str,
        resource: str,
        amount: float | None,
        now: datetime,
    ) -> bool:
        tokens = request.get("obligation_tokens") or []
        for tid in tokens:
            tok = self.tokens.get(tid)
            if tok is None or not tok.valid_at(now):
                continue
            if tok.initiator == initiator and tok.actor_agent == actor and tok.action == action and tok.resource == resource:
                if tok.amount is None or amount is None or tok.amount >= amount:
                    return True
        return False

    def _finish(
        self,
        allow: bool,
        decision: str,
        reason: str,
        reasons: list[str],
        initiator: str,
        actor: str,
        action: str,
        resource: str,
        identity: dict,
        scope: dict,
        risk: str,
        obligations: list,
        path: list,
        enter_trace: list,
        pack: CapabilityPack,
        request: dict,
    ) -> EvaluateResult:
        rec = AuditRecord(
            id=f"aud-{uuid.uuid4().hex[:12]}",
            ts=_now().isoformat(),
            decision=decision,
            allow=allow,
            initiator=initiator,
            actor=actor,
            action=action,
            resource=resource,
            payload={
                "reason": reason,
                "reasons": reasons,
                "identity": identity,
                "scope": scope,
                "path": path,
                "enter_trace": enter_trace,
                "pack_id": pack.id,
                "pack_version": pack.version,
                "request": {
                    k: request[k]
                    for k in request
                    if k in {
                        "initiator_human_id",
                        "actor_agent_id",
                        "action",
                        "resource_id",
                        "data_owner_id",
                        "amount",
                        "delegation_chain",
                        "pack_id",
                        "document_id",
                    }
                },
            },
        )
        self.audit.append(rec)
        return EvaluateResult(
            allow=allow,
            decision=decision,
            reason=reason,
            reasons=reasons,
            effective_identity=identity,
            effective_scope=scope,
            risk_level=risk,
            obligations=obligations,
            path=path,
            enter_trace=enter_trace,
            pack_id=pack.id,
            pack_version=pack.version,
            audit_id=rec.id,
        )


def _deny_enter(code: str, reason: str, pack: CapabilityPack) -> dict:
    return {
        "allow": False,
        "enter_reason": "denied",
        "denied_reason": code,
        "reason": reason,
        "reasons": [reason],
        "pack_id": pack.id,
        "require_user_grant": None,
    }
