"""Trust Manager v2: start_task / hop / authorize_egress + evaluate facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import uuid

from .cedar_authz import CedarEngine, entity
from .graphstore import TrustGraph
from .packs import RISK_RANK, CapabilityPack, _oid


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _bare(oid: str) -> str:
    return oid.split(":", 1)[-1] if ":" in oid else oid


@dataclass
class Task:
    id: str
    initiator: str
    pack_id: str
    entry: str
    snapshot: dict
    env: str
    chain: list[str]
    active: bool = True
    created_at: str = field(default_factory=lambda: _now().isoformat())


@dataclass
class Decision:
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
    task_id: str | None = None


class TrustManager:
    def __init__(self, graph: TrustGraph, cedar: CedarEngine | None = None):
        self.graph = graph
        self.cedar = cedar or CedarEngine()
        self.tasks: dict[str, Task] = {}
        self.tokens: dict[str, dict] = {}
        self.audit: list[dict] = []

    @property
    def packs(self) -> dict[str, CapabilityPack]:
        return self.graph.packs

    @property
    def registry(self):
        class _R:
            def __init__(self, g: TrustGraph):
                self._g = g
                self.humans = {
                    _bare(n): type("H", (), {**d, "id": _bare(n), "status": d.get("status", "active")})()
                    for n, d in g.g.nodes(data=True)
                    if d.get("kind") == "user"
                }

            def snapshot(self):
                return self._g.registry_snapshot()

            def agent(self, aid: str):
                nid = _oid("agent", aid)
                return self._g.node(nid)

            def resource(self, rid: str):
                nid = _oid("resource", rid)
                data = self._g.node(nid)
                return type("R", (), {**data, "object_id": nid, "risk_level": data.get("risk_level", "L0")})()

        return _R(self.graph)

    def start_task(self, user: str, pack_id: str, entry: str | None = None, env: str = "prod") -> Decision:
        user = _oid("user", user)
        pack = self.graph.packs[pack_id]
        entry = _oid("agent", entry or pack.entry)
        status = self.graph.node(user).get("status", "active")
        snap = self.graph.effective_snapshot(user, pack_id)
        ctx = {
            "has_grant": snap is not None,
            "user_active": status == "active",
            "entry": _bare(entry),
            "pack_entry": _bare(pack.entry),
            "env": env,
            "pack_env": pack.env,
        }
        entities = [
            entity("User", _bare(user)),
            entity("Pack", pack.id, {"entry": _bare(pack.entry)}),
        ]
        verdict = self.cedar.decide(f'User::"{_bare(user)}"', "StartTask", f'Pack::"{pack.id}"', ctx, entities)
        if not verdict["allow"]:
            reason = "无权启动任务" if not ctx["has_grant"] or not ctx["user_active"] else "入口不匹配"
            return self._finish(False, "deny", reason, verdict["reasons"], user, entry, "StartTask", pack.object_id, {}, {}, "L0", [], [], [], pack, {})
        task = Task(
            id=f"task-{uuid.uuid4().hex[:12]}",
            initiator=user,
            pack_id=pack_id,
            entry=entry,
            snapshot=snap or {},
            env=env,
            chain=[entry],
        )
        self.tasks[task.id] = task
        return self._finish(
            True,
            "allow",
            "任务已启动",
            verdict["reasons"] + [f"snapshot={list((snap or {}).get('resources', []))}"],
            user,
            entry,
            "StartTask",
            pack.object_id,
            {"initiator": user, "entry_agent": entry},
            snap or {},
            pack.risk_cap,
            [],
            [{"kind": "start", "task": task.id, "entry": entry}],
            [{"agent": entry, "enter_reason": "start_task", "allow": True}],
            pack,
            {},
            task_id=task.id,
        )

    def can_enter(
        self,
        user: str,
        agent: str,
        *,
        caller: str | None = None,
        pack_id: str | None = None,
        chain: list[str] | None = None,
    ) -> dict:
        pack = self.graph.packs[pack_id or "expense-orch"]
        agent = _oid("agent", agent)
        user = _oid("user", user)
        if caller is None:
            started = self.start_task(user, pack.id, agent)
            return {
                "allow": started.allow,
                "enter_reason": "start_task" if started.allow else "denied",
                "reason": started.reason,
                "reasons": started.reasons,
                "pack_id": pack.id,
            }
        caller = _oid("agent", caller)
        ok = self.graph.invoke_allowed(caller, agent, pack)
        return {
            "allow": ok,
            "enter_reason": "topology_hop" if ok else "denied",
            "reason": "拓扑允许" if ok else f"缺少 INVOKE {caller} → {agent}",
            "reasons": [],
            "pack_id": pack.id,
        }

    def hop(self, task_id: str, dst: str) -> Decision:
        task = self.tasks[task_id]
        pack = self.graph.packs[task.pack_id]
        src = task.chain[-1]
        dst = _oid("agent", dst)
        ctx = {
            "invoke_edge": self.graph.invoke_allowed(src, dst, pack),
            "both_in_pack": src in pack.members() and dst in pack.members(),
            "task_active": task.active,
        }
        entities = [entity("Agent", _bare(src)), entity("Agent", _bare(dst))]
        verdict = self.cedar.decide(f'Agent::"{_bare(src)}"', "Hop", f'Agent::"{_bare(dst)}"', ctx, entities)
        if not verdict["allow"]:
            return self._finish(
                False,
                "deny",
                f"拓扑不允许 {src} → {dst}",
                verdict["reasons"],
                task.initiator,
                dst,
                "Hop",
                dst,
                {},
                task.snapshot,
                "L0",
                [],
                [],
                [{"agent": dst, "caller": src, "enter_reason": "denied", "allow": False}],
                pack,
                {},
                task_id=task.id,
            )
        task.chain.append(dst)
        return self._finish(
            True,
            "allow",
            "拓扑跳转允许",
            verdict["reasons"],
            task.initiator,
            dst,
            "Hop",
            dst,
            {"initiator": task.initiator, "calling_agent": src, "executing_agent": dst},
            task.snapshot,
            pack.risk_cap,
            [],
            [{"kind": "hop", "from": src, "to": dst}],
            [{"agent": dst, "caller": src, "enter_reason": "topology_hop", "allow": True}],
            pack,
            {},
            task_id=task.id,
        )

    def authorize_egress(self, task_id: str, request: dict) -> Decision:
        task = self.tasks[task_id]
        pack = self.graph.packs[task.pack_id]
        actor = _oid("agent", request.get("actor_agent_id") or task.chain[-1])
        action = request["action"]
        resource = _oid("resource", request["resource_id"])
        initiator = task.initiator
        data_owner = _oid("user", request["data_owner_id"]) if request.get("data_owner_id") else initiator
        amount = request.get("amount")
        env = request.get("env") or task.env
        sp = self.graph.sp_for(actor, env)
        snap = task.snapshot
        res_attrs = self.graph.node(resource) if resource in self.graph.g else {}
        risk = res_attrs.get("risk_level", "L0")
        risk_rank = RISK_RANK.get(risk, 0)
        approval = self._approval_ok(request, initiator, actor, action, resource, amount)
        dual = approval and (self.tokens.get((request.get("obligation_tokens") or [None])[0], {}).get("kind") == "dual_control" if request.get("obligation_tokens") else False)
        if request.get("obligation_tokens"):
            for tid in request["obligation_tokens"]:
                tok = self.tokens.get(tid)
                if tok and tok.get("kind") == "dual_control":
                    dual = True
        right = self.graph.data_right(initiator, data_owner, request.get("document_id"))
        data_ok = data_owner == initiator or right in {"share", "manager"}
        actor_egress = actor in (snap.get("egress") or {})
        entitled_resources = set(snap.get("resources") or [])
        if actor_egress:
            entitled_resources &= set((snap.get("egress") or {}).get(actor) or [])
        amount_limit = snap.get("amount_limit")
        amount_over = amount is not None and amount_limit is not None and amount > amount_limit
        amount_ok = (not amount_over) or approval
        cap_rank = RISK_RANK.get(snap.get("risk_cap") or "L0", 0)
        if risk_rank >= 5 or risk_rank > cap_rank:
            risk_ok = False
            risk_need = "deny"
        elif risk_rank >= 4:
            risk_ok = dual
            risk_need = "dual"
        elif risk_rank >= 3:
            risk_ok = approval
            risk_need = "approval"
        else:
            risk_ok = True
            risk_need = None
        facts = {
            "task_active": task.active,
            "actor_in_snapshot_egress": actor_egress,
            "sp_binds_actor": sp is not None,
            "sp_access_edge": bool(sp) and self.graph.sp_can(sp, action, resource),
            "resource_in_snapshot": resource in entitled_resources,
            "action_in_snapshot": action in set(snap.get("actions") or []),
            "data_ok": data_ok,
            "risk_ok": risk_ok,
            "amount_ok": amount_ok,
            "risk_rank": risk_rank,
        }
        entities = [
            entity("ServicePrincipal", _bare(sp or "missing")),
            entity("Resource", _bare(resource), {"risk": risk}),
            entity("User", _bare(initiator)),
        ]
        verdict = self.cedar.decide(
            f'ServicePrincipal::"{_bare(sp or "missing")}"',
            action,
            f'Resource::"{_bare(resource)}"',
            facts,
            entities,
        )
        identity = {
            "initiator": initiator,
            "entry_agent": task.entry,
            "calling_agent": task.chain[-2] if len(task.chain) > 1 else None,
            "executing_agent": actor,
            "executing_sp": sp,
            "data_owner": data_owner,
            "env": env,
        }
        path = [{"kind": "hop", "agent": a} for a in task.chain] + [
            {"kind": "egress", "sp": sp, "action": action, "resource": resource}
        ]
        trace = [{"agent": a, "enter_reason": "start_task" if i == 0 else "topology_hop", "allow": True} for i, a in enumerate(task.chain)]
        if not verdict["allow"]:
            obligations = []
            decision = "deny"
            reason = "出站拒绝"
            if task.active and actor_egress and facts["sp_access_edge"] and facts["resource_in_snapshot"]:
                if not data_ok:
                    reason = "跨人数据访问缺少独立依据（组织权 / 分享 / 审批）"
                elif amount_over and not approval:
                    decision = "require_approval"
                    reason = f"金额 {amount} 超过能力包档位上限 {amount_limit}，需要人工审批"
                    obligations = [{"type": "human_approval", "reason": "amount_limit", "amount": amount, "limit": amount_limit}]
                elif risk_need == "dual" and not dual:
                    decision = "require_approval"
                    reason = "L4 高价值/不可逆动作需要双人审批"
                    obligations = [{"type": "dual_control", "resource": resource, "risk_level": risk}]
                elif risk_need == "approval" and not approval:
                    decision = "require_approval"
                    reason = "L3 财务/客户/生产动作需要人工审批"
                    obligations = [{"type": "human_approval", "resource": resource, "risk_level": risk}]
                elif not actor_egress:
                    reason = f"{actor} 不是该能力快照中的出站 Agent（内部 worker 禁止出站）"
                elif not facts["sp_access_edge"]:
                    reason = f"无边：{sp} can_{action} {resource}（零信任默认拒绝）"
                elif not facts["resource_in_snapshot"]:
                    reason = f"能力快照不包含 {resource}"
            elif not actor_egress:
                reason = f"{actor} 不是该能力快照中的出站 Agent（内部 worker 禁止出站）"
            elif not facts["sp_access_edge"]:
                reason = f"无边：{sp} can_{action} {resource}（零信任默认拒绝）"
            elif not facts["resource_in_snapshot"]:
                reason = f"能力快照不包含 {resource}"
            return self._finish(
                False,
                decision,
                reason,
                verdict["reasons"] + [k for k, v in facts.items() if v is False],
                initiator,
                actor,
                action,
                resource,
                identity,
                snap,
                risk,
                obligations,
                path,
                trace,
                pack,
                request,
                task_id=task.id,
            )
        return self._finish(
            True,
            "allow",
            "允许",
            verdict["reasons"],
            initiator,
            actor,
            action,
            resource,
            identity,
            snap,
            risk,
            [],
            path,
            trace,
            pack,
            request,
            task_id=task.id,
        )

    def evaluate(self, request: dict) -> Decision:
        user = request["initiator_human_id"]
        pack_id = request.get("pack_id") or "expense-orch"
        env = request.get("env") or "prod"
        chain = [_oid("agent", a) for a in (request.get("delegation_chain") or [request["actor_agent_id"]])]
        started = self.start_task(user, pack_id, chain[0], env)
        if not started.allow:
            return started
        task_id = started.task_id
        for dst in chain[1:]:
            hopped = self.hop(task_id, dst)
            if not hopped.allow:
                return hopped
        actor = _oid("agent", request["actor_agent_id"])
        if chain[-1] != actor:
            hopped = self.hop(task_id, actor)
            if not hopped.allow:
                return hopped
        return self.authorize_egress(task_id, request)

    def issue_approval(self, request: dict, ttl_seconds: int = 3600) -> type("T", (), {}):
        token_id = f"ob-{uuid.uuid4().hex[:12]}"
        rec = {
            "id": token_id,
            "initiator": _oid("user", request["initiator_human_id"]),
            "actor_agent": _oid("agent", request["actor_agent_id"]),
            "action": request["action"],
            "resource": _oid("resource", request["resource_id"]),
            "amount": request.get("amount"),
            "kind": request.get("kind") or "human_approval",
            "expires_at": _now() + timedelta(seconds=ttl_seconds),
        }
        self.tokens[token_id] = rec

        class Token:
            pass

        t = Token()
        t.id = token_id
        t.expires_at = rec["expires_at"]
        t.kind = rec["kind"]
        return t

    def share_data(self, owner: str, viewer: str) -> None:
        self.graph.edge(_oid("user", viewer), "DATA_VIEWER", _oid("user", owner))

    def offboard_user(self, user_id: str) -> dict:
        user = _oid("user", user_id)
        removed = self.graph.revoke_user(user)
        for task in self.tasks.values():
            if task.initiator == user:
                task.active = False
        return {"user": user, "tuples_removed": removed, "blast_radius": self.graph.blast_radius(user)}

    def blast_radius(self, node: str) -> dict:
        return self.graph.blast_radius(node)

    def graph_payload(self) -> dict:
        return self.graph.layout_payload()

    def add_worker(self, pack_id: str, worker: str, after: str) -> None:
        pack = self.graph.packs[pack_id]
        worker = _oid("agent", worker)
        after = _oid("agent", after)
        if worker not in pack.workers:
            pack.workers.append(worker)
        # splice: after → worker → old successors of after
        old = [e for e in pack.workflow if e[0] == after]
        pack.workflow = [e for e in pack.workflow if e[0] != after]
        pack.workflow.append((after, worker))
        for _a, b in old:
            pack.workflow.append((worker, b))
        self.graph.edge(after, "INVOKE", worker, pack=pack_id)
        for _a, b in old:
            self.graph.edge(worker, "INVOKE", b, pack=pack_id)
        pack.version = _bump(pack.version, topology=True)

    def expand_capability(self, pack_id: str, agent: str, resource: str) -> None:
        pack = self.graph.packs[pack_id]
        agent = _oid("agent", agent)
        resource = _oid("resource", resource)
        pack.egress.setdefault(agent, [])
        if resource not in pack.egress[agent]:
            pack.egress[agent].append(resource)
        if resource not in pack.resources:
            pack.resources.append(resource)
        pack.version = _bump(pack.version, capability=True)

    def _approval_ok(self, request, initiator, actor, action, resource, amount) -> bool:
        now = _now()
        for tid in request.get("obligation_tokens") or []:
            tok = self.tokens.get(tid)
            if not tok or now > tok["expires_at"]:
                continue
            if tok["initiator"] == initiator and tok["actor_agent"] == actor and tok["action"] == action and tok["resource"] == resource:
                if tok["amount"] is None or amount is None or tok["amount"] >= amount:
                    return True
        return False

    def _finish(
        self,
        allow,
        decision,
        reason,
        reasons,
        initiator,
        actor,
        action,
        resource,
        identity,
        scope,
        risk,
        obligations,
        path,
        enter_trace,
        pack,
        request,
        task_id=None,
    ) -> Decision:
        rec = {
            "id": f"aud-{uuid.uuid4().hex[:12]}",
            "ts": _now().isoformat(),
            "decision": decision,
            "allow": allow,
            "initiator": initiator,
            "actor": actor,
            "action": action,
            "resource": resource,
            "payload": {
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
        }
        self.audit.append(rec)
        return Decision(
            allow=allow,
            decision=decision,
            reason=reason,
            reasons=list(reasons),
            effective_identity=identity,
            effective_scope=scope,
            risk_level=risk,
            obligations=obligations,
            path=path,
            enter_trace=enter_trace,
            pack_id=pack.id,
            pack_version=pack.version,
            audit_id=rec["id"],
            task_id=task_id,
        )


def _bump(version: str, topology: bool = False, capability: bool = False) -> str:
    parts = [int(x) for x in version.split(".")]
    while len(parts) < 3:
        parts.append(0)
    if capability:
        parts[1] += 1
        parts[2] = 0
    elif topology:
        parts[2] += 1
    return ".".join(str(x) for x in parts)
