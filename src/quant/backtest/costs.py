"""版本化研究成本模型；数值由 configs/ 提供。"""

import datetime as dt
import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from quant.backtest.fx import (
    FxSnapshot,
    convert_money,
    require_fx_snapshot_current,
)
from quant.domain.enums import Currency, Market, OrderSide
from quant.execution.contracts import (
    FeeComponent,
    OrderIntent,
    build_fee_component,
    build_money_amount,
    build_order_intent,
)

_COST_INPUT_INVALID = "EXECUTION_COST_INPUT_INVALID"
_COST_PERIOD_MISSING = "EXECUTION_COST_PERIOD_MISSING"
_CENT = Decimal("0.01")


class ExecutionCostError(ValueError):
    """Stable M4 cost schedule or calculation failure."""


@dataclass(frozen=True, slots=True)
class ExecutionCostPeriod:
    market: Market
    effective_from: dt.date
    effective_to: dt.date | None
    commission_rate: Decimal
    commission_min: Decimal
    stamp_tax_sell: Decimal
    transfer_fee: Decimal
    settlement_currency: Currency

    def __post_init__(self) -> None:
        rates = (
            self.commission_rate,
            self.commission_min,
            self.stamp_tax_sell,
            self.transfer_fee,
        )
        quote = Currency.HKD if self.market is Market.HK else Currency.CNY
        if (
            type(self.market) is not Market
            or type(self.effective_from) is not dt.date
            or self.effective_to is not None
            and type(self.effective_to) is not dt.date
            or self.effective_to is not None
            and self.effective_to < self.effective_from
            or any(
                type(value) is not Decimal or not value.is_finite() or value < 0
                for value in rates
            )
            or type(self.settlement_currency) is not Currency
            or self.market in {Market.SH, Market.SZ}
            and self.settlement_currency is not quote
        ):
            raise ExecutionCostError(_COST_INPUT_INVALID)


@dataclass(frozen=True, slots=True)
class ExecutionCostSchedule:
    selector: str
    periods: tuple[ExecutionCostPeriod, ...]

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(
                self.periods,
                key=lambda item: (item.market.value, item.effective_from),
            )
        )
        if (
            type(self.selector) is not str
            or not self.selector
            or any(char in "/\\:%" for char in self.selector)
            or any(ord(char) < 32 or ord(char) == 127 for char in self.selector)
            or type(self.periods) is not tuple
            or not self.periods
            or any(type(item) is not ExecutionCostPeriod for item in self.periods)
            or ordered != self.periods
        ):
            raise ExecutionCostError(_COST_INPUT_INVALID)
        previous: dict[Market, ExecutionCostPeriod] = {}
        for period in self.periods:
            prior = previous.get(period.market)
            if prior is not None and (
                prior.effective_to is None
                or period.effective_from <= prior.effective_to
            ):
                raise ExecutionCostError(_COST_INPUT_INVALID)
            previous[period.market] = period


def build_execution_cost_schedule(
    *, selector: str, periods: tuple[ExecutionCostPeriod, ...]
) -> ExecutionCostSchedule:
    """Sort and validate a multi-market, versioned fee schedule."""
    try:
        ordered = tuple(
            sorted(periods, key=lambda item: (item.market.value, item.effective_from))
        )
        return ExecutionCostSchedule(selector=selector, periods=ordered)
    except Exception:
        raise ExecutionCostError(_COST_INPUT_INVALID) from None


def _prove_cost_intent(intent: OrderIntent) -> OrderIntent:
    try:
        proven = build_order_intent(
            plan_id=intent.plan_id,
            symbol=intent.symbol,
            market=intent.market,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            quote_currency=intent.quote_currency,
            session_date=intent.session_date,
            generated_at=intent.generated_at,
            target_identity=intent.target_identity,
            market_snapshot_id=intent.market_snapshot_id,
            account_snapshot_id=intent.account_snapshot_id,
            config_identity=intent.config_identity,
            connect_route=intent.connect_route,
        )
        if type(intent) is not OrderIntent or proven != intent:
            raise ValueError
        return proven
    except Exception:
        raise ExecutionCostError(_COST_INPUT_INVALID) from None


