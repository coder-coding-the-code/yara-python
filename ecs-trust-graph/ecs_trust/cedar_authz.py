"""Cedar decision adapter."""

from __future__ import annotations

from pathlib import Path

from cedarpy import Decision, is_authorized

POLICY_PATH = Path(__file__).resolve().parent.parent / "cedar" / "trust.cedar"


class CedarEngine:
    def __init__(self, policy_text: str | None = None) -> None:
        self.policies = policy_text or POLICY_PATH.read_text(encoding="utf-8")

    def decide(self, principal: str, action: str, resource: str, context: dict, entities: list[dict]) -> dict:
        import json

        result = is_authorized(
            {
                "principal": principal,
                "action": f'Action::"{action}"',
                "resource": resource,
                "context": context,
            },
            self.policies,
            json.dumps(entities),
        )
        allow = result.decision == Decision.Allow
        reasons = list(result.diagnostics.reasons)
        errors = list(result.diagnostics.errors)
        return {
            "allow": allow,
            "decision": "allow" if allow else "deny",
            "reasons": reasons,
            "errors": errors,
        }


def entity(type_: str, id_: str, attrs: dict | None = None, parents: list | None = None) -> dict:
    return {
        "uid": {"type": type_, "id": id_},
        "attrs": attrs or {},
        "parents": parents or [],
    }
