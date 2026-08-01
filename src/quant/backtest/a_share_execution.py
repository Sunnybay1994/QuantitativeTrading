"""Pure A-share target-to-order and fee contracts for M3 G7D."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from fractions import Fraction
from typing import TYPE_CHECKING, Literal, TypeAlias, cast

import polars as pl

from quant.domain import (
    AShareBoard,
    Bar1dSchema,
    BenchmarkBar1dSchema,
    CorporateActionLedgerSchema,
    CorporateActionReconciliationSchema,
    ExecutionRejectReason,
    InstrumentSchema,
    OpenExecutionStateSchema,
    OrderSide,
    PriceLimit1dSchema,
    Suspension1dSchema,
    TargetWeightSchema,
    TradeCalendarSchema,
)
from quant.research.m3.contracts import AShareCostPeriod
from quant.research.m3.run_state import ArtifactDigest

if TYPE_CHECKING:
    from quant.research.m3.development_example import (
        VerifiedDevelopmentExampleAShareMarketFacts,
        VerifiedDevelopmentExampleBacktestPlanArtifact,
        VerifiedDevelopmentExampleG1Release,
    )

_RULE_VERSION: Literal["sse_szse_limit_order_quantity_v1"] = (
    "sse_szse_limit_order_quantity_v1"
)
_CENT = Decimal("0.01")
_PRICE_TICK = Decimal("0.01")
_FACT_FILES = (
    "bar_1d.parquet",
    "benchmark_bar_1d.parquet",
    "corporate_action_ledger.parquet",
    "corporate_action_reconciliation.parquet",
    "instrument.parquet",
    "price_limit_1d.parquet",
    "suspension_1d.parquet",
    "trade_calendar.parquet",
)
_PARTIAL_INTERVAL = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


@dataclass(frozen=True)
class AShareMarketFactsIdentityV1:
    schema_version: Literal["m3-a-share-market-facts-v1"]
    g1_release_id: str
    g1_release_manifest_sha256: str
    window_sha256: str
    artifact_digests: tuple[ArtifactDigest, ...]
    input_market_facts_sha256: str

    def __post_init__(self) -> None:
        digests = tuple(
            ArtifactDigest(**asdict(item))
            for item in self.artifact_digests
            if type(item) is ArtifactDigest
        )
        if (
            self.schema_version != "m3-a-share-market-facts-v1"
            or any(
                type(value) is not str
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
                for value in (
                    self.g1_release_id,
                    self.g1_release_manifest_sha256,
                    self.window_sha256,
                    self.input_market_facts_sha256,
                )
            )
            or len(digests) != len(_FACT_FILES)
            or digests != tuple(
                sorted(digests, key=lambda item: item.relative_path)
            )
        ):
            raise ValueError("A-share market facts identity invalid")
        object.__setattr__(self, "artifact_digests", digests)


def build_a_share_market_facts(
    *,
    release: VerifiedDevelopmentExampleG1Release,
    plan: VerifiedDevelopmentExampleBacktestPlanArtifact,
) -> VerifiedDevelopmentExampleAShareMarketFacts:
    """Rebuild a read-only development market-facts view from verified bundles."""
    from quant.research.m3.development_example import (
        VerifiedDevelopmentExampleAShareMarketFacts,
        VerifiedDevelopmentExampleBacktestPlanArtifact,
        VerifiedDevelopmentExampleG1Release,
    )

    if (
        type(release) is not VerifiedDevelopmentExampleG1Release
        or type(plan) is not VerifiedDevelopmentExampleBacktestPlanArtifact
        or release.release_kind != "development_example"
        or plan.release_kind != "development_example"
        or release.formal_gate_eligible is not False
        or plan.formal_gate_eligible is not False
        or release.manifest.example_id != plan.example_id
        or plan.manifest.g1_release_id != release.manifest.release_id
        or plan.manifest.g1_release_manifest_sha256 != release.manifest_sha256
    ):
        raise ValueError("A-share market facts upstream identity mismatch")
    source_paths = dict(release.artifact_paths)
    entries = {item.path: item for item in release.manifest.files}
    schemas = {
        "instrument.parquet": InstrumentSchema,
        "trade_calendar.parquet": TradeCalendarSchema,
        "bar_1d.parquet": Bar1dSchema,
        "price_limit_1d.parquet": PriceLimit1dSchema,
        "suspension_1d.parquet": Suspension1dSchema,
        "corporate_action_ledger.parquet": CorporateActionLedgerSchema,
        "corporate_action_reconciliation.parquet": CorporateActionReconciliationSchema,
        "benchmark_bar_1d.parquet": BenchmarkBar1dSchema,
    }
    frames: dict[str, pl.DataFrame] = {}
    digests: list[ArtifactDigest] = []
    for name in _FACT_FILES:
        path = source_paths.get(name)
        entry = entries.get(name)
        if path is None or entry is None or path.name != name:
            raise ValueError("A-share market facts artifact closure invalid")
        raw = path.read_bytes()
        sha256 = hashlib.sha256(raw).hexdigest()
        if len(raw) != entry.size_bytes or sha256 != entry.sha256:
            raise ValueError("A-share market facts artifact digest drift")
        frames[name] = schemas[name].validate(pl.read_parquet(path))
        digests.append(
            ArtifactDigest(
                root_alias="development_g1_release",
                relative_path=f"contract/{name}",
                size_bytes=len(raw),
                sha256=sha256,
            )
        )
    _validate_market_fact_closure(frames)
    window_sha256 = hashlib.sha256(
        _canonical_json_bytes(asdict(plan.manifest.window))
    ).hexdigest()
    ordered_digests = tuple(sorted(digests, key=lambda item: item.relative_path))
    identity_payload = {
        "artifact_digests": [asdict(item) for item in ordered_digests],
        "g1_release_id": release.manifest.release_id,
        "g1_release_manifest_sha256": release.manifest_sha256,
        "schema_version": "m3-a-share-market-facts-v1",
        "window_sha256": window_sha256,
    }
    identity = AShareMarketFactsIdentityV1(
        schema_version="m3-a-share-market-facts-v1",
        g1_release_id=release.manifest.release_id,
        g1_release_manifest_sha256=release.manifest_sha256,
        window_sha256=window_sha256,
        artifact_digests=ordered_digests,
        input_market_facts_sha256=hashlib.sha256(
            _canonical_json_bytes(identity_payload)
        ).hexdigest(),
    )
    return VerifiedDevelopmentExampleAShareMarketFacts(
        release_kind="development_example",
        formal_gate_eligible=False,
        example_id=release.manifest.example_id,
        identity=identity,
        instruments=frames["instrument.parquet"],
        calendar=frames["trade_calendar.parquet"],
        bars=frames["bar_1d.parquet"],
        limits=frames["price_limit_1d.parquet"],
        suspensions=frames["suspension_1d.parquet"],
        corporate_actions=frames["corporate_action_ledger.parquet"],
        corporate_action_reconciliation=frames[
            "corporate_action_reconciliation.parquet"
        ],
        benchmark_bars=frames["benchmark_bar_1d.parquet"],
    )


def build_open_execution_states(
    *,
    facts: VerifiedDevelopmentExampleAShareMarketFacts,
    date: dt.date,
    symbols: tuple[str, ...],
) -> pl.DataFrame:
    """Project opening-only execution facts; later OHLCV fields are ignored."""
    from quant.research.m3.development_example import (
        VerifiedDevelopmentExampleAShareMarketFacts,
    )

    if (
        type(facts) is not VerifiedDevelopmentExampleAShareMarketFacts
        or type(date) is not dt.date
        or type(symbols) is not tuple
        or len(set(symbols)) != len(symbols)
        or any(type(symbol) is not str for symbol in symbols)
    ):
        raise ValueError("open execution state inputs invalid")
    bars = facts.bars.filter(pl.col("trade_date") == date)
    limits = facts.limits.filter(pl.col("trade_date") == date)
    suspensions = facts.suspensions.filter(pl.col("trade_date") == date)
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        bar_rows = bars.filter(pl.col("symbol") == symbol)
        limit_rows = limits.filter(pl.col("symbol") == symbol)
        suspension_rows = suspensions.filter(pl.col("symbol") == symbol)
        if max(bar_rows.height, limit_rows.height, suspension_rows.height) > 1:
            raise ValueError("open execution state key not unique")
        suspension = (
            None if suspension_rows.is_empty() else suspension_rows.row(0, named=True)
        )
        full_day = bool(
            suspension is not None
            and suspension["suspension_scope"] == "FULL_DAY"
        )
        bar = None if bar_rows.is_empty() else bar_rows.row(0, named=True)
        if full_day:
            rows.append(_open_state_row(
                date=date,
                symbol=symbol,
                open_value=None,
                full_day=True,
                partial_status="NOT_APPLICABLE",
                limit=None,
                buy_allowed=False,
                sell_allowed=False,
                reason="SUSPENDED",
            ))
            continue
        if limit_rows.height != 1:
            raise ValueError("non-full-day price limit missing")
        limit = limit_rows.row(0, named=True)
        if (
            limit["has_price_limit"] is not True
            or limit["up_limit"] is None
            or limit["down_limit"] is None
        ):
            raise ValueError("non-full-day price limit invalid")
        partial_status = "NOT_APPLICABLE"
        reason: str | None = None
        allowed = True
        if suspension is not None:
            partial_status = _partial_open_status(cast(str, suspension["suspension_detail"]))
            if partial_status == "SUSPENDED_AT_OPEN":
                allowed, reason = False, "SUSPENDED"
            elif partial_status == "OPEN_UNKNOWN":
                allowed, reason = False, "OPEN_UNKNOWN"
        if bar is None:
            allowed, reason = False, "MISSING_OPEN"
        open_value = None if bar is None else cast(float, bar["open"])
        buy_allowed = allowed
        sell_allowed = allowed
        if allowed and open_value is not None:
            open_decimal = Decimal(str(open_value))
            if open_decimal >= Decimal(str(limit["up_limit"])) - _PRICE_TICK / 2:
                buy_allowed = False
            if open_decimal <= Decimal(str(limit["down_limit"])) + _PRICE_TICK / 2:
                sell_allowed = False
        rows.append(_open_state_row(
            date=date,
            symbol=symbol,
            open_value=open_value,
            full_day=False,
            partial_status=partial_status,
            limit=limit,
            buy_allowed=buy_allowed,
            sell_allowed=sell_allowed,
            reason=reason,
        ))
    frame = pl.DataFrame(rows, schema={
        "date": pl.Date,
        "symbol": pl.Utf8,
        "open": pl.Float64,
        "has_open": pl.Boolean,
        "full_day_suspended": pl.Boolean,
        "partial_open_status": pl.Utf8,
        "has_price_limit": pl.Boolean,
        "up_limit": pl.Float64,
        "down_limit": pl.Float64,
        "buy_allowed": pl.Boolean,
        "sell_allowed": pl.Boolean,
        "reason": pl.Utf8,
    })
    return OpenExecutionStateSchema.validate(frame)


def _validate_market_fact_closure(frames: dict[str, pl.DataFrame]) -> None:
    bars = frames["bar_1d.parquet"]
    limits = frames["price_limit_1d.parquet"]
    suspensions = frames["suspension_1d.parquet"]
    bar_keys = set(bars.select("symbol", "trade_date").iter_rows())
    limit_keys = set(limits.select("symbol", "trade_date").iter_rows())
    full_day_keys = set(
        suspensions.filter(pl.col("suspension_scope") == "FULL_DAY")
        .select("symbol", "trade_date")
        .iter_rows()
    )
    if bar_keys != limit_keys or bar_keys & full_day_keys:
        raise ValueError("A-share market facts execution closure invalid")
    actions = frames["corporate_action_ledger.parquet"]
    reconciliations = frames["corporate_action_reconciliation.parquet"]
    reconciliation_keys = set(
        reconciliations.select(
            "symbol", pl.col("effective_date").alias("trade_date")
        ).iter_rows()
    )
    for symbol, ex_date in actions.select("symbol", "ex_date").iter_rows():
        key = (symbol, ex_date)
        if key not in bar_keys and not (
            key in full_day_keys and key in reconciliation_keys
        ):
            raise ValueError("A-share corporate action market fact missing")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: item.isoformat()
        if isinstance(item, (dt.date, dt.datetime))
        else str(item),
    ).encode("utf-8")


def _partial_open_status(detail: str) -> str:
    if type(detail) is not str or not detail:
        return "OPEN_UNKNOWN"
    intervals = detail.split(" | ")
    if " | ".join(intervals) != detail:
        return "OPEN_UNKNOWN"
    open_minute = 9 * 60 + 30
    parsed: list[tuple[int, int]] = []
    for interval in intervals:
        match = _PARTIAL_INTERVAL.fullmatch(interval)
        if match is None:
            return "OPEN_UNKNOWN"
        start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
        if (
            start_hour > 23
            or end_hour > 23
            or start_minute > 59
            or end_minute > 59
        ):
            return "OPEN_UNKNOWN"
        start = start_hour * 60 + start_minute
        end = end_hour * 60 + end_minute
        if start >= end:
            return "OPEN_UNKNOWN"
        parsed.append((start, end))
    if any(start <= open_minute < end for start, end in parsed):
        return "SUSPENDED_AT_OPEN"
    return "PROVEN_OPEN_TRADABLE"


def _open_state_row(
    *,
    date: dt.date,
    symbol: str,
    open_value: float | None,
    full_day: bool,
    partial_status: str,
    limit: dict[str, object] | None,
    buy_allowed: bool,
    sell_allowed: bool,
    reason: str | None,
) -> dict[str, object]:
    return {
        "date": date,
        "symbol": symbol,
        "open": open_value,
        "has_open": open_value is not None,
        "full_day_suspended": full_day,
        "partial_open_status": partial_status,
        "has_price_limit": limit is not None,
        "up_limit": None if limit is None else limit["up_limit"],
        "down_limit": None if limit is None else limit["down_limit"],
        "buy_allowed": buy_allowed,
        "sell_allowed": sell_allowed,
        "reason": reason,
    }


@dataclass(frozen=True)
class AccountPosition:
    symbol: str
    quantity: int
    sellable_quantity: int
    unsettled_quantity: int
    mark_price: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.symbol) is not str
            or not self.symbol.endswith((".SH", ".SZ"))
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.quantity,
                    self.sellable_quantity,
                    self.unsettled_quantity,
                )
            )
            or self.sellable_quantity + self.unsettled_quantity != self.quantity
            or type(self.mark_price) is not Decimal
            or not self.mark_price.is_finite()
            or self.mark_price <= 0
        ):
            raise ValueError("account position invalid")


PositionBook: TypeAlias = tuple[AccountPosition, ...]


@dataclass(frozen=True)
class AShareFeeComponents:
    commission: Decimal
    stamp_tax: Decimal
    transfer_fee: Decimal

    def __post_init__(self) -> None:
        if any(
            type(value) is not Decimal or not value.is_finite() or value < 0
            for value in (self.commission, self.stamp_tax, self.transfer_fee)
        ):
            raise ValueError("A-share fees invalid")


@dataclass(frozen=True)
class AShareOrderQuantityRule:
    rule_version: Literal["sse_szse_limit_order_quantity_v1"]
    board: AShareBoard
    buy_min_quantity: int
    buy_increment: int
    sell_min_quantity: int
    sell_increment: int
    odd_lot_sell_policy: Literal[
        "MATCH_POSITION_REMAINDER", "FULL_BALANCE_BELOW_MIN"
    ]

    def __post_init__(self) -> None:
        if (
            self.rule_version != _RULE_VERSION
            or type(self.board) is not AShareBoard
            or any(
                type(value) is not int or value <= 0
                for value in (
                    self.buy_min_quantity,
                    self.buy_increment,
                    self.sell_min_quantity,
                    self.sell_increment,
                )
            )
            or self.odd_lot_sell_policy
            not in {"MATCH_POSITION_REMAINDER", "FULL_BALANCE_BELOW_MIN"}
        ):
            raise ValueError("A-share quantity rule invalid")


@dataclass(frozen=True)
class TargetOrderIntent:
    symbol: str
    side: OrderSide
    target_weight: Decimal
    target_notional: Decimal
    raw_target_quantity: int | None
    target_position_quantity: int | None
    requested_quantity: int | None
    quantity_rule: AShareOrderQuantityRule

    def __post_init__(self) -> None:
        quantities = (
            self.raw_target_quantity,
            self.target_position_quantity,
            self.requested_quantity,
        )
        if (
            type(self.symbol) is not str
            or type(self.side) is not OrderSide
            or any(
                type(value) is not Decimal or not value.is_finite() or value < 0
                for value in (self.target_weight, self.target_notional)
            )
            or any(value is not None and (type(value) is not int or value < 0) for value in quantities)
            or type(self.quantity_rule) is not AShareOrderQuantityRule
        ):
            raise ValueError("target order intent invalid")


@dataclass(frozen=True)
class ExecutionFill:
    symbol: str
    side: OrderSide
    quantity: int
    reference_open: Decimal
    execution_price: Decimal
    notional: Decimal
    fees: AShareFeeComponents
    slippage_cost: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.side) is not OrderSide
            or type(self.quantity) is not int
            or self.quantity <= 0
            or any(
                type(value) is not Decimal or not value.is_finite() or value < 0
                for value in (
                    self.reference_open,
                    self.execution_price,
                    self.notional,
                    self.slippage_cost,
                )
            )
            or type(self.fees) is not AShareFeeComponents
        ):
            raise ValueError("execution fill invalid")


@dataclass(frozen=True)
class ExecutionRejection:
    symbol: str
    side: OrderSide
    reason: ExecutionRejectReason
    requested_quantity: int | None
    filled_quantity: int
    rejected_quantity: int | None
    rejected_notional: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.side) is not OrderSide
            or type(self.reason) is not ExecutionRejectReason
            or type(self.filled_quantity) is not int
            or self.filled_quantity < 0
            or self.requested_quantity is not None
            and (type(self.requested_quantity) is not int or self.requested_quantity < 0)
            or self.rejected_quantity is not None
            and (type(self.rejected_quantity) is not int or self.rejected_quantity < 0)
            or self.requested_quantity is not None
            and self.rejected_quantity is not None
            and self.requested_quantity
            != self.filled_quantity + self.rejected_quantity
            or type(self.rejected_notional) is not Decimal
            or not self.rejected_notional.is_finite()
            or self.rejected_notional < 0
        ):
            raise ValueError("execution rejection invalid")


@dataclass(frozen=True)
class ExecutionBatch:
    cash: Decimal
    positions: PositionBook
    fills: tuple[ExecutionFill, ...]
    rejections: tuple[ExecutionRejection, ...]

    def __post_init__(self) -> None:
        if (
            type(self.cash) is not Decimal
            or not self.cash.is_finite()
            or self.cash < 0
            or any(type(item) is not AccountPosition for item in self.positions)
            or len({item.symbol for item in self.positions}) != len(self.positions)
            or any(type(item) is not ExecutionFill for item in self.fills)
            or any(type(item) is not ExecutionRejection for item in self.rejections)
        ):
            raise ValueError("execution batch invalid")


@dataclass(frozen=True)
class BuyAllocation:
    lambda_fraction: Fraction | None
    batch: ExecutionBatch

    def __post_init__(self) -> None:
        if (
            self.lambda_fraction is not None
            and (
                type(self.lambda_fraction) is not Fraction
                or not Fraction(0) <= self.lambda_fraction <= Fraction(1)
            )
            or type(self.batch) is not ExecutionBatch
        ):
            raise ValueError("buy allocation invalid")


def resolve_a_share_order_quantity_rule(
    *, symbol: str, date: dt.date
) -> AShareOrderQuantityRule:
    if type(symbol) is not str or type(date) is not dt.date:
        raise ValueError("A-share rule lookup invalid")
    prefix, suffix = symbol[:3], symbol[-3:]
    if len(symbol) != 9 or symbol[6] != ".":
        raise ValueError("A-share symbol invalid")
    if suffix == ".SH" and prefix in {"600", "601", "603", "605"}:
        board = AShareBoard.SSE_MAIN
    elif suffix == ".SH" and prefix in {"688", "689"}:
        if date < dt.date(2019, 7, 22):
            raise ValueError("STAR rule not effective")
        board = AShareBoard.SSE_STAR
    elif suffix == ".SZ" and prefix in {"000", "001", "002", "003"}:
        board = AShareBoard.SZSE_MAIN
    elif suffix == ".SZ" and prefix in {"300", "301"}:
        board = AShareBoard.SZSE_CHINEXT
    else:
        raise ValueError("unsupported A-share board")
    if board is AShareBoard.SSE_STAR:
        return AShareOrderQuantityRule(
            _RULE_VERSION, board, 200, 1, 200, 1, "FULL_BALANCE_BELOW_MIN"
        )
    return AShareOrderQuantityRule(
        _RULE_VERSION, board, 100, 100, 100, 100, "MATCH_POSITION_REMAINDER"
    )


def largest_valid_buy_quantity(
    *, requested_quantity: int, rule: AShareOrderQuantityRule
) -> int:
    _validate_quantity(requested_quantity)
    if type(rule) is not AShareOrderQuantityRule:
        raise ValueError("quantity rule invalid")
    if requested_quantity < rule.buy_min_quantity:
        return 0
    if rule.board is AShareBoard.SSE_STAR:
        return requested_quantity
    return requested_quantity - requested_quantity % rule.buy_increment


def largest_valid_sell_quantity(
    *, requested_quantity: int, position_quantity: int, rule: AShareOrderQuantityRule
) -> int:
    _validate_quantity(requested_quantity)
    _validate_quantity(position_quantity)
    if type(rule) is not AShareOrderQuantityRule:
        raise ValueError("sell quantity invalid")
    capped_quantity = min(requested_quantity, position_quantity)
    if capped_quantity == position_quantity:
        return capped_quantity
    if rule.board is AShareBoard.SSE_STAR:
        return capped_quantity if capped_quantity >= rule.sell_min_quantity else 0
    round_lot = capped_quantity - capped_quantity % rule.sell_increment
    remainder = position_quantity % rule.sell_increment
    odd_lot = 0
    if remainder and capped_quantity >= remainder:
        odd_lot = capped_quantity - (capped_quantity - remainder) % rule.sell_increment
    return max(round_lot, odd_lot)


def compute_a_share_fee_components(
    *, notional: Decimal, side: OrderSide, cost_period: AShareCostPeriod
) -> AShareFeeComponents:
    if (
        type(notional) is not Decimal
        or not notional.is_finite()
        or notional < 0
        or type(side) is not OrderSide
        or type(cost_period) is not AShareCostPeriod
    ):
        raise ValueError("fee inputs invalid")
    commission = max(
        notional * cost_period.commission_rate, cost_period.commission_min
    ).quantize(_CENT, rounding=ROUND_HALF_UP)
    stamp = (
        notional * cost_period.stamp_tax_sell
        if side is OrderSide.SELL
        else Decimal("0")
    ).quantize(_CENT, rounding=ROUND_HALF_UP)
    transfer = (notional * cost_period.transfer_fee).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    return AShareFeeComponents(commission, stamp, transfer)


def build_target_order_intents(
    *,
    date: dt.date,
    targets: pl.DataFrame,
    positions: PositionBook,
    open_states: pl.DataFrame,
    pre_trade_equity: Decimal,
) -> tuple[TargetOrderIntent, ...]:
    if (
        type(date) is not dt.date
        or type(pre_trade_equity) is not Decimal
        or not pre_trade_equity.is_finite()
        or pre_trade_equity <= 0
    ):
        raise ValueError("target intent inputs invalid")
    clean = TargetWeightSchema.validate(targets)
    if clean["as_of"].n_unique() != 1 or clean["symbol"].n_unique() != clean.height:
        raise ValueError("target intent target domain invalid")
    _validate_open_states(open_states, date)
    if len({item.symbol for item in positions}) != len(positions):
        raise ValueError("position book duplicate symbols")
    by_position = {item.symbol: item for item in positions}
    by_open = {cast(str, row["symbol"]): row for row in open_states.iter_rows(named=True)}
    intents: list[TargetOrderIntent] = []
    for row in clean.sort("symbol").iter_rows(named=True):
        symbol = cast(str, row["symbol"])
        if symbol not in by_open:
            raise ValueError("target open state missing")
        rule = resolve_a_share_order_quantity_rule(symbol=symbol, date=date)
        position = by_position.get(symbol)
        current_quantity = 0 if position is None else position.quantity
        weight = Decimal(str(row["weight"]))
        target_notional = weight * pre_trade_equity
        state = by_open[symbol]
        open_value = state["open"]
        if open_value is None or not cast(bool, state["has_open"]):
            current_value = (
                Decimal("0")
                if position is None
                else Decimal(position.quantity) * position.mark_price
            )
            if target_notional == current_value:
                continue
            side = OrderSide.BUY if target_notional > current_value else OrderSide.SELL
            intents.append(
                TargetOrderIntent(
                    symbol, side, weight, target_notional, None, None, None, rule
                )
            )
            continue
        open_price = Decimal(str(open_value))
        if open_price <= 0:
            raise ValueError("target open price invalid")
        raw = int((target_notional / open_price).to_integral_value(rounding=ROUND_FLOOR))
        target_quantity = (
            0 if weight == 0 else largest_valid_buy_quantity(requested_quantity=raw, rule=rule)
        )
        lot_constrained_buy = (
            weight > 0 and raw > 0 and target_quantity == 0 and current_quantity == 0
        )
        if target_quantity == current_quantity and not lot_constrained_buy:
            continue
        side = (
            OrderSide.BUY
            if target_quantity > current_quantity or lot_constrained_buy
            else OrderSide.SELL
        )
        intents.append(
            TargetOrderIntent(
                symbol=symbol,
                side=side,
                target_weight=weight,
                target_notional=target_notional,
                raw_target_quantity=raw,
                target_position_quantity=target_quantity,
                requested_quantity=abs(target_quantity - current_quantity),
                quantity_rule=rule,
            )
        )
    return tuple(intents)


def execute_sell_intents(
    *,
    intents: tuple[TargetOrderIntent, ...],
    open_states: pl.DataFrame,
    positions: PositionBook,
    cash: Decimal,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> ExecutionBatch:
    """Execute valid sell quantities while preserving T+1 and lot residuals."""
    _validate_execution_inputs(
        intents=intents,
        side=OrderSide.SELL,
        open_states=open_states,
        positions=positions,
        cash=cash,
        cost_period=cost_period,
        price_tick=price_tick,
    )
    state_by_symbol = _state_map(open_states)
    position_by_symbol = {item.symbol: item for item in positions}
    fills: list[ExecutionFill] = []
    rejections: list[ExecutionRejection] = []
    updated_cash = cash
    for intent in sorted(intents, key=lambda item: item.symbol):
        state = state_by_symbol[intent.symbol]
        blocked = _blocked_reason(state=state, side=OrderSide.SELL)
        if blocked is not None:
            rejections.append(_whole_rejection(intent, state, blocked))
            continue
        position = position_by_symbol.get(intent.symbol)
        if position is None:
            raise ValueError("sell position missing")
        requested = intent.requested_quantity
        if requested is None:
            raise ValueError("sell requested quantity unknown with trusted open")
        sellable_cap = min(requested, position.sellable_quantity)
        t1_residual = requested - sellable_cap
        valid = largest_valid_sell_quantity(
            requested_quantity=sellable_cap,
            position_quantity=position.quantity,
            rule=intent.quantity_rule,
        )
        lot_residual = sellable_cap - valid
        open_price = Decimal(str(state["open"]))
        if valid:
            execution_price = _execution_price(
                open_price=open_price,
                side=OrderSide.SELL,
                slippage=cost_period.slippage,
                price_tick=price_tick,
                lower=Decimal(str(state["down_limit"])),
                upper=Decimal(str(state["up_limit"])),
            )
            notional = execution_price * valid
            fees = compute_a_share_fee_components(
                notional=notional,
                side=OrderSide.SELL,
                cost_period=cost_period,
            )
            fill = ExecutionFill(
                symbol=intent.symbol,
                side=OrderSide.SELL,
                quantity=valid,
                reference_open=open_price,
                execution_price=execution_price,
                notional=notional,
                fees=fees,
                slippage_cost=(open_price - execution_price) * valid,
            )
            fills.append(fill)
            updated_cash += notional - _fee_total(fees)
            position_by_symbol[intent.symbol] = AccountPosition(
                symbol=position.symbol,
                quantity=position.quantity - valid,
                sellable_quantity=position.sellable_quantity - valid,
                unsettled_quantity=position.unsettled_quantity,
                mark_price=position.mark_price,
            )
        if t1_residual:
            rejections.append(_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.T_PLUS_ONE,
                quantity=t1_residual,
                open_price=open_price,
            ))
        if lot_residual:
            rejections.append(_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.LOT_CONSTRAINT,
                quantity=lot_residual,
                open_price=open_price,
            ))
    return ExecutionBatch(
        cash=updated_cash,
        positions=tuple(sorted(position_by_symbol.values(), key=lambda item: item.symbol)),
        fills=tuple(fills),
        rejections=tuple(rejections),
    )


def allocate_buy_lots(
    *,
    intents: tuple[TargetOrderIntent, ...],
    open_states: pl.DataFrame,
    positions: PositionBook,
    cash: Decimal,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> BuyAllocation:
    """Allocate discrete buy quantities by exact Fraction breakpoints."""
    _validate_execution_inputs(
        intents=intents,
        side=OrderSide.BUY,
        open_states=open_states,
        positions=positions,
        cash=cash,
        cost_period=cost_period,
        price_tick=price_tick,
    )
    states = _state_map(open_states)
    positions_by_symbol = {item.symbol: item for item in positions}
    rejections: list[ExecutionRejection] = []
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]] = []
    for intent in sorted(intents, key=lambda item: item.symbol):
        state = states[intent.symbol]
        blocked = _blocked_reason(state=state, side=OrderSide.BUY)
        if blocked is not None:
            rejections.append(_whole_rejection(intent, state, blocked))
            continue
        if intent.requested_quantity is None:
            raise ValueError("buy requested quantity unknown with trusted open")
        desired = largest_valid_buy_quantity(
            requested_quantity=intent.requested_quantity,
            rule=intent.quantity_rule,
        )
        raw_gap_base = max(
            intent.requested_quantity,
            0 if intent.raw_target_quantity is None else intent.raw_target_quantity,
        )
        lot_residual = raw_gap_base - desired
        if lot_residual:
            rejections.append(_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.LOT_CONSTRAINT,
                quantity=lot_residual,
                open_price=Decimal(str(state["open"])),
            ))
        if desired:
            executable.append((intent, state, desired))
    if not executable:
        return BuyAllocation(
            lambda_fraction=None,
            batch=ExecutionBatch(
                cash=cash,
                positions=tuple(sorted(positions, key=lambda item: item.symbol)),
                fills=(),
                rejections=tuple(rejections),
            ),
        )
    breakpoints = {Fraction(0), Fraction(1)}
    for intent, _, desired in executable:
        breakpoints.update(
            Fraction(quantity, desired)
            for quantity in _valid_buy_quantities(desired, intent.quantity_rule)
        )
    chosen = Fraction(0)
    quantities: dict[str, int] = {}
    for candidate in sorted(breakpoints):
        candidate_quantities = {
            intent.symbol: _quantity_at_fraction(
                desired=desired,
                rule=intent.quantity_rule,
                fraction=candidate,
            )
            for intent, _, desired in executable
        }
        if _buy_total_cost(executable, candidate_quantities, cost_period, price_tick) <= cash:
            chosen = candidate
            quantities = candidate_quantities
        else:
            break
    remaining = cash - _buy_total_cost(executable, quantities, cost_period, price_tick)
    while True:
        candidates: list[tuple[Fraction, str, int, Decimal]] = []
        for intent, state, desired in executable:
            current = quantities.get(intent.symbol, 0)
            next_quantity = _next_valid_buy_quantity(
                current=current, desired=desired, rule=intent.quantity_rule
            )
            if next_quantity is None:
                continue
            incremental = _buy_cost(
                intent=intent,
                state=state,
                quantity=next_quantity,
                cost_period=cost_period,
                price_tick=price_tick,
            ) - _buy_cost(
                intent=intent,
                state=state,
                quantity=current,
                cost_period=cost_period,
                price_tick=price_tick,
            )
            candidates.append(
                (Fraction(desired - current, desired), intent.symbol, next_quantity, incremental)
            )
        affordable = [item for item in candidates if item[3] <= remaining]
        if not affordable:
            break
        _, symbol, next_quantity, incremental = sorted(
            affordable, key=lambda item: (-item[0], item[1])
        )[0]
        quantities[symbol] = next_quantity
        remaining -= incremental
    fills: list[ExecutionFill] = []
    for intent, state, desired in executable:
        quantity = quantities.get(intent.symbol, 0)
        if quantity:
            fill = _buy_fill(
                intent=intent,
                state=state,
                quantity=quantity,
                cost_period=cost_period,
                price_tick=price_tick,
            )
            fills.append(fill)
            current_position = positions_by_symbol.get(intent.symbol)
            positions_by_symbol[intent.symbol] = AccountPosition(
                symbol=intent.symbol,
                quantity=quantity
                + (0 if current_position is None else current_position.quantity),
                sellable_quantity=(
                    0
                    if current_position is None
                    else current_position.sellable_quantity
                ),
                unsettled_quantity=quantity
                + (
                    0
                    if current_position is None
                    else current_position.unsettled_quantity
                ),
                mark_price=(
                    fill.execution_price
                    if current_position is None
                    else current_position.mark_price
                ),
            )
        cash_residual = desired - quantity
        if cash_residual:
            rejections.append(_quantity_rejection(
                intent=intent,
                reason=ExecutionRejectReason.CASH_CONSTRAINT,
                quantity=cash_residual,
                open_price=Decimal(str(state["open"])),
            ))
    spent = sum((fill.notional + _fee_total(fill.fees) for fill in fills), Decimal(0))
    return BuyAllocation(
        lambda_fraction=chosen,
        batch=ExecutionBatch(
            cash=cash - spent,
            positions=tuple(
                sorted(positions_by_symbol.values(), key=lambda item: item.symbol)
            ),
            fills=tuple(fills),
            rejections=tuple(rejections),
        ),
    )


def _validate_execution_inputs(
    *,
    intents: tuple[TargetOrderIntent, ...],
    side: OrderSide,
    open_states: pl.DataFrame,
    positions: PositionBook,
    cash: Decimal,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> None:
    if (
        type(intents) is not tuple
        or any(type(intent) is not TargetOrderIntent or intent.side is not side for intent in intents)
        or len({intent.symbol for intent in intents}) != len(intents)
        or any(type(position) is not AccountPosition for position in positions)
        or len({position.symbol for position in positions}) != len(positions)
        or type(cash) is not Decimal
        or not cash.is_finite()
        or cash < 0
        or type(cost_period) is not AShareCostPeriod
        or type(price_tick) is not Decimal
        or not price_tick.is_finite()
        or price_tick <= 0
    ):
        raise ValueError("execution inputs invalid")
    if not intents:
        return
    dates = open_states.get_column("date").unique()
    if len(dates) != 1:
        raise ValueError("execution open-state date invalid")
    _validate_open_states(open_states, dates.item())
    if {intent.symbol for intent in intents} - set(open_states.get_column("symbol")):
        raise ValueError("execution open state missing")


def _state_map(frame: pl.DataFrame) -> dict[str, dict[str, object]]:
    return {
        cast(str, row["symbol"]): row for row in frame.iter_rows(named=True)
    }


def _blocked_reason(
    *, state: dict[str, object], side: OrderSide
) -> ExecutionRejectReason | None:
    reason = state["reason"]
    if reason in {"MISSING_OPEN", "OPEN_UNKNOWN", "SUSPENDED"}:
        return ExecutionRejectReason(cast(str, reason))
    allowed_field = "buy_allowed" if side is OrderSide.BUY else "sell_allowed"
    if not cast(bool, state[allowed_field]):
        return (
            ExecutionRejectReason.BUY_AT_UPPER_LIMIT
            if side is OrderSide.BUY
            else ExecutionRejectReason.SELL_AT_LOWER_LIMIT
        )
    return None


def _whole_rejection(
    intent: TargetOrderIntent,
    state: dict[str, object],
    reason: ExecutionRejectReason,
) -> ExecutionRejection:
    requested = intent.requested_quantity
    open_value = state["open"]
    rejected_notional = (
        intent.target_notional
        if requested is None or open_value is None
        else Decimal(requested) * Decimal(str(open_value))
    )
    return ExecutionRejection(
        symbol=intent.symbol,
        side=intent.side,
        reason=reason,
        requested_quantity=requested,
        filled_quantity=0,
        rejected_quantity=requested,
        rejected_notional=rejected_notional,
    )


def _quantity_rejection(
    *,
    intent: TargetOrderIntent,
    reason: ExecutionRejectReason,
    quantity: int,
    open_price: Decimal,
) -> ExecutionRejection:
    return ExecutionRejection(
        symbol=intent.symbol,
        side=intent.side,
        reason=reason,
        requested_quantity=quantity,
        filled_quantity=0,
        rejected_quantity=quantity,
        rejected_notional=open_price * quantity,
    )


def _execution_price(
    *,
    open_price: Decimal,
    side: OrderSide,
    slippage: Decimal,
    price_tick: Decimal,
    lower: Decimal,
    upper: Decimal,
) -> Decimal:
    raw = open_price * (
        Decimal(1) + slippage if side is OrderSide.BUY else Decimal(1) - slippage
    )
    rounding = ROUND_CEILING if side is OrderSide.BUY else ROUND_FLOOR
    ticked = (raw / price_tick).to_integral_value(rounding=rounding) * price_tick
    return min(max(ticked, lower), upper)


def _fee_total(fees: AShareFeeComponents) -> Decimal:
    return fees.commission + fees.stamp_tax + fees.transfer_fee


def _valid_buy_quantities(
    desired: int, rule: AShareOrderQuantityRule
) -> tuple[int, ...]:
    if rule.board is AShareBoard.SSE_STAR:
        return tuple(range(rule.buy_min_quantity, desired + 1))
    return tuple(range(rule.buy_min_quantity, desired + 1, rule.buy_increment))


def _quantity_at_fraction(
    *, desired: int, rule: AShareOrderQuantityRule, fraction: Fraction
) -> int:
    cap = (desired * fraction.numerator) // fraction.denominator
    return largest_valid_buy_quantity(requested_quantity=cap, rule=rule)


def _next_valid_buy_quantity(
    *, current: int, desired: int, rule: AShareOrderQuantityRule
) -> int | None:
    if current >= desired:
        return None
    if current == 0:
        candidate = rule.buy_min_quantity
    else:
        candidate = current + rule.buy_increment
    return candidate if candidate <= desired else None


def _buy_fill(
    *,
    intent: TargetOrderIntent,
    state: dict[str, object],
    quantity: int,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> ExecutionFill:
    open_price = Decimal(str(state["open"]))
    execution_price = _execution_price(
        open_price=open_price,
        side=OrderSide.BUY,
        slippage=cost_period.slippage,
        price_tick=price_tick,
        lower=Decimal(str(state["down_limit"])),
        upper=Decimal(str(state["up_limit"])),
    )
    notional = execution_price * quantity
    fees = compute_a_share_fee_components(
        notional=notional, side=OrderSide.BUY, cost_period=cost_period
    )
    return ExecutionFill(
        symbol=intent.symbol,
        side=OrderSide.BUY,
        quantity=quantity,
        reference_open=open_price,
        execution_price=execution_price,
        notional=notional,
        fees=fees,
        slippage_cost=(execution_price - open_price) * quantity,
    )


def _buy_cost(
    *,
    intent: TargetOrderIntent,
    state: dict[str, object],
    quantity: int,
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> Decimal:
    if quantity == 0:
        return Decimal(0)
    fill = _buy_fill(
        intent=intent,
        state=state,
        quantity=quantity,
        cost_period=cost_period,
        price_tick=price_tick,
    )
    return fill.notional + _fee_total(fill.fees)


def _buy_total_cost(
    executable: list[tuple[TargetOrderIntent, dict[str, object], int]],
    quantities: dict[str, int],
    cost_period: AShareCostPeriod,
    price_tick: Decimal,
) -> Decimal:
    return sum(
        (
            _buy_cost(
                intent=intent,
                state=state,
                quantity=quantities.get(intent.symbol, 0),
                cost_period=cost_period,
                price_tick=price_tick,
            )
            for intent, state, _ in executable
        ),
        Decimal(0),
    )


def _validate_quantity(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("quantity invalid")


def _validate_open_states(frame: pl.DataFrame, date: dt.date) -> None:
    required = [
        "date", "symbol", "open", "has_open", "full_day_suspended",
        "partial_open_status", "has_price_limit", "up_limit", "down_limit",
        "buy_allowed", "sell_allowed", "reason",
    ]
    if (
        set(frame.columns) != set(required)
        or frame["symbol"].n_unique() != frame.height
        or any(day != date for day in frame["date"])
    ):
        raise ValueError("open execution states invalid")


__all__ = [
    "AShareBoard", "AShareFeeComponents", "AShareMarketFactsIdentityV1",
    "AShareOrderQuantityRule",
    "AccountPosition", "BuyAllocation", "ExecutionBatch", "ExecutionFill",
    "ExecutionRejectReason", "ExecutionRejection", "PositionBook",
    "TargetOrderIntent", "allocate_buy_lots", "build_a_share_market_facts",
    "build_open_execution_states", "build_target_order_intents",
    "compute_a_share_fee_components", "largest_valid_buy_quantity",
    "execute_sell_intents", "largest_valid_sell_quantity",
    "resolve_a_share_order_quantity_rule",
]
