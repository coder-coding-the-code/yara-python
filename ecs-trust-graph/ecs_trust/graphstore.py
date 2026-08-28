"""Attributed trust graph: identity, topology, access edges, data rights."""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from .packs import CapabilityPack, RISK_RANK, _oid


@dataclass
class Node:
    id: str
    kind: str
    label: str
    attrs: dict = field(default_factory=dict)


class TrustGraph:
    def __init__(self) -> None:
        self.g = nx.MultiDiGraph()
        self.packs: dict[str, CapabilityPack] = {}
        self.grants: dict[tuple[str, str], dict] = {}

    def add(self, node_id: str, kind: str, label: str, **attrs) -> None:
        self.g.add_node(node_id, kind=kind, label=label, **attrs)

    def edge(self, src: str, rel: str, dst: str, **attrs) -> None:
        self.g.add_edge(src, dst, key=rel, relation=rel, **attrs)

    def has_edge(self, src: str, rel: str, dst: str) -> bool:
        return self.g.has_edge(src, dst, key=rel)

    def node(self, node_id: str) -> dict:
        return self.g.nodes[node_id]

    def put_pack(self, pack: CapabilityPack) -> None:
        self.packs[pack.id] = pack
        if pack.object_id not in self.g:
            self.add(pack.object_id, "pack", pack.display_name, version=pack.version)
        else:
            self.g.nodes[pack.object_id]["version"] = pack.version
        for a, b in pack.workflow:
            if not self.has_edge(a, "INVOKE", b):
                self.edge(a, "INVOKE", b, pack=pack.id)

    def grant(self, user: str, pack_id: str) -> dict:
        user = _oid("user", user)
        pack = self.packs[pack_id]
        snap = pack.capability_snapshot()
        rec = {
            "user": user,
            "pack_id": pack_id,
            "fingerprint": pack.capability_fingerprint(),
            "snapshot": snap,
            "status": "active",
        }
        self.grants[(user, pack_id)] = rec
        self.edge(user, "GRANTED", pack.object_id, fingerprint=rec["fingerprint"])
        return rec

    def revoke_user(self, user: str) -> int:
        user = _oid("user", user)
        n = 0
        for key in list(self.grants):
            if key[0] == user:
                del self.grants[key]
                n += 1
        if user in self.g:
            self.g.nodes[user]["status"] = "offboarded"
        drop = [
            (u, v, k)
            for u, v, k, d in self.g.edges(keys=True, data=True)
            if u == user and d.get("relation") == "GRANTED"
        ]
        for u, v, k in drop:
            self.g.remove_edge(u, v, k)
        return n

    def effective_snapshot(self, user: str, pack_id: str) -> dict | None:
        user = _oid("user", user)
        rec = self.grants.get((user, pack_id))
        if rec is None or rec["status"] != "active":
            return None
        pack = self.packs[pack_id]
        from .packs import intersect_snapshot

        return intersect_snapshot(rec["snapshot"], pack.capability_snapshot())

    def sp_for(self, agent: str, env: str) -> str | None:
        agent = _oid("agent", agent)
        for _u, v, d in self.g.out_edges(agent, data=True):
            if d.get("relation") == "RUNS_AS" and self.g.nodes[v].get("env") == env:
                if self.g.nodes[v].get("status", "active") == "active":
                    return v
        return None

    def sp_can(self, sp: str, action: str, resource: str) -> bool:
        return self.has_edge(sp, f"CAN_{action.upper()}", resource)

    def data_right(self, viewer: str, owner: str, document: str | None) -> str:
        viewer = _oid("user", viewer)
        owner = _oid("user", owner)
        if viewer == owner:
            return "self"
        if document and self.has_edge(owner, "OWNS", _oid("resource", document)):
            if self.has_edge(viewer, "VIEWER", _oid("resource", document)):
                return "share"
        if self.has_edge(viewer, "DATA_VIEWER", owner):
            return "share"
        if self.has_edge(viewer, "MANAGER", owner):
            return "manager"
        return "none"

    def invoke_allowed(self, src: str, dst: str, pack: CapabilityPack) -> bool:
        src, dst = _oid("agent", src), _oid("agent", dst)
        return (src, dst) in pack.workflow and src in pack.members() and dst in pack.members()

    def chain_in_workflow(self, chain: list[str], pack: CapabilityPack) -> bool:
        nodes = [_oid("agent", a) for a in chain]
        if not nodes or nodes[0] != pack.entry:
            return False
        for a, b in zip(nodes, nodes[1:]):
            if (a, b) not in pack.workflow:
                return False
        return set(nodes) <= pack.members()

    def validate(self) -> list[str]:
        errors: list[str] = []
        for pack in self.packs.values():
            if pack.entry in pack.egress_agents() and pack.entry in pack.workers:
                errors.append(f"{pack.id}: entry cannot be both worker and egress")
            overlap = set(pack.workers) & pack.egress_agents()
            if overlap:
                errors.append(f"{pack.id}: worker/egress overlap {sorted(overlap)}")
            for worker in pack.workers:
                sp = self.sp_for(worker, pack.env)
                if sp:
                    for resource in pack.resources:
                        for action in pack.actions:
                            if self.sp_can(sp, action, resource):
                                errors.append(
                                    f"{pack.id}: worker {worker} SP {sp} can {action} {resource}"
                                )
            for agent in pack.egress_agents():
                if agent not in pack.members():
                    errors.append(f"{pack.id}: egress agent {agent} not a member")
                in_flow = agent == pack.entry or any(agent in e for e in pack.workflow)
                if not in_flow:
                    errors.append(f"{pack.id}: egress {agent} not in workflow")
            for a, b in pack.workflow:
                if a not in pack.members() or b not in pack.members():
                    errors.append(f"{pack.id}: workflow edge {a}->{b} outside members")
        return errors

    def blast_radius(self, node: str) -> dict:
        if node not in self.g:
            return {"node": node, "reachable": [], "edge_count": 0}
        reachable = nx.descendants(self.g, node)
        sub = self.g.subgraph({node, *reachable})
        return {
            "node": node,
            "reachable": sorted(reachable),
            "node_count": sub.number_of_nodes(),
            "edge_count": sub.number_of_edges(),
            "agents": sorted(n for n in reachable if n.startswith("agent:")),
            "packs": sorted(n for n in reachable if n.startswith("pack:")),
            "resources": sorted(n for n in reachable if n.startswith("resource:")),
        }

    def layout_payload(self) -> dict:
        kind_order = ["user", "pack", "agent", "service_principal", "connector", "resource"]
        buckets: dict[str, list[str]] = {k: [] for k in kind_order}
        for nid, data in self.g.nodes(data=True):
            buckets.setdefault(data.get("kind") or nid.split(":")[0], []).append(nid)
        positions = {}
        for row, kind in enumerate([k for k in kind_order if buckets.get(k)]):
            for col, nid in enumerate(sorted(buckets[kind])):
                positions[nid] = (70.0 + col * 88.0, 48.0 + row * 150.0)
        nodes = []
        for nid, data in self.g.nodes(data=True):
            x, y = positions.get(nid, (40.0, 40.0))
            nodes.append(
                {
                    "id": nid,
                    "kind": data.get("kind") or nid.split(":")[0],
                    "label": data.get("label") or nid,
                    "status": data.get("status"),
                    "x": x,
                    "y": y,
                    "risk": data.get("risk_level"),
                }
            )
        edges = [
            {"from": u, "to": v, "relation": d.get("relation")}
            for u, v, d in self.g.edges(data=True)
        ]
        return {"nodes": nodes, "edges": edges}

    def registry_snapshot(self) -> dict:
        grouped: dict[str, list] = {
            "humans": [],
            "agents": [],
            "service_principals": [],
            "connectors": [],
            "resources": [],
        }
        mapping = {
            "user": "humans",
            "agent": "agents",
            "service_principal": "service_principals",
            "connector": "connectors",
            "resource": "resources",
        }
        for nid, data in self.g.nodes(data=True):
            bucket = mapping.get(data.get("kind"))
            if not bucket:
                continue
            item = {"id": nid.split(":", 1)[-1], "display_name": data.get("label"), **data}
            grouped[bucket].append(item)
        return grouped
