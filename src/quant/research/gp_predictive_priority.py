"""Pure candidate selection for the preregistered predictive_priority_v2 design.

This module neither generates candidates nor activates a search. Input versions,
point-in-time availability, monthly IC calculation and control freezing are the
caller's responsibility; selection refuses absent manifest or measurement data.
"""
from __future__ import annotations

import ast
import hashlib
import json
import keyword
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

_IC_BAND = Decimal("0.001")


@dataclass(frozen=True)
class MechanismTerminal:
    terminal_id: str
    mechanism: str
    input_version: str
    availability: str


@dataclass(frozen=True)
class MechanismManifest:
    terminals: tuple[MechanismTerminal, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.terminals, tuple) or not self.terminals:
            raise ValueError("A nonempty immutable mechanism manifest is required")
        ids = [terminal.terminal_id for terminal in self.terminals]
        if len(set(ids)) != len(ids):
            raise ValueError("Mechanism terminal IDs must be unique")
        for terminal in self.terminals:
            if (not terminal.terminal_id.isidentifier()
                    or keyword.iskeyword(terminal.terminal_id)
                    or terminal.mechanism not in {"financial", "industry_relative_reversal"}
                    or not terminal.input_version.strip() or not terminal.availability.strip()):
                raise ValueError("Manifest requires exact IDs, mechanism, version and availability")

    @property
    def sha256(self) -> str:
        """Canonical hash is order-independent and includes every input declaration."""
        payload = [asdict(row) for row in sorted(self.terminals, key=lambda row: row.terminal_id)]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SelectionRules:
    sample_groups: int
    minimum_valid_months_per_group: int
    minimum_symbols_per_month: int
    minimum_paired_coverage: float
    max_depth: int
    maximum_candidates: int

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> SelectionRules:
        if config.get("version") != "predictive_priority_v2":
            raise ValueError("Require the predictive_priority_v2 registration")
        try:
            result = cls(**{name: config[name] for name in cls.__dataclass_fields__})
        except KeyError as exc:
            raise ValueError(f"Missing registered selection setting: {exc.args[0]}") from exc
        return result

    def __post_init__(self) -> None:
        counts = (self.sample_groups, self.minimum_valid_months_per_group,
                  self.minimum_symbols_per_month, self.max_depth, self.maximum_candidates)
        if (any(type(value) is not int or value < 1 for value in counts)
                or self.sample_groups != 3
                or not _finite(self.minimum_paired_coverage)
                or not 0 < self.minimum_paired_coverage <= 1):
            raise ValueError("Invalid registered selection settings")


@dataclass(frozen=True)
class GroupIC:
    """IC mean over valid months, plus minima over those same valid months.

The caller must first exclude months that fail paired coverage/symbol counts,
then compute this mean and valid-month count. Group IDs are 0, 1, 2. The selector
cannot reconstruct monthly calculations from aggregate statistics.
"""
    group_id: int
    mean_ic: float | None
    valid_months: int | None
    minimum_symbols: int | None
    minimum_paired_coverage: float | None


@dataclass(frozen=True)
class Candidate:
    expression: str
    groups: tuple[GroupIC, ...]
    control_correlations: tuple[tuple[str, float | None], ...]


@dataclass(frozen=True)
class CandidateAssessment:
    expression: str
    direction: int | None
    primary: float | None
    secondary: float | None
    node_count: int | None
    depth: int | None
    mechanism_terminals: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return not self.reasons


