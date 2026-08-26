"""OpenFGA-compatible ReBAC store: Check / Write / Expand / ListUsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .dsl import (
    AuthorizationModel,
    ComputedUserset,
    DirectUserset,
    TupleToUserset,
    UnionRewrite,
    parse_dsl,
)


@dataclass(frozen=True)
class RelationshipTuple:
    user: str
    relation: str
    object: str

    def key(self) -> tuple[str, str, str]:
        return (self.user, self.relation, self.object)


def parse_userset(ref: str) -> tuple[str, str] | None:
    """Return (object, relation) if `type:id#relation`, else None."""
    if "#" not in ref:
        return None
    obj, rel = ref.split("#", 1)
    if ":" not in obj or not rel:
        raise ValueError(f"invalid userset reference: {ref}")
    return obj, rel


class ReBAC:
    """In-memory Zanzibar/OpenFGA subset used when a live OpenFGA server is absent."""

    def __init__(self, model: AuthorizationModel):
        self.model = model
        self._tuples: dict[tuple[str, str, str], RelationshipTuple] = {}

    @classmethod
    def from_dsl(cls, text: str) -> "ReBAC":
        return cls(parse_dsl(text))

    @classmethod
    def from_model_file(cls, path: str | Path) -> "ReBAC":
        return cls.from_dsl(Path(path).read_text(encoding="utf-8"))

    def write(self, user: str, relation: str, object_: str) -> RelationshipTuple:
        tup = RelationshipTuple(user=user, relation=relation, object=object_)
        self._tuples[tup.key()] = tup
        return tup

    def delete(self, user: str, relation: str, object_: str) -> bool:
        return self._tuples.pop((user, relation, object_), None) is not None

    def delete_matching(self, user: str | None = None, relation: str | None = None, object_: str | None = None) -> int:
        keys = [
            k
            for k, t in self._tuples.items()
            if (user is None or t.user == user)
            and (relation is None or t.relation == relation)
            and (object_ is None or t.object == object_)
        ]
        for k in keys:
            del self._tuples[k]
        return len(keys)

    def tuples(self) -> list[RelationshipTuple]:
        return list(self._tuples.values())

    def tuples_for(self, object_: str, relation: str) -> list[RelationshipTuple]:
        return [t for t in self._tuples.values() if t.object == object_ and t.relation == relation]

    def check(self, user: str, relation: str, object_: str) -> bool:
        return self._check(user, relation, object_, set())

    def _check(self, user: str, relation: str, object_: str, visited: set[tuple[str, str, str]]) -> bool:
        key = (user, relation, object_)
        if key in visited:
            return False
        visited.add(key)
        if ":" not in object_:
            raise ValueError(f"object must be type:id, got {object_!r}")
        object_type = object_.split(":", 1)[0]
        rewrite = self.model.rewrite(object_type, relation)
        return self._eval(user, relation, object_, rewrite, visited)

    def _eval(
        self,
        user: str,
        relation: str,
        object_: str,
        rewrite,
        visited: set[tuple[str, str, str]],
    ) -> bool:
        if isinstance(rewrite, UnionRewrite):
            return any(self._eval(user, relation, object_, child, visited) for child in rewrite.children)
        if isinstance(rewrite, DirectUserset):
            return self._eval_this(user, relation, object_, visited)
        if isinstance(rewrite, ComputedUserset):
            return self._check(user, rewrite.relation, object_, visited)
        if isinstance(rewrite, TupleToUserset):
            for tup in self.tuples_for(object_, rewrite.tupleset):
                if self._userset_contains(user, tup.user, rewrite.computed, visited):
                    return True
            return False
        raise TypeError(f"unknown rewrite {rewrite!r}")

    def _eval_this(
        self,
        user: str,
        relation: str,
        object_: str,
        visited: set[tuple[str, str, str]],
    ) -> bool:
        for tup in self.tuples_for(object_, relation):
            if tup.user == user:
                return True
            parsed = parse_userset(tup.user)
            if parsed is not None:
                us_object, us_rel = parsed
                if self._check(user, us_rel, us_object, visited):
                    return True
        return False

    def _userset_contains(
        self,
        user: str,
        subject: str,
        computed_relation: str,
        visited: set[tuple[str, str, str]],
    ) -> bool:
        if subject == user:
            # Direct subject match is not enough for TTU; still need computed relation.
            # Example: viewer = manager from owner. owner user:lisi does not make lisi
            # a viewer via this branch unless we also treat owner separately.
            pass
        parsed = parse_userset(subject)
        if parsed is not None:
            us_object, us_rel = parsed
            if self._check(user, us_rel, us_object, visited) and self._check(
                user, computed_relation, us_object, visited
            ):
                return True
            # If subject is a userset, members of that userset are checked below
            # by resolving who is in us_rel... For ECS model, TTU subjects are
            # concrete objects (user:lisi), not usersets.
        return self._check(user, computed_relation, subject, visited)

    def list_objects(self, user: str, relation: str, object_type: str) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for tup in self._tuples.values():
            if not tup.object.startswith(object_type + ":"):
                continue
            if tup.object in seen:
                continue
            if self.check(user, relation, tup.object):
                seen.add(tup.object)
                found.append(tup.object)
        return sorted(found)

    def expand_users(self, relation: str, object_: str, limit: int = 200) -> list[str]:
        """Best-effort listing of concrete subjects that check() as related."""
        candidates: set[str] = set()
        for tup in self._tuples.values():
            if "#" not in tup.user:
                candidates.add(tup.user)
        related = [c for c in sorted(candidates) if self.check(c, relation, object_)]
        return related[:limit]