def calculate_execution_cost(
    intent: OrderIntent,
    fill_price: Decimal,
    fill_quantity: int,
    schedule: ExecutionCostSchedule,
    fx_snapshot: FxSnapshot | None,
) -> tuple[FeeComponent, ...]:
    """Calculate commission and statutory fees from the actual fill notional."""
    intent = _prove_cost_intent(intent)
    if (
        type(fill_price) is not Decimal
        or not fill_price.is_finite()
        or fill_price <= 0
        or type(fill_quantity) is not int
        or not 0 < fill_quantity <= intent.quantity
        or type(schedule) is not ExecutionCostSchedule
    ):
        raise ExecutionCostError(_COST_INPUT_INVALID)
    schedule = build_execution_cost_schedule(
        selector=schedule.selector, periods=schedule.periods
    )
    matches = tuple(
        period
        for period in schedule.periods
        if period.market is intent.market
        and period.effective_from <= intent.session_date
        and (period.effective_to is None or intent.session_date <= period.effective_to)
    )
    if len(matches) != 1:
        raise ExecutionCostError(_COST_PERIOD_MISSING)
    period = matches[0]
    notional = fill_price * fill_quantity
    source_amounts = (
        (
            "COMMISSION",
            max(notional * period.commission_rate, period.commission_min),
            False,
        ),
        (
            "STAMP_TAX",
            notional * period.stamp_tax_sell
            if intent.side is OrderSide.SELL
            else Decimal(0),
            True,
        ),
        ("TRANSFER_FEE", notional * period.transfer_fee, True),
    )
    if period.settlement_currency is not intent.quote_currency:
        if fx_snapshot is None:
            raise ExecutionCostError(_COST_INPUT_INVALID)
        try:
            fx_snapshot = require_fx_snapshot_current(
                fx_snapshot,
                session_date=intent.session_date,
                at=intent.generated_at,
            )
        except Exception as error:
            raise ExecutionCostError(str(error)) from None
    components: list[FeeComponent] = []
    for code, raw_amount, statutory in source_amounts:
        source = build_money_amount(
            intent.quote_currency,
            raw_amount.quantize(_CENT, rounding=ROUND_HALF_UP),
        )
        amount = (
            source
            if source.currency is period.settlement_currency
            else convert_money(source, fx_snapshot, period.settlement_currency)  # type: ignore[arg-type]
        )
        components.append(
            build_fee_component(
                code=code,
                amount=amount,
                statutory=statutory,
                rule_version=schedule.selector,
            )
        )
    return tuple(components)


def _require_finite_nonnegative(name: str, value: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} 必须是非负有限数")


@dataclass(frozen=True)
class EtfCostModel:
    commission_rate: float
    commission_min: float
    slippage: float
    effective_from: dt.date
    slippage_per_share: float = 0.0

    def __post_init__(self) -> None:
        _require_finite_nonnegative("commission_rate", self.commission_rate)
        _require_finite_nonnegative("commission_min", self.commission_min)
        _require_finite_nonnegative("slippage", self.slippage)
        _require_finite_nonnegative("slippage_per_share", self.slippage_per_share)
        if self.slippage and self.slippage_per_share:
            raise ValueError("Choose either fractional or per-share ETF slippage")
        if self.slippage >= 1:
            raise ValueError("滑点必须小于 1")

    def execution_price(self, open_price: float, side: str) -> float:
        if open_price <= self.slippage_per_share:
            raise ValueError("ETF price must exceed per-share slippage")
        if side == "BUY":
            return open_price * (1 + self.slippage) + self.slippage_per_share
        if side == "SELL":
            return open_price * (1 - self.slippage) - self.slippage_per_share
        raise ValueError(f"未知方向: {side}")

    def fee(self, notional: float, date: dt.date) -> float:
        if date < self.effective_from:
            raise ValueError("交易日期早于成本配置有效期")
        return max(notional * self.commission_rate, self.commission_min)

    def with_execution_cost_multiplier(
        self, multiplier: float
    ) -> "EtfCostModel":
        """返回只缩放执行摩擦的新成本模型。"""
        if (
            isinstance(multiplier, bool)
            or not isinstance(multiplier, (int, float))
            or not math.isfinite(multiplier)
            or multiplier <= 0
        ):
            raise ValueError("成本压力倍数必须是正有限数")
        return EtfCostModel(
            commission_rate=self.commission_rate * multiplier,
            commission_min=self.commission_min * multiplier,
            slippage=self.slippage * multiplier,
            effective_from=self.effective_from,
            slippage_per_share=self.slippage_per_share * multiplier,
        )


