"""Agent / SP / Connector / Resource registry (non-ReBAC attributes)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

RiskLevel = Literal["L0", "L1", "L2", "L3", "L4", "L5"]
AgentKind = Literal[
    "entry",
    "orchestrator",
    "tool",
    "resource_access",
    "funds",
    "industrial",
]


@dataclass
class HumanPrincipal:
    id: str
    display_name: str
    org: str
    person: str
    role: str
    status: str = "active"

    @property
    def object_id(self) -> str:
        return f"user:{self.id}"


@dataclass
class AgentRecord:
    id: str
    display_name: str
    kind: AgentKind
    require_user_grant: bool
    trust_level: str = "standard"
    status: str = "active"
    env: str = "prod"
    is_entry: bool = False
    risk_level: RiskLevel = "L1"

    @property
    def object_id(self) -> str:
        return f"agent:{self.id}"


@dataclass
class ServicePrincipalRecord:
    id: str
    agent_id: str
    env: str = "prod"
    status: str = "active"
    scopes: list[str] = field(default_factory=list)
    expires_at: str | None = None

    @property
    def object_id(self) -> str:
        return f"service_principal:{self.id}"


@dataclass
class ConnectorRecord:
    id: str
    display_name: str
    system: str
    auth_type: str = "oidc"
    status: str = "active"

    @property
    def object_id(self) -> str:
        return f"connector:{self.id}"


@dataclass
class ResourceRecord:
    id: str
    display_name: str
    classification: str
    risk_level: RiskLevel
    env: str = "prod"
    personal: bool = False

    @property
    def object_id(self) -> str:
        return f"resource:{self.id}"


class AgentRegistry:
    def __init__(self) -> None:
        self.humans: dict[str, HumanPrincipal] = {}
        self.agents: dict[str, AgentRecord] = {}
        self.sps: dict[str, ServicePrincipalRecord] = {}
        self.connectors: dict[str, ConnectorRecord] = {}
        self.resources: dict[str, ResourceRecord] = {}

    def put_human(self, rec: HumanPrincipal) -> HumanPrincipal:
        self.humans[rec.id] = rec
        return rec

    def put_agent(self, rec: AgentRecord) -> AgentRecord:
        self.agents[rec.id] = rec
        return rec

    def put_sp(self, rec: ServicePrincipalRecord) -> ServicePrincipalRecord:
        self.sps[rec.id] = rec
        return rec

    def put_connector(self, rec: ConnectorRecord) -> ConnectorRecord:
        self.connectors[rec.id] = rec
        return rec

    def put_resource(self, rec: ResourceRecord) -> ResourceRecord:
        self.resources[rec.id] = rec
        return rec

    def human(self, hid: str) -> HumanPrincipal:
        return self.humans[_bare(hid, "user")]

    def agent(self, aid: str) -> AgentRecord:
        return self.agents[_bare(aid, "agent")]

    def resource(self, rid: str) -> ResourceRecord:
        return self.resources[_bare(rid, "resource")]

    def sp_for_agent(self, agent_id: str, env: str) -> ServicePrincipalRecord | None:
        aid = _bare(agent_id, "agent")
        for sp in self.sps.values():
            if sp.agent_id == aid and sp.env == env and sp.status == "active":
                return sp
        return None

    def snapshot(self) -> dict:
        return {
            "humans": [r.__dict__ for r in self.humans.values()],
            "agents": [r.__dict__ for r in self.agents.values()],
            "service_principals": [r.__dict__ for r in self.sps.values()],
            "connectors": [r.__dict__ for r in self.connectors.values()],
            "resources": [r.__dict__ for r in self.resources.values()],
        }


def _bare(value: str, prefix: str) -> str:
    p = prefix + ":"
    return value[len(p) :] if value.startswith(p) else value