@dataclass(frozen=True)
class SelectionResult:
    manifest_sha256: str
    selected: tuple[CandidateAssessment, ...]
    eligible_not_selected: tuple[CandidateAssessment, ...]
    rejected: tuple[CandidateAssessment, ...]


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _expression_details(expression: str) -> tuple[set[str], int, int]:
    """Inspect terminal DSL without executing it; leaves have depth zero.

    Calls count as one GP node; numeric windows and industry metadata are
    parameters, not GP nodes. The nightly GP export adds comparison ``*1.0``
    casts and a ``>0`` wrapper around where conditions; those are not new nodes.
    Function identifiers never count as referenced terminals.
"""
    def visit(node: ast.AST) -> tuple[set[str], int, int]:
        if isinstance(node, ast.Name):
            return {node.id}, 1, 0
        if isinstance(node, ast.Constant) and _finite(node.value):
            return set(), 1, 0
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)
                and isinstance(node.left, ast.Compare)
                and isinstance(node.right, ast.Constant) and node.right.value == 1.0):
            return visit(node.left)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            arguments = list(node.args)
            if node.func.id == "where" and len(arguments) == 3:
                condition = arguments[0]
                if (isinstance(condition, ast.Compare) and len(condition.ops) == 1
                        and isinstance(condition.ops[0], ast.Gt)
                        and isinstance(condition.comparators[0], ast.Constant)
                        and condition.comparators[0].value == 0):
                    arguments[0] = condition.left
            if (node.func.id == "ind_neutralize" and len(arguments) == 2
                    and isinstance(arguments[1], ast.Name) and arguments[1].id == "industry_l1"):
                arguments = arguments[:1]
            operands = [arg for arg in arguments
                        if not (isinstance(arg, ast.Constant) and _finite(arg.value))]
            if not operands:
                raise ValueError("Function call has no signal operand")
        elif isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            operands = [node.left, node.right]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operands = [node.operand]
        elif (isinstance(node, ast.Compare) and len(node.ops) == 1
              and isinstance(node.ops[0], (ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq))):
            operands = [node.left, node.comparators[0]]
        else:
            raise ValueError("Unsupported terminal expression syntax")
        children = [visit(child) for child in operands]
        return (set().union(*(child[0] for child in children)),
                1 + sum(child[1] for child in children), 1 + max(child[2] for child in children))

    try:
        return visit(ast.parse(expression, mode="eval").body)
    except (SyntaxError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid terminal expression") from exc


def _validate_context(manifest: MechanismManifest | None, control_ids: Sequence[str]) -> None:
    if not isinstance(manifest, MechanismManifest):
        raise ValueError("A frozen nonempty mechanism manifest is required before selection")
    if (isinstance(control_ids, (str, bytes)) or not control_ids
            or any(not isinstance(value, str) or not value.strip()
                               for value in control_ids)
            or len(set(control_ids)) != len(control_ids)):
        raise ValueError("Explicit unique frozen control IDs are required")


def assess_candidate(candidate: Candidate, *, manifest: MechanismManifest | None,
                     control_ids: Sequence[str], rules: SelectionRules) -> CandidateAssessment:
    """Return hard-requirement failures; missing/nonfinite measurements never become zero."""
    _validate_context(manifest, control_ids)
    assert manifest is not None
    reasons: list[str] = []
    referenced: tuple[str, ...] = ()
    node_count = depth = None
    try:
        names, node_count, depth = _expression_details(candidate.expression)
        referenced = tuple(sorted(names & {row.terminal_id for row in manifest.terminals}))
        if not referenced:
            reasons.append("required_mechanism_not_referenced")
        if depth > rules.max_depth:
            reasons.append("expression_exceeds_max_depth")
    except ValueError:
        reasons.append("invalid_expression")

    group_ids = [group.group_id for group in candidate.groups]
    if (len(group_ids) != rules.sample_groups
            or any(type(group) is not int for group in group_ids)
            or set(group_ids) != set(range(rules.sample_groups))):
        reasons.append("incomplete_or_duplicate_groups")
    group_means: list[float] = []
    for group in sorted(candidate.groups, key=lambda item: str(item.group_id)):
        label = f"group_{group.group_id}"
        if not _finite(group.mean_ic) or not -1 <= group.mean_ic <= 1:
            reasons.append(f"{label}:invalid_mean_ic")
        else:
            group_means.append(float(group.mean_ic))
        if (type(group.valid_months) is not int
                or group.valid_months < rules.minimum_valid_months_per_group):
            reasons.append(f"{label}:insufficient_valid_months")
        if (type(group.minimum_symbols) is not int
                or group.minimum_symbols < rules.minimum_symbols_per_month):
            reasons.append(f"{label}:insufficient_symbols")
        if (not _finite(group.minimum_paired_coverage)
                or not rules.minimum_paired_coverage <= group.minimum_paired_coverage <= 1):
            reasons.append(f"{label}:insufficient_paired_coverage")

    direction = primary = None
    if (len(group_means) == rules.sample_groups
            and "incomplete_or_duplicate_groups" not in reasons):
        direction = 1 if math.fsum(group_means) / len(group_means) >= 0 else -1
        primary = min(direction * mean for mean in group_means)
        if primary <= 0:
            reasons.append("nonpositive_directional_group_ic")

    observed_controls = [name for name, _ in candidate.control_correlations]
    if (len(observed_controls) != len(control_ids)
            or set(observed_controls) != set(control_ids)):
        reasons.append("incomplete_or_duplicate_control_correlations")
    correlations = [value for _, value in candidate.control_correlations]
    secondary = None
    if not correlations or any(not _finite(value) or not -1 <= value <= 1
                               for value in correlations):
        reasons.append("invalid_control_correlations")
    elif "incomplete_or_duplicate_control_correlations" not in reasons:
        secondary = max(abs(value) for value in correlations)
    return CandidateAssessment(candidate.expression, direction, primary, secondary, node_count,
                               depth, referenced, tuple(reasons))


def rank_candidates(candidates: Sequence[Candidate], *, manifest: MechanismManifest | None,
                    control_ids: Sequence[str], rules: SelectionRules) -> SelectionResult:
    """Select at most the registered limit with a deterministic remaining-best band.

At EACH selection step, take the highest primary among remaining eligible
candidates, form its inclusive 0.001 IC band, and select exactly one candidate
by secondary, node count, expression lexical order. Remove that candidate and
rebuild the band. This is not a pairwise comparator or a one-time band sort.
Decimal conversion of reported floats preserves the inclusive decimal boundary.
Identical expressions are invalid batch input: callers must consolidate their
measurements, rather than choosing one possibly inconsistent observation.
"""
    _validate_context(manifest, control_ids)
    assert manifest is not None
    expressions = [candidate.expression for candidate in candidates]
    if len(set(expressions)) != len(expressions):
        raise ValueError("Duplicate candidate expressions must be consolidated before selection")
    assessments = [assess_candidate(candidate, manifest=manifest, control_ids=control_ids,
                                    rules=rules) for candidate in candidates]
    remaining = [row for row in assessments if row.eligible]
    ranking = []
    while remaining:
        best = max(Decimal(str(row.primary)) for row in remaining)
        band = [row for row in remaining if best - Decimal(str(row.primary)) <= _IC_BAND]
        winner = min(band, key=lambda row: (row.secondary, row.node_count, row.expression))
        ranking.append(winner)
        remaining.remove(winner)
    return SelectionResult(
        manifest.sha256, tuple(ranking[:rules.maximum_candidates]),
        tuple(ranking[rules.maximum_candidates:]),
        tuple(sorted((row for row in assessments if not row.eligible),
                     key=lambda row: row.expression)),
    )
