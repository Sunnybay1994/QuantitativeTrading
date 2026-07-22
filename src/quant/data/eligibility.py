"""由港股通基线快照和官方生效事件重建可投资域。"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass

import polars as pl

from quant.domain import (
    ConnectEligibilityEventSchema,
    ConnectEligibilitySnapshotSchema,
    ConnectRoute,
    UniverseMembershipSchema,
)

_ALLOWED_ROUTES = frozenset(
    {ConnectRoute.SH_CONNECT.value, ConnectRoute.SZ_CONNECT.value}
)
_REVERSE_CODES = frozenset(
    {
        "REVERSE_AUDIT_INPUT_INVALID",
        "REVERSE_AUDIT_COVERAGE_INVALID",
        "REVERSE_AUDIT_EVENT_CONFLICT",
        "REVERSE_AUDIT_STATE_CONFLICT",
        "REVERSE_AUDIT_COUNT_MISMATCH",
    }
)
_REVERSE_MEMBERSHIP_CODES = frozenset(
    {
        "REVERSE_MEMBERSHIP_INPUT_INVALID",
        "REVERSE_MEMBERSHIP_AUDIT_MISMATCH",
        "REVERSE_MEMBERSHIP_STATE_CONFLICT",
        "REVERSE_MEMBERSHIP_FINAL_STATE_MISMATCH",
    }
)
_ELIGIBILITY_CODES = _REVERSE_CODES | _REVERSE_MEMBERSHIP_CODES


class EligibilityHistoryError(ValueError):
    """基线覆盖不足或事件状态不一致，禁止生成可能含未来函数的历史名单。"""

    def __init__(self, message: str) -> None:
        self.code = message if message in _ELIGIBILITY_CODES else message
        super().__init__(message)

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else self.code


@dataclass(frozen=True, slots=True)
class VerifiedReverseEligibilityAudit:
    """逆向审计通过后的不可变结果；构造时重算字段不变量。"""

    route: str
    baseline_date: dt.date
    snapshot_date: dt.date
    expected_baseline_count: int
    baseline_symbols: tuple[str, ...]
    current_count: int
    event_count: int
    reverse_count: int
    event_min_date: dt.date | None
    event_max_date: dt.date | None

    def __post_init__(self) -> None:
        try:
            if type(self.route) is not str or self.route not in _ALLOWED_ROUTES:
                raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
            if type(self.baseline_date) is not dt.date or type(self.snapshot_date) is not dt.date:
                raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
            if self.snapshot_date <= self.baseline_date:
                raise EligibilityHistoryError("REVERSE_AUDIT_COVERAGE_INVALID")
            if (
                type(self.expected_baseline_count) is not int
                or self.expected_baseline_count <= 0
            ):
                raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
            if type(self.baseline_symbols) is not tuple or any(
                type(symbol) is not str for symbol in self.baseline_symbols
            ):
                raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
            if (
                type(self.current_count) is not int
                or type(self.event_count) is not int
                or type(self.reverse_count) is not int
                or self.current_count <= 0
                or self.event_count < 0
                or self.reverse_count <= 0
            ):
                raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
            if self.reverse_count != len(self.baseline_symbols):
                raise EligibilityHistoryError("REVERSE_AUDIT_COUNT_MISMATCH")
            if self.reverse_count != self.expected_baseline_count:
                raise EligibilityHistoryError("REVERSE_AUDIT_COUNT_MISMATCH")
            if list(self.baseline_symbols) != sorted(self.baseline_symbols):
                raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
            if len(set(self.baseline_symbols)) != len(self.baseline_symbols):
                raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
            if self.event_count == 0:
                if self.event_min_date is not None or self.event_max_date is not None:
                    raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
            else:
                if (
                    type(self.event_min_date) is not dt.date
                    or type(self.event_max_date) is not dt.date
                ):
                    raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
                if not (
                    self.baseline_date
                    < self.event_min_date
                    <= self.event_max_date
                    <= self.snapshot_date
                ):
                    raise EligibilityHistoryError("REVERSE_AUDIT_COVERAGE_INVALID")
        except EligibilityHistoryError:
            raise
        except Exception:
            raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID") from None


def verify_reverse_eligibility_history(
    snapshot: pl.DataFrame,
    events: pl.DataFrame,
    *,
    route: str,
    baseline_date: dt.date,
    expected_baseline_count: int,
) -> VerifiedReverseEligibilityAudit:
    """用 current snapshot 与完整事件流逆向回放到官方启动基线；失败 fail-closed。"""
    try:
        return _verify_reverse_eligibility_history(
            snapshot,
            events,
            route=route,
            baseline_date=baseline_date,
            expected_baseline_count=expected_baseline_count,
        )
    except EligibilityHistoryError:
        raise
    except Exception:
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID") from None


def _verify_reverse_eligibility_history(
    snapshot: pl.DataFrame,
    events: pl.DataFrame,
    *,
    route: str,
    baseline_date: dt.date,
    expected_baseline_count: int,
) -> VerifiedReverseEligibilityAudit:
    if type(route) is not str or route not in _ALLOWED_ROUTES:
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
    if type(baseline_date) is not dt.date:
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
    if type(expected_baseline_count) is not int or expected_baseline_count <= 0:
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
    if not isinstance(snapshot, pl.DataFrame) or not isinstance(events, pl.DataFrame):
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")

    _require_exact_dtypes_snapshot(snapshot)
    _require_exact_dtypes_events(events)

    try:
        snap = ConnectEligibilitySnapshotSchema.validate(snapshot)
        ev = ConnectEligibilityEventSchema.validate(events)
    except Exception:
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID") from None

    routes = snap.get_column("route").unique().to_list()
    if len(routes) != 1 or routes[0] != route:
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
    dates = snap.get_column("snapshot_date").unique().to_list()
    if len(dates) != 1:
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
    snapshot_date = dates[0]
    if type(snapshot_date) is not dt.date:
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
    if snapshot_date <= baseline_date:
        raise EligibilityHistoryError("REVERSE_AUDIT_COVERAGE_INVALID")
    if not snap.get_column("buy_eligible").dtype == pl.Boolean:
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
    if not snap.get_column("buy_eligible").all():
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")

    if ev.height > 0:
        event_routes = ev.get_column("route").unique().to_list()
        if len(event_routes) != 1 or event_routes[0] != route:
            raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
        too_early = ev.filter(pl.col("effective_date") <= baseline_date)
        too_late = ev.filter(pl.col("effective_date") > snapshot_date)
        if too_early.height > 0 or too_late.height > 0:
            raise EligibilityHistoryError("REVERSE_AUDIT_COVERAGE_INVALID")
        conflicts = (
            ev.group_by("effective_date", "symbol")
            .agg(
                pl.col("action").n_unique().alias("actions"),
                pl.len().alias("rows"),
            )
            .filter((pl.col("actions") > 1) | (pl.col("rows") > 1))
        )
        if not conflicts.is_empty():
            raise EligibilityHistoryError("REVERSE_AUDIT_EVENT_CONFLICT")

    active: set[str] = set(snap.get_column("symbol").to_list())
    current_count = len(active)
    if current_count != snap.height:
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")

    ordered = ev.sort(["effective_date", "symbol"], descending=True)
    for effective_date, symbol, action in ordered.select(
        "effective_date", "symbol", "action"
    ).iter_rows():
        if action == "ADD":
            if symbol not in active:
                raise EligibilityHistoryError("REVERSE_AUDIT_STATE_CONFLICT")
            active.remove(symbol)
        elif action == "REMOVE":
            if symbol in active:
                raise EligibilityHistoryError("REVERSE_AUDIT_STATE_CONFLICT")
            active.add(symbol)
        else:
            raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")

    baseline_symbols = tuple(sorted(active))
    if len(baseline_symbols) != expected_baseline_count:
        raise EligibilityHistoryError("REVERSE_AUDIT_COUNT_MISMATCH")

    if ev.height == 0:
        event_min_date: dt.date | None = None
        event_max_date: dt.date | None = None
    else:
        event_min_date = ev.get_column("effective_date").min()  # type: ignore[assignment]
        event_max_date = ev.get_column("effective_date").max()  # type: ignore[assignment]

    return VerifiedReverseEligibilityAudit(
        route=route,
        baseline_date=baseline_date,
        snapshot_date=snapshot_date,
        expected_baseline_count=expected_baseline_count,
        baseline_symbols=baseline_symbols,
        current_count=current_count,
        event_count=ev.height,
        reverse_count=len(baseline_symbols),
        event_min_date=event_min_date,
        event_max_date=event_max_date,
    )


def build_membership_intervals_from_reverse_audit(
    *,
    audit: VerifiedReverseEligibilityAudit,
    snapshot: pl.DataFrame,
    events: pl.DataFrame,
) -> pl.DataFrame:
    """将 verified reverse baseline 正序回放为成员区间；须重新闭合 audit+snapshot+events。"""
    try:
        return _build_membership_intervals_from_reverse_audit(
            audit=audit,
            snapshot=snapshot,
            events=events,
        )
    except EligibilityHistoryError:
        raise
    except Exception:
        raise EligibilityHistoryError("REVERSE_MEMBERSHIP_INPUT_INVALID") from None


def _audit_fields_equal(
    left: VerifiedReverseEligibilityAudit,
    right: VerifiedReverseEligibilityAudit,
) -> bool:
    return (
        left.route == right.route
        and left.baseline_date == right.baseline_date
        and left.snapshot_date == right.snapshot_date
        and left.expected_baseline_count == right.expected_baseline_count
        and left.baseline_symbols == right.baseline_symbols
        and left.current_count == right.current_count
        and left.event_count == right.event_count
        and left.reverse_count == right.reverse_count
        and left.event_min_date == right.event_min_date
        and left.event_max_date == right.event_max_date
    )


def _assert_no_membership_overlap(frame: pl.DataFrame) -> None:
    for symbol in frame.get_column("symbol").unique().to_list():
        rows = (
            frame.filter(pl.col("symbol") == symbol)
            .sort(["effective_from", "effective_to"])
            .select("effective_from", "effective_to")
        )
        prev_to: dt.date | None = None
        prev_open = False
        for effective_from, effective_to in rows.iter_rows():
            if prev_open:
                raise EligibilityHistoryError("REVERSE_MEMBERSHIP_STATE_CONFLICT")
            if prev_to is not None and effective_from <= prev_to:
                raise EligibilityHistoryError("REVERSE_MEMBERSHIP_STATE_CONFLICT")
            if effective_to is None:
                prev_open = True
                prev_to = None
            else:
                if effective_to < effective_from:
                    raise EligibilityHistoryError("REVERSE_MEMBERSHIP_STATE_CONFLICT")
                prev_to = effective_to


def _build_membership_intervals_from_reverse_audit(
    *,
    audit: VerifiedReverseEligibilityAudit,
    snapshot: pl.DataFrame,
    events: pl.DataFrame,
) -> pl.DataFrame:
    if type(audit) is not VerifiedReverseEligibilityAudit:
        raise EligibilityHistoryError("REVERSE_MEMBERSHIP_INPUT_INVALID")
    if not isinstance(snapshot, pl.DataFrame) or not isinstance(events, pl.DataFrame):
        raise EligibilityHistoryError("REVERSE_MEMBERSHIP_INPUT_INVALID")

    try:
        recomputed = verify_reverse_eligibility_history(
            snapshot,
            events,
            route=audit.route,
            baseline_date=audit.baseline_date,
            expected_baseline_count=audit.expected_baseline_count,
        )
    except EligibilityHistoryError:
        raise EligibilityHistoryError("REVERSE_MEMBERSHIP_AUDIT_MISMATCH") from None

    if not _audit_fields_equal(audit, recomputed):
        raise EligibilityHistoryError("REVERSE_MEMBERSHIP_AUDIT_MISMATCH")

    try:
        snap = ConnectEligibilitySnapshotSchema.validate(snapshot)
        ev = ConnectEligibilityEventSchema.validate(events)
    except Exception:
        raise EligibilityHistoryError("REVERSE_MEMBERSHIP_INPUT_INVALID") from None

    active: dict[str, dt.date] = {
        symbol: recomputed.baseline_date for symbol in recomputed.baseline_symbols
    }
    intervals: list[dict[str, object]] = []
    ordered = ev.sort(["effective_date", "symbol"])
    for effective_date, symbol, action in ordered.select(
        "effective_date", "symbol", "action"
    ).iter_rows():
        if action == "ADD":
            if symbol in active:
                raise EligibilityHistoryError("REVERSE_MEMBERSHIP_STATE_CONFLICT")
            active[symbol] = effective_date
            continue
        if action == "REMOVE":
            if symbol not in active:
                raise EligibilityHistoryError("REVERSE_MEMBERSHIP_STATE_CONFLICT")
            effective_from = active.pop(symbol)
            effective_to = effective_date - dt.timedelta(days=1)
            if effective_to < effective_from:
                raise EligibilityHistoryError("REVERSE_MEMBERSHIP_STATE_CONFLICT")
            intervals.append(
                {
                    "universe": recomputed.route,
                    "symbol": symbol,
                    "effective_from": effective_from,
                    "effective_to": effective_to,
                }
            )
            continue
        raise EligibilityHistoryError("REVERSE_MEMBERSHIP_INPUT_INVALID")

    snapshot_symbols = set(snap.get_column("symbol").to_list())
    if set(active) != snapshot_symbols:
        raise EligibilityHistoryError("REVERSE_MEMBERSHIP_FINAL_STATE_MISMATCH")

    intervals.extend(
        {
            "universe": recomputed.route,
            "symbol": symbol,
            "effective_from": effective_from,
            "effective_to": None,
        }
        for symbol, effective_from in active.items()
    )
    result = pl.DataFrame(
        intervals,
        schema={
            "universe": pl.String,
            "symbol": pl.String,
            "effective_from": pl.Date,
            "effective_to": pl.Date,
        },
    ).sort(["symbol", "effective_from"])
    _assert_no_membership_overlap(result)
    return UniverseMembershipSchema.validate(result)


def _require_exact_dtypes_snapshot(frame: pl.DataFrame) -> None:
    required = {
        "route": pl.String,
        "snapshot_date": pl.Date,
        "symbol": pl.String,
        "name_cn": pl.String,
        "name_en": pl.String,
        "security_type": pl.String,
        "buy_eligible": pl.Boolean,
        "source": pl.String,
    }
    _require_exact_dtypes(frame, required)


def _require_exact_dtypes_events(frame: pl.DataFrame) -> None:
    required = {
        "route": pl.String,
        "effective_date": pl.Date,
        "symbol": pl.String,
        "action": pl.String,
        "name_cn": pl.String,
        "name_en": pl.String,
        "security_type": pl.String,
        "published_date": pl.Date,
        "source": pl.String,
    }
    # published_date 可为全 null 的 Date；缺列或 Datetime 一律拒绝。
    _require_exact_dtypes(frame, required)


def _require_exact_dtypes(frame: pl.DataFrame, required: Mapping[str, object]) -> None:
    if set(frame.columns) != set(required):
        raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")
    for name, expected in required.items():
        actual = frame.schema[name]
        if actual != expected:
            # polars String 别名兼容
            if expected == pl.String and actual in (pl.String, pl.Utf8):
                continue
            raise EligibilityHistoryError("REVERSE_AUDIT_INPUT_INVALID")


def build_membership_intervals(
    snapshot: pl.DataFrame,
    events: pl.DataFrame,
    *,
    route: str,
) -> pl.DataFrame:
    """重建基线日之后的成员区间；不推断基线日前的真实加入日期。"""
    baseline = ConnectEligibilitySnapshotSchema.validate(snapshot).filter(
        pl.col("route") == route
    )
    if baseline.is_empty():
        raise EligibilityHistoryError(f"缺少 {route} 基线快照")
    dates = baseline.get_column("snapshot_date").unique().to_list()
    if len(dates) != 1:
        raise EligibilityHistoryError(f"{route} 基线必须且只能包含一个 snapshot_date")
    baseline_date: dt.date = dates[0]

    route_events = ConnectEligibilityEventSchema.validate(events).filter(
        (pl.col("route") == route) & (pl.col("effective_date") > baseline_date)
    )
    conflicts = (
        route_events.group_by("effective_date", "symbol")
        .agg(pl.col("action").n_unique().alias("actions"))
        .filter(pl.col("actions") > 1)
    )
    if not conflicts.is_empty():
        raise EligibilityHistoryError("同一证券同一生效日同时出现调入和调出")

    active: dict[str, dt.date] = {
        symbol: baseline_date
        for symbol in baseline.filter(pl.col("buy_eligible")).get_column("symbol").to_list()
    }
    intervals: list[dict[str, object]] = []
    for effective_date, symbol, action in route_events.sort(
        ["effective_date", "symbol"]
    ).select("effective_date", "symbol", "action").iter_rows():
        if action == "ADD":
            if symbol in active:
                raise EligibilityHistoryError(
                    f"重复调入仍在池中的证券: {symbol} @ {effective_date}"
                )
            active[symbol] = effective_date
            continue
        if symbol not in active:
            raise EligibilityHistoryError(
                f"调出不在基线/事件状态中的证券: {symbol} @ {effective_date}"
            )
        intervals.append(
            {
                "universe": route,
                "symbol": symbol,
                "effective_from": active.pop(symbol),
                "effective_to": effective_date - dt.timedelta(days=1),
            }
        )

    intervals.extend(
        {
            "universe": route,
            "symbol": symbol,
            "effective_from": effective_from,
            "effective_to": None,
        }
        for symbol, effective_from in active.items()
    )
    result = pl.DataFrame(
        intervals,
        schema={
            "universe": pl.String,
            "symbol": pl.String,
            "effective_from": pl.Date,
            "effective_to": pl.Date,
        },
    ).sort(["symbol", "effective_from"])
    return UniverseMembershipSchema.validate(result)


def eligible_symbols_on(
    intervals: pl.DataFrame,
    *,
    route: str,
    as_of: dt.date,
) -> list[str]:
    """查询某日路由内可买证券；早于覆盖起点时显式失败。"""
    validated = UniverseMembershipSchema.validate(intervals).filter(
        pl.col("universe") == route
    )
    if validated.is_empty():
        raise EligibilityHistoryError(f"缺少 {route} 成员区间")
    coverage_start: dt.date = validated.get_column("effective_from").min()  # type: ignore[assignment]
    if as_of < coverage_start:
        raise EligibilityHistoryError(
            f"查询日 {as_of} 早于可证明覆盖起点 {coverage_start}"
        )
    return (
        validated.filter(
            (pl.col("effective_from") <= as_of)
            & (pl.col("effective_to").is_null() | (pl.col("effective_to") >= as_of))
        )
        .get_column("symbol")
        .sort()
        .to_list()
    )
