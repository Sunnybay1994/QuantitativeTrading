"""Load the versioned factor library; definitions are data, never code."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from quant.factors.expressions import required_history


@dataclass(frozen=True)
class FactorDefinition:
    id: str
    expr: str
    family: str
    direction: int
    source_ref: str

    @property
    def lookback(self) -> int:
        return required_history(self.expr)


def load_library(root: Path, selected: str = "all") -> list[FactorDefinition]:
    definitions = []
    for path in sorted(root.glob("*.toml")):
        row = tomllib.loads(path.read_text(encoding="utf-8"))
        definition = FactorDefinition(**row)
        if (not re.fullmatch(r"[a-z][a-z0-9_]*", definition.id)
                or definition.direction not in {-1, 1}
                or not definition.family or not definition.source_ref):
            raise ValueError(f"Invalid factor definition: {path}")
        required_history(definition.expr)
        definitions.append(definition)
    ids = [row.id for row in definitions]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Factor library is empty or contains duplicate IDs")
    if selected != "all":
        requested = set(selected.split(","))
        if requested - set(ids):
            raise ValueError(f"Unknown factors: {sorted(requested - set(ids))}")
        definitions = [row for row in definitions if row.id in requested]
    return definitions