@dataclass(frozen=True)
class AShareCostModel:
    """A 股股票双边佣金/过户费与卖出印花税模型。"""

    commission_rate: float
    commission_min: float
    stamp_tax_sell: float
    transfer_fee: float
    slippage: float
    effective_from: dt.date
    historical_statutory_fees: bool = False
    pre_2015_sh_transfer_multiplier: float = 2.0
    pre_2015_sh_transfer_min: float = 1.0
    pre_2015_sh_par_value: float = 1.0

    def __post_init__(self) -> None:
        _require_finite_nonnegative("commission_rate", self.commission_rate)
        _require_finite_nonnegative("commission_min", self.commission_min)
        _require_finite_nonnegative("stamp_tax_sell", self.stamp_tax_sell)
        _require_finite_nonnegative("transfer_fee", self.transfer_fee)
        _require_finite_nonnegative("slippage", self.slippage)
        if self.slippage >= 1:
            raise ValueError("滑点必须小于 1")
        if type(self.historical_statutory_fees) is not bool:
            raise ValueError("Historical statutory fee switch must be boolean")
        for name in ("pre_2015_sh_transfer_multiplier", "pre_2015_sh_transfer_min", "pre_2015_sh_par_value"):
            _require_finite_nonnegative(name, getattr(self, name))

    def execution_price(self, open_price: float, side: str) -> float:
        if side == "BUY":
            return open_price * (1 + self.slippage)
        if side == "SELL":
            return open_price * (1 - self.slippage)
        raise ValueError(f"未知方向: {side}")

    def fee(self, notional: float, date: dt.date, side: str, *,
            market: str | None = None, quantity: int | None = None) -> float:
        if date < self.effective_from:
            raise ValueError("交易日期早于成本配置有效期")
        if side not in {"BUY", "SELL"}:
            raise ValueError(f"未知方向: {side}")
        commission = max(notional * self.commission_rate, self.commission_min)
        transfer_rate, stamp_rate = self.transfer_fee, self.stamp_tax_sell
        if self.historical_statutory_fees:
            if date < dt.date(2015, 8, 1):
                if date < dt.date(2010, 1, 1) or market not in {"SH", "SZ"} or type(quantity) is not int or quantity <= 0:
                    raise ValueError("Before 2015-08-01, historical fees require SH/SZ market and quantity from 2010")
                # Shanghai charged face value; Shenzhen's transfer fee was
                # included in gross commission. Retail retention/minimum are
                # explicit research assumptions, documented with the config.
                rate = (.0005 if date < dt.date(2012, 6, 1) else
                        .000375 if date < dt.date(2012, 9, 1) else .0003)
                transfer = (max(self.pre_2015_sh_transfer_min,
                    quantity*self.pre_2015_sh_par_value*rate*self.pre_2015_sh_transfer_multiplier)
                    if market == "SH" else 0.)
                return commission + transfer + (notional*.001 if side == "SELL" else 0.)
            transfer_rate = 0.00002 if date < dt.date(2022, 4, 29) else 0.00001
            stamp_rate = 0.001 if date < dt.date(2023, 8, 28) else 0.0005
        transfer = notional * transfer_rate
        stamp = notional * stamp_rate if side == "SELL" else 0.0
        return commission + transfer + stamp

    def with_execution_cost_multiplier(
        self, multiplier: float
    ) -> "AShareCostModel":
        """返回只缩放佣金和滑点、不缩放法定税费的新模型。"""
        if (
            isinstance(multiplier, bool)
            or not isinstance(multiplier, (int, float))
            or not math.isfinite(multiplier)
            or multiplier <= 0
        ):
            raise ValueError("成本压力倍数必须是正有限数")
        return AShareCostModel(
            commission_rate=self.commission_rate * multiplier,
            commission_min=self.commission_min * multiplier,
            stamp_tax_sell=self.stamp_tax_sell,
            transfer_fee=self.transfer_fee,
            slippage=self.slippage * multiplier,
            effective_from=self.effective_from,
            historical_statutory_fees=self.historical_statutory_fees,
            pre_2015_sh_transfer_multiplier=self.pre_2015_sh_transfer_multiplier,
            pre_2015_sh_transfer_min=self.pre_2015_sh_transfer_min,
            pre_2015_sh_par_value=self.pre_2015_sh_par_value,
        )
