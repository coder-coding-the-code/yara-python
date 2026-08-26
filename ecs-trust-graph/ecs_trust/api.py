"""FastAPI control plane for ECS Guardian Trust."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .manager import EvaluateResult, TrustManager
from .seed import build_demo

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class EvaluateBody(BaseModel):
    actor_agent_id: str
    initiator_human_id: str
    action: str
    resource_id: str
    data_owner_id: str | None = None
    amount: float | None = None
    env: str = "prod"
    connector_id: str | None = None
    skill_id: str | None = None
    caller_agent_id: str | None = None
    delegation_chain: list[str] | None = None
    pack_id: str | None = "expense-orch"
    session_id: str | None = None
    obligation_tokens: list[str] | None = None
    document_id: str | None = None


class ApprovalBody(EvaluateBody):
    ttl_seconds: int = 3600
    kind: str = "human_approval"


class ShareBody(BaseModel):
    owner_id: str
    viewer_id: str


class CanEnterBody(BaseModel):
    initiator_human_id: str
    agent_id: str
    caller_agent_id: str | None = None
    pack_id: str | None = "expense-orch"
    chain: list[str] | None = None


def _to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    return obj


def _tm(request: Request) -> TrustManager:
    return request.app.state.tm


def create_app(manager: TrustManager | None = None) -> FastAPI:
    app = FastAPI(title="ECS Guardian Trust", version="0.1.0")
    app.state.tm = manager or build_demo()

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "product": "guardian-trust", "engine": "openfga-rebac"}

    @app.get("/api/registry")
    def registry(request: Request) -> dict:
        return _tm(request).registry.snapshot()

    @app.get("/api/packs")
    def packs(request: Request) -> dict:
        return {k: asdict(v) for k, v in _tm(request).packs.items()}

    @app.get("/api/tuples")
    def tuples(request: Request) -> dict:
        return {
            "tuples": [
                {"user": t.user, "relation": t.relation, "object": t.object}
                for t in _tm(request).rebac.tuples()
            ]
        }

    @app.get("/api/graph")
    def graph(request: Request) -> dict:
        return _tm(request).graph_payload()

    @app.post("/api/evaluate")
    def evaluate(body: EvaluateBody, request: Request) -> dict:
        result = _tm(request).evaluate(body.model_dump())
        return _result_dict(result)

    @app.post("/api/can-enter")
    def can_enter(body: CanEnterBody, request: Request) -> dict:
        return _tm(request).can_enter(
            body.initiator_human_id,
            body.agent_id,
            caller=body.caller_agent_id,
            pack_id=body.pack_id,
            chain=body.chain,
        )

    @app.post("/api/approvals")
    def approvals(body: ApprovalBody, request: Request) -> dict:
        token = _tm(request).issue_approval(body.model_dump(), ttl_seconds=body.ttl_seconds)
        return {
            "id": token.id,
            "expires_at": token.expires_at.isoformat(),
            "kind": token.kind,
        }

    @app.post("/api/share")
    def share(body: ShareBody, request: Request) -> dict:
        _tm(request).share_data(body.owner_id, body.viewer_id)
        return {"ok": True}

    @app.post("/api/offboard/{user_id}")
    def offboard(user_id: str, request: Request) -> dict:
        tm = _tm(request)
        if user_id not in tm.registry.humans:
            raise HTTPException(404, f"unknown user {user_id}")
        return tm.offboard_user(user_id)

    @app.post("/api/reset")
    def reset(request: Request) -> dict:
        request.app.state.tm = build_demo()
        return {"ok": True}

    @app.get("/api/blast-radius")
    def blast_radius(node: str, request: Request) -> dict:
        return _tm(request).blast_radius(node)

    @app.get("/api/audit")
    def audit(request: Request, limit: int = 50) -> dict:
        items = _tm(request).audit[-limit:][::-1]
        return {"events": [_to_dict(x) for x in items]}

    @app.get("/api/scenarios")
    def scenarios() -> dict:
        return {"scenarios": SCENARIOS}

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

    return app


def _result_dict(result: EvaluateResult) -> dict:
    return {
        "allow": result.allow,
        "decision": result.decision,
        "reason": result.reason,
        "reasons": result.reasons,
        "effective_identity": result.effective_identity,
        "effective_scope": result.effective_scope,
        "risk_level": result.risk_level,
        "obligations": result.obligations,
        "path": result.path,
        "enter_trace": result.enter_trace,
        "pack_id": result.pack_id,
        "pack_version": result.pack_version,
        "audit_id": result.audit_id,
    }


SCENARIOS = [
    {
        "id": "self-submit",
        "title": "张三提交本人 1200 元报销",
        "expect": "allow",
        "request": {
            "initiator_human_id": "zhangsan",
            "actor_agent_id": "erp-docs",
            "action": "submit",
            "resource_id": "expense-api",
            "amount": 1200,
            "delegation_chain": ["expense-orchestrator", "invoice-ocr", "erp-docs"],
            "pack_id": "expense-orch",
        },
    },
    {
        "id": "cross-person-deny",
        "title": "张三提交李四的报销单",
        "expect": "deny",
        "request": {
            "initiator_human_id": "zhangsan",
            "actor_agent_id": "erp-docs",
            "action": "submit",
            "resource_id": "expense-api",
            "data_owner_id": "lisi",
            "amount": 1200,
            "delegation_chain": ["expense-orchestrator", "invoice-ocr", "erp-docs"],
            "pack_id": "expense-orch",
        },
    },
    {
        "id": "bank-pay-deny",
        "title": "助手调用银行付款 API",
        "expect": "deny",
        "request": {
            "initiator_human_id": "zhangsan",
            "actor_agent_id": "erp-docs",
            "action": "submit",
            "resource_id": "bank-pay-api",
            "amount": 1200,
            "delegation_chain": ["expense-orchestrator", "invoice-ocr", "erp-docs"],
            "pack_id": "expense-orch",
        },
    },
    {
        "id": "over-limit",
        "title": "张三提交 8000 元（超额审批）",
        "expect": "require_approval",
        "request": {
            "initiator_human_id": "zhangsan",
            "actor_agent_id": "erp-docs",
            "action": "submit",
            "resource_id": "expense-api",
            "amount": 8000,
            "delegation_chain": ["expense-orchestrator", "invoice-ocr", "erp-docs"],
            "pack_id": "expense-orch",
        },
    },
    {
        "id": "chain-ok",
        "title": "方案一：A→B（免检）→C（强检）",
        "expect": "allow",
        "request": {
            "initiator_human_id": "zhangsan",
            "actor_agent_id": "erp-docs",
            "action": "query",
            "resource_id": "expense-api",
            "delegation_chain": ["expense-orchestrator", "invoice-ocr", "erp-docs"],
            "pack_id": "expense-orch",
        },
    },
    {
        "id": "scheme2-ocr-requires-grant",
        "title": "方案二：进入发票识别也要 User→B",
        "expect": "allow",
        "request": {
            "initiator_human_id": "zhangsan",
            "actor_agent_id": "erp-docs",
            "action": "query",
            "resource_id": "expense-api",
            "delegation_chain": ["expense-orchestrator", "invoice-ocr", "erp-docs"],
            "pack_id": "expense-strict",
        },
    },
]


app = create_app()
