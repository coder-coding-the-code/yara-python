"""Minimal OpenFGA DSL parser covering the ECS Trust Graph model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass(frozen=True)
class DirectUserset:
    """`this` — tuples written directly to the relation."""

    allowed_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComputedUserset:
    relation: str


@dataclass(frozen=True)
class TupleToUserset:
    tupleset: str
    computed: str


@dataclass(frozen=True)
class UnionRewrite:
    children: tuple["Rewrite", ...]


Rewrite = Union[DirectUserset, ComputedUserset, TupleToUserset, UnionRewrite]


@dataclass
class TypeDef:
    name: str
    relations: dict[str, Rewrite] = field(default_factory=dict)


@dataclass
class AuthorizationModel:
    schema_version: str = "1.1"
    types: dict[str, TypeDef] = field(default_factory=dict)

    def rewrite(self, object_type: str, relation: str) -> Rewrite:
        try:
            return self.types[object_type].relations[relation]
        except KeyError as exc:
            raise KeyError(f"unknown relation {object_type}#{relation}") from exc


def _split_top(expr: str, keyword: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    tokens = expr.split()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        depth += tok.count("[") + tok.count("(")
        depth -= tok.count("]") + tok.count(")")
        if tok == keyword and depth == 0:
            parts.append(" ".join(buf).strip())
            buf = []
        else:
            buf.append(tok)
        i += 1
    if buf:
        parts.append(" ".join(buf).strip())
    return [p for p in parts if p]


def parse_rewrite(expr: str) -> Rewrite:
    expr = expr.strip()
    union_parts = _split_top(expr, "or")
    if len(union_parts) > 1:
        return UnionRewrite(tuple(parse_rewrite(p) for p in union_parts))
    atom = union_parts[0]
    if " from " in atom:
        computed, tupleset = atom.split(" from ", 1)
        return TupleToUserset(tupleset=tupleset.strip(), computed=computed.strip())
    if atom.startswith("[") and atom.endswith("]"):
        inner = atom[1:-1].strip()
        if not inner:
            return DirectUserset(())
        types = tuple(item.strip() for item in inner.split(",") if item.strip())
        return DirectUserset(types)
    return ComputedUserset(atom)


def _strip_comment(raw: str) -> str:
    """Strip OpenFGA comments. `type#relation` must not be treated as a comment."""
    for i, ch in enumerate(raw):
        if ch == "#" and (i == 0 or raw[i - 1].isspace()):
            return raw[:i]
    return raw


def parse_dsl(text: str) -> AuthorizationModel:
    model = AuthorizationModel()
    current: TypeDef | None = None
    in_relations = False

    for raw in text.splitlines():
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("model") or line.startswith("schema"):
            if line.startswith("schema"):
                model.schema_version = line.replace("schema", "").strip()
            continue
        if line.startswith("type "):
            name = line.split(None, 1)[1].strip()
            current = TypeDef(name=name)
            model.types[name] = current
            in_relations = False
            continue
        if line == "relations":
            in_relations = True
            continue
        if in_relations and line.startswith("define "):
            if current is None:
                raise ValueError(f"define outside type: {line}")
            body = line[len("define ") :]
            name, expr = body.split(":", 1)
            current.relations[name.strip()] = parse_rewrite(expr.strip())
    return model
