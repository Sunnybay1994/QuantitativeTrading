"""数据契约最小单测:合法数据通过,非法数据被拒绝。"""

import datetime as dt

import pandera.errors
import polars as pl
import pytest

from quant.domain import (
    AdjustmentFactorSchema,
    Bar1dSchema,
    CashSchema,
    BacktestPositionSchema,
    BacktestRejectionSchema,
    BacktestNavSchema,
    CorporateActionLedgerSchema,
    CorporateActionReconciliationSchema,
    CorporateActionSchema,
    CorporateActionSelectionEvidenceSchema,
    DailyBasic1dSchema,
    FactorValueSchema,
    HkCorporateActionImplementationEvidenceSchema,
    HkBarAvailabilityEvidenceSchema,
    InstrumentSchema,
    HkCorporateActionRevisionEvidenceSchema,
    OrderSchema,
    PositionSchema,
    PriceLimit1dSchema,
    ResearchPrice1dSchema,
    SnapshotSessionCalendarSchema,
    TargetWeightSchema,
    TradeCalendarSchema,
    UniverseMembershipSchema,
)
from quant.domain.schemas import HKNoTradeEvidenceSchema


def test_research_price_schema_accepts_hk_gross_total_return_method() -> None:
    ResearchPrice1dSchema.validate(
        pl.DataFrame(
            [
                {
                    "symbol": "00700.HK",
                    "trade_date": dt.date(2026, 5, 8),
                    "adjusted_close": 194.0,
                    "adjustment_method": "HK_GROSS_TOTAL_RETURN_V1",
                    "source": "derived_hk_bar_and_ca_v1",
                }
            ]
        )
    )


def test_hk_bar_availability_schema_enforces_exact_key_and_kind_nullability() -> None:
    base = {
        "symbol": "00700.HK",
        "trade_date": dt.date(2026, 7, 10),
        "source": "tushare",
        "availability_source_kind": "REQUEST_RAW",
        "bar_available_at": dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc),
        "source_record_id": "a" * 64,
        "request_id": "a" * 64,
        "raw_file_sha256": "b" * 64,
        "raw_metadata_sha256": "c" * 64,
        "request_receipt_sha256": "d" * 64,
        "plan_sha256": "e" * 64,
        "availability_evidence_sha256": "f" * 64,
    }
    HkBarAvailabilityEvidenceSchema.validate(pl.DataFrame([base]))
    for changed in (
        {**base, "request_id": None},
        {
            **base,
            "availability_source_kind": "SEED_RAW",
            "request_receipt_sha256": None,
        },
    ):
        with pytest.raises(pandera.errors.SchemaError):
            HkBarAvailabilityEvidenceSchema.validate(pl.DataFrame([changed]))
    with pytest.raises(pandera.errors.SchemaError):
        HkBarAvailabilityEvidenceSchema.validate(pl.DataFrame([base, base]))


def _hk_corporate_action_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "event_id": "a" * 64,
        "symbol": "00700.HK",
        "action_type": "DIVIDEND",
        "record_date": dt.date(2026, 5, 8),
        "ex_date": dt.date(2026, 5, 11),
        "pay_date": dt.date(2026, 5, 20),
        "stock_list_date": None,
        "declared_currency": "HKD",
        "cash_per_share_gross": 0.5,
        "stock_ratio": None,
        "share_multiplier": None,
        "rights_ratio": None,
        "rights_subscription_price": None,
        "rights_subscription_start": None,
        "rights_subscription_end": None,
        "announce_time": dt.datetime(2026, 5, 4, 9, tzinfo=dt.UTC),
        "source": "FIXTURE",
        "source_event_id": "event-1",
        "source_revision_id": "revision-1",
        "source_snapshot_sha256": "b" * 64,
    }
    row.update(overrides)
    return row


def test_hk_corporate_action_schema_enforces_action_units() -> None:
    CorporateActionSchema.validate(pl.DataFrame([_hk_corporate_action_row()]))
    split = _hk_corporate_action_row(
        event_id="c" * 64,
        action_type="SPLIT",
        pay_date=None,
        stock_list_date=dt.date(2026, 5, 12),
        declared_currency=None,
        cash_per_share_gross=None,
        share_multiplier=0.5,
    )
    CorporateActionSchema.validate(pl.DataFrame([split]))
    with pytest.raises(pandera.errors.SchemaError):
        CorporateActionSchema.validate(pl.DataFrame([{**split, "share_multiplier": 1.0}]))
    with pytest.raises(pandera.errors.SchemaError):
        CorporateActionSchema.validate(pl.DataFrame([{**split, "stock_ratio": 0.5}]))


def test_hk_revision_evidence_schema_rejects_invalid_selected_reason() -> None:
    action = _hk_corporate_action_row()
    row = {
        "economic_event_key_sha256": "d" * 64,
        "candidate_id": "e" * 64,
        **{key: action[key] for key in (
            "symbol", "action_type", "source", "source_event_id", "source_revision_id",
            "record_date", "ex_date", "pay_date", "stock_list_date", "declared_currency",
            "cash_per_share_gross", "stock_ratio", "share_multiplier", "rights_ratio",
            "rights_subscription_price", "rights_subscription_start", "rights_subscription_end",
        )},
        "revision_sequence": 1,
        "predecessor_candidate_id": None,
        "revision_status": "ACTIVE",
        "published_at": action["announce_time"],
        "source_observed_at": dt.datetime(2026, 8, 1, tzinfo=dt.UTC),
        "raw_bundle_sha256": "f" * 64,
        "raw_file_sha256": "1" * 64,
        "raw_metadata_sha256": "2" * 64,
        "raw_selector": "row/1",
        "selected": True,
        "selection_reason": "SELECTED_AS_OF",
        "query_as_of": dt.datetime(2026, 5, 5, tzinfo=dt.UTC),
    }
    HkCorporateActionRevisionEvidenceSchema.validate(pl.DataFrame([row]))
    with pytest.raises(pandera.errors.SchemaError):
        HkCorporateActionRevisionEvidenceSchema.validate(
            pl.DataFrame([{**row, "selection_reason": "FUTURE_AS_OF"}])
        )
    with pytest.raises(pandera.errors.SchemaError):
        HkCorporateActionRevisionEvidenceSchema.validate(
            pl.DataFrame([{**row, "stock_ratio": 0.1}])
        )


def test_hk_implementation_evidence_schema_is_strict_and_implemented_only() -> None:
    row = {
        "event_id": "a" * 64,
        "symbol": "00700.HK",
        "action_type": "DIVIDEND",
        "source": "FIXTURE",
        "source_event_id": "event-1",
        "source_revision_id": "revision-1",
        "implementation_status": "IMPLEMENTED",
        "implementation_effective_date": dt.date(2026, 5, 8),
        "implementation_confirmed_at": dt.datetime(2026, 5, 9, tzinfo=dt.UTC),
        "source_observed_at": dt.datetime(2026, 5, 10, tzinfo=dt.UTC),
        "source_record_id": "record-1",
        "raw_selector": "records/0",
        "raw_file_sha256": "b" * 64,
        "raw_metadata_sha256": "c" * 64,
        "raw_bundle_sha256": "d" * 64,
        "p0_actions_content_sha256": "e" * 64,
        "p0_evidence_content_sha256": "f" * 64,
        "p0_query_sha256": "1" * 64,
        "implementation_evidence_sha256": "2" * 64,
    }
    HkCorporateActionImplementationEvidenceSchema.validate(pl.DataFrame([row]))
    with pytest.raises(pandera.errors.SchemaError):
        HkCorporateActionImplementationEvidenceSchema.validate(
            pl.DataFrame([{**row, "implementation_status": "PENDING"}])
        )
    with pytest.raises(pandera.errors.SchemaError):
        HkCorporateActionImplementationEvidenceSchema.validate(
            pl.DataFrame(
                [
                    {
                        **row,
                        "source_observed_at": dt.datetime(
                            2026, 5, 8, tzinfo=dt.UTC
                        ),
                    }
                ]
            )
        )


def test_hk_no_trade_evidence_schema_rejects_duplicate_key() -> None:
    row = {
        "schema_version": "hk-no-trade-evidence-v1",
        "evidence_sha256": "a" * 64,
        "symbol": "01065.HK",
        "trade_date": dt.date(2026, 5, 5),
        "market": "HK",
        "reason": "NO_DAILY_TRADING_V1",
        "source": "HKEX_DAILY_QUOTATIONS",
        "source_record_id": "synthetic-fixture",
        "source_as_of": dt.datetime(2026, 7, 31),
        "raw_selector": "hkex/d260505e.html",
        "raw_file_sha256": "b" * 64,
        "raw_metadata_sha256": "c" * 64,
    }
    HKNoTradeEvidenceSchema.validate(pl.DataFrame([row]))
    HKNoTradeEvidenceSchema.validate(
        pl.DataFrame(
            [
                {
                    **row,
                    "symbol": "01065.HK",
                    "trade_date": dt.date(2026, 5, 5),
                    "source": "USER_APPROVED_MULTI_SOURCE_CONSENSUS",
                    "source_record_id": "UA-M1-001",
                    "raw_selector": (
                        "user-approved-consensus/"
                        "ua-m1-001-01065-2026-05-05.record"
                    ),
                }
            ]
        )
    )
    with pytest.raises(pandera.errors.SchemaError):
        HKNoTradeEvidenceSchema.validate(
            pl.DataFrame(
                [
                    {
                        **row,
                        "symbol": "01066.HK",
                        "source": "USER_APPROVED_MULTI_SOURCE_CONSENSUS",
                        "source_record_id": "UA-M1-001",
                        "raw_selector": (
                            "user-approved-consensus/"
                            "ua-m1-001-01065-2026-05-05.record"
                        ),
                    }
                ]
            )
        )
    duplicate = dict(row)
    duplicate["evidence_sha256"] = "d" * 64
    with pytest.raises(pandera.errors.SchemaError):
        HKNoTradeEvidenceSchema.validate(pl.DataFrame([row, duplicate]))


def test_hk_no_trade_evidence_schema_accepts_exact_ua_m1_005_and_rejects_drift() -> None:
    def user_approved_row(
        *,
        symbol: str,
        trade_date: dt.date,
        source_record_id: str,
        raw_selector: str,
        evidence_sha256: str = "a" * 64,
    ) -> dict[str, object]:
        return {
            "schema_version": "hk-no-trade-evidence-v1",
            "evidence_sha256": evidence_sha256,
            "symbol": symbol,
            "trade_date": trade_date,
            "market": "HK",
            "reason": "NO_DAILY_TRADING_V1",
            "source": "USER_APPROVED_MULTI_SOURCE_CONSENSUS",
            "source_record_id": source_record_id,
            "source_as_of": dt.datetime(2026, 8, 15),
            "raw_selector": raw_selector,
            "raw_file_sha256": "b" * 64,
            "raw_metadata_sha256": "c" * 64,
        }

    ua_m1_001 = user_approved_row(
        symbol="01065.HK",
        trade_date=dt.date(2026, 5, 5),
        source_record_id="UA-M1-001",
        raw_selector="user-approved-consensus/ua-m1-001-01065-2026-05-05.record",
    )
    ua_m1_004 = user_approved_row(
        symbol="02402.HK",
        trade_date=dt.date(2026, 4, 14),
        source_record_id="UA-M1-004",
        raw_selector=(
            "user-approved-consensus/"
            "ua-m1-004-02402-2026-04-01-to-2026-05-04.record"
        ),
        evidence_sha256="d" * 64,
    )
    ua_m1_005 = user_approved_row(
        symbol="06110.HK",
        trade_date=dt.date(2026, 6, 25),
        source_record_id="UA-M1-005",
        raw_selector="user-approved-consensus/ua-m1-005-06110-2026-06-25.record",
        evidence_sha256="e" * 64,
    )
    HKNoTradeEvidenceSchema.validate(pl.DataFrame([ua_m1_001]))
    HKNoTradeEvidenceSchema.validate(pl.DataFrame([ua_m1_004]))
    HKNoTradeEvidenceSchema.validate(pl.DataFrame([ua_m1_005]))
    HKNoTradeEvidenceSchema.validate(pl.DataFrame([ua_m1_001, ua_m1_004, ua_m1_005]))

    with pytest.raises(pandera.errors.SchemaError):
        HKNoTradeEvidenceSchema.validate(
            pl.DataFrame(
                [
                    {
                        **ua_m1_004,
                        "trade_date": dt.date(2026, 5, 4),
                    }
                ]
            )
        )
    for drifted in (
        {**ua_m1_005, "symbol": "06111.HK"},
        {**ua_m1_005, "trade_date": dt.date(2026, 6, 24)},
        {**ua_m1_005, "trade_date": dt.date(2026, 6, 26)},
        {**ua_m1_005, "source_record_id": "UA-M1-001"},
        {
            **ua_m1_005,
            "raw_selector": "user-approved-consensus/ua-m1-001-01065-2026-05-05.record",
        },
        {**ua_m1_005, "source": "HKEX_DAILY_QUOTATIONS"},
        {
            **ua_m1_005,
            "source": "HKEX_DAILY_QUOTATIONS",
            "raw_selector": "hkex/d260625e.html",
        },
        {
            **ua_m1_005,
            "source": "HKEX_DAILY_QUOTATIONS",
            "source_record_id": "synthetic-fixture",
        },
        {**ua_m1_001, "source": "HKEX_DAILY_QUOTATIONS"},
        {
            **ua_m1_001,
            "source": "HKEX_DAILY_QUOTATIONS",
            "raw_selector": "hkex/d260505e.html",
        },
        {
            **ua_m1_001,
            "source": "HKEX_DAILY_QUOTATIONS",
            "source_record_id": "synthetic-fixture",
        },
        {**ua_m1_001, "source": "TUSHARE_HK_DAILY"},
        {**ua_m1_004, "source": "HKEX_DAILY_QUOTATIONS"},
        {
            **ua_m1_004,
            "source": "HKEX_DAILY_QUOTATIONS",
            "raw_selector": "hkex/d260414e.html",
        },
        {
            **ua_m1_004,
            "source": "HKEX_DAILY_QUOTATIONS",
            "source_record_id": "synthetic-fixture",
        },
        {
            **ua_m1_001,
            "source": "HKEX_DAILY_QUOTATIONS",
            "source_record_id": "UA-M1-006",
            "raw_selector": "hkex/d260505e.html",
        },
        {
            **ua_m1_001,
            "source": "HKEX_DAILY_QUOTATIONS",
            "source_record_id": "synthetic-fixture",
            "raw_selector": "user-approved-consensus/ua-m1-006-unknown.record",
        },
    ):
        with pytest.raises(pandera.errors.SchemaError):
            HKNoTradeEvidenceSchema.validate(pl.DataFrame([drifted]))

    ordinary_hkex = {
        "schema_version": "hk-no-trade-evidence-v1",
        "evidence_sha256": "f" * 64,
        "symbol": "06110.HK",
        "trade_date": dt.date(2026, 6, 25),
        "market": "HK",
        "reason": "NO_DAILY_TRADING_V1",
        "source": "HKEX_DAILY_QUOTATIONS",
        "source_record_id": "synthetic-fixture",
        "source_as_of": dt.datetime(2026, 7, 31),
        "raw_selector": "hkex/d260625e.html",
        "raw_file_sha256": "b" * 64,
        "raw_metadata_sha256": "c" * 64,
    }
    HKNoTradeEvidenceSchema.validate(pl.DataFrame([ordinary_hkex]))
    HKNoTradeEvidenceSchema.validate(pl.DataFrame([ua_m1_001, ua_m1_004, ordinary_hkex]))


class TestSnapshotSessionCalendarSchema:
    def test_strictly_increasing_dates_pass(self) -> None:
        SnapshotSessionCalendarSchema.validate(pl.DataFrame({
            "date": [dt.date(2026, 1, 5), dt.date(2026, 1, 6)]
        }))

    @pytest.mark.parametrize(
        "dates",
        [
            [],
            [dt.date(2026, 1, 5), dt.date(2026, 1, 5)],
            [dt.date(2026, 1, 6), dt.date(2026, 1, 5)],
        ],
    )
    def test_empty_duplicate_or_unsorted_dates_fail(
        self, dates: list[dt.date],
    ) -> None:
        with pytest.raises(pandera.errors.SchemaError):
            SnapshotSessionCalendarSchema.validate(
                pl.DataFrame({"date": dates}, schema={"date": pl.Date})
            )


def make_bar(**overrides) -> pl.DataFrame:
    row = {
        "symbol": "000001.SZ",
        "trade_date": dt.date(2026, 7, 10),
        "open": 10.0,
        "high": 10.5,
        "low": 9.8,
        "close": 10.2,
        "volume": 1_000_000.0,
        "amount": 10_200_000.0,
        "adj_factor": 1.0,
        "source": "akshare",
    }
    row.update(overrides)
    return pl.DataFrame([row])


class TestBar1dSchema:
    def test_valid_bar_passes(self):
        Bar1dSchema.validate(make_bar())

    def test_hk_symbol_passes(self):
        Bar1dSchema.validate(make_bar(symbol="00700.HK"))

    def test_bad_symbol_rejected(self):
        with pytest.raises(pandera.errors.SchemaError):
            Bar1dSchema.validate(make_bar(symbol="SZ000001"))

    def test_invalid_ohlc_rejected(self):
        # high < low:非法 K 线
        with pytest.raises(pandera.errors.SchemaError):
            Bar1dSchema.validate(make_bar(high=9.0, low=9.8))

    def test_close_above_high_rejected(self):
        with pytest.raises(pandera.errors.SchemaError):
            Bar1dSchema.validate(make_bar(close=11.0, high=10.5))

    def test_negative_volume_rejected(self):
        with pytest.raises(pandera.errors.SchemaError):
            Bar1dSchema.validate(make_bar(volume=-100.0))

    def test_zero_price_rejected(self):
        with pytest.raises(pandera.errors.SchemaError):
            Bar1dSchema.validate(make_bar(open=0.0))

    def test_duplicate_source_bar_rejected(self):
        with pytest.raises(pandera.errors.SchemaError):
            Bar1dSchema.validate(pl.concat([make_bar(), make_bar()]))

    def test_same_symbol_date_from_different_sources_passes(self):
        Bar1dSchema.validate(
            pl.concat([make_bar(), make_bar().with_columns(pl.lit("check").alias("source"))])
        )


def make_daily_basic(**overrides: object) -> pl.DataFrame:
    row: dict[str, object] = {
        "symbol": "000001.SZ",
        "trade_date": dt.date(2026, 7, 10),
        "close": 10.2,
        "turnover_rate": 1.2,
        "turnover_rate_free": 2.1,
        "volume_ratio": None,
        "pe": -12.0,
        "pe_ttm": -10.0,
        "pb": 1.1,
        "ps": 2.0,
        "ps_ttm": 1.9,
        "dividend_yield": None,
        "dividend_yield_ttm": 1.5,
        "total_shares": 10_000_000.0,
        "float_shares": 8_000_000.0,
        "free_float_shares": 7_000_000.0,
        "total_market_value": 102_000_000.0,
        "circulating_market_value": 81_600_000.0,
        "source": "tushare",
    }
    row.update(overrides)
    return pl.DataFrame([row])


class TestDailyBasic1dSchema:
    def test_valid_row_accepts_nullable_fields_and_negative_pe(self) -> None:
        DailyBasic1dSchema.validate(make_daily_basic())

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("symbol", "920001.BJ"),
            ("close", 0.0),
            ("turnover_rate", -0.1),
            ("pb", float("inf")),
            ("total_shares", 0.0),
        ],
    )
    def test_invalid_domain_values_are_rejected(
        self, field: str, value: object
    ) -> None:
        with pytest.raises(pandera.errors.SchemaError):
            DailyBasic1dSchema.validate(make_daily_basic(**{field: value}))

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("float_shares", 11_000_000.0),
            ("free_float_shares", 9_000_000.0),
            ("circulating_market_value", 103_000_000.0),
        ],
    )
    def test_share_and_market_value_relationships_are_enforced(
        self, field: str, value: float
    ) -> None:
        with pytest.raises(pandera.errors.SchemaError):
            DailyBasic1dSchema.validate(make_daily_basic(**{field: value}))

    def test_duplicate_key_is_rejected(self) -> None:
        row = make_daily_basic()
        with pytest.raises(pandera.errors.SchemaError):
            DailyBasic1dSchema.validate(pl.concat([row, row]))


class TestTargetWeightSchema:
    def make_weights(self, weights: list[float]) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "as_of": [dt.date(2026, 7, 10)] * len(weights),
                "strategy": ["etf_rotation"] * len(weights),
                "strategy_version": ["0.1.0"] * len(weights),
                "symbol": [f"{510000 + i}.SH" for i in range(len(weights))],
                "weight": weights,
            }
        )

    def test_valid_weights_pass(self):
        TargetWeightSchema.validate(self.make_weights([0.5, 0.3]))  # 留 20% 现金

    def test_weights_sum_above_one_rejected(self):
        with pytest.raises(pandera.errors.SchemaError):
            TargetWeightSchema.validate(self.make_weights([0.7, 0.5]))

    def test_negative_weight_rejected(self):
        with pytest.raises(pandera.errors.SchemaError):
            TargetWeightSchema.validate(self.make_weights([-0.1, 0.5]))

    def test_versions_have_independent_budgets(self):
        weights = pl.concat(
            [
                self.make_weights([0.7]),
                self.make_weights([0.7]).with_columns(
                    pl.lit("0.2.0").alias("strategy_version")
                ),
            ]
        )
        TargetWeightSchema.validate(weights)

    def test_duplicate_target_rejected(self):
        row = self.make_weights([0.4])
        with pytest.raises(pandera.errors.SchemaError):
            TargetWeightSchema.validate(pl.concat([row, row]))


class TestBacktestAccountEvidenceSchemas:
    @staticmethod
    def position() -> pl.DataFrame:
        return pl.DataFrame({
            "strategy": ["m2-u1"],
            "date": [dt.date(2026, 1, 5)],
            "symbol": ["600000.SH"],
            "quantity": [200],
            "settled_quantity": [100],
            "unsettled_quantity": [100],
            "mark_price": [10.0],
            "market_value": [2_000.0],
            "target_weight": [0.5],
        })

    @staticmethod
    def rejection() -> pl.DataFrame:
        return pl.DataFrame({
            "strategy": ["m2-u1"],
            "date": [dt.date(2026, 1, 5)],
            "symbol": ["600000.SH"],
            "side": ["SELL"],
            "reason": ["T_PLUS_ONE"],
            "requested_quantity": [200],
            "rejected_quantity": [200],
            "reference_price": [10.0],
        })

    def test_valid_position_and_rejection_pass(self) -> None:
        BacktestPositionSchema.validate(self.position())
        BacktestRejectionSchema.validate(self.rejection())
        BacktestPositionSchema.validate(
            self.position().with_columns(
                pl.lit(None, dtype=pl.Float64).alias("target_weight")
            )
        )

    def test_nav_requires_finite_balanced_account_values(self) -> None:
        valid = pl.DataFrame({
            "strategy": ["m2-u1"],
            "date": [dt.date(2026, 1, 5)],
            "equity": [2_000.0],
            "unit_nav": [1.0],
            "cash": [1_000.0],
            "market_value": [1_000.0],
            "cumulative_fees": [0.0],
        })
        BacktestNavSchema.validate(valid)
        with pytest.raises(pandera.errors.SchemaError):
            BacktestNavSchema.validate(
                valid.with_columns(pl.lit(float("inf")).alias("unit_nav"))
            )
        with pytest.raises(pandera.errors.SchemaError):
            BacktestNavSchema.validate(
                valid.with_columns(pl.lit(1_999.0).alias("equity"))
            )

    @pytest.mark.parametrize(
        ("column", "value"),
        [
            ("quantity", 201),
            ("market_value", 1_999.0),
            ("target_weight", 1.01),
        ],
    )
    def test_position_account_invariants_are_enforced(
        self, column: str, value: float
    ) -> None:
        with pytest.raises(pandera.errors.SchemaError):
            BacktestPositionSchema.validate(
                self.position().with_columns(pl.lit(value).alias(column))
            )

    def test_position_key_is_unique(self) -> None:
        row = self.position()
        with pytest.raises(pandera.errors.SchemaError):
            BacktestPositionSchema.validate(pl.concat([row, row]))

    @pytest.mark.parametrize(
        ("column", "value"),
        [
            ("rejected_quantity", 100),
            ("reason", "UNKNOWN"),
            ("reference_price", 0.0),
            ("reference_price", float("inf")),
        ],
    )
    def test_rejection_requires_full_known_positive_evidence(
        self, column: str, value: object
    ) -> None:
        with pytest.raises(pandera.errors.SchemaError):
            BacktestRejectionSchema.validate(
                self.rejection().with_columns(pl.lit(value).alias(column))
            )

    @pytest.mark.parametrize(
        ("side", "reason"),
        [
            ("BUY", "SELL_AT_LOWER_LIMIT"),
            ("BUY", "T_PLUS_ONE"),
            ("SELL", "BUY_AT_UPPER_LIMIT"),
        ],
    )
    def test_rejection_side_and_reason_are_consistent(
        self, side: str, reason: str
    ) -> None:
        with pytest.raises(pandera.errors.SchemaError):
            BacktestRejectionSchema.validate(
                self.rejection().with_columns(
                    pl.lit(side).alias("side"),
                    pl.lit(reason).alias("reason"),
                )
            )

    @pytest.mark.parametrize("side", ["BUY", "SELL"])
    @pytest.mark.parametrize("reason", ["SUSPENDED", "OPEN_UNKNOWN"])
    def test_no_bar_rejection_is_valid_for_both_sides(self, side: str, reason: str) -> None:
        BacktestRejectionSchema.validate(
            self.rejection().with_columns(
                pl.lit(side).alias("side"),
                pl.lit(reason).alias("reason"),
            )
        )

    def test_rejection_key_is_unique(self) -> None:
        row = self.rejection()
        with pytest.raises(pandera.errors.SchemaError):
            BacktestRejectionSchema.validate(pl.concat([row, row]))


class TestCrossFieldConstraints:
    def test_instrument_market_currency_and_dates(self):
        instrument = pl.DataFrame(
            {
                "symbol": ["00700.HK"],
                "market": ["HK"],
                "name": ["Tencent"],
                "instrument_type": ["STOCK"],
                "currency": ["HKD"],
                "list_date": [dt.date(2004, 6, 16)],
                "delist_date": [None],
                "board_lot": [100],
                "status": ["LISTED"],
            }
        )
        InstrumentSchema.validate(instrument)
        with pytest.raises(pandera.errors.SchemaError):
            InstrumentSchema.validate(instrument.with_columns(pl.lit("CNY").alias("currency")))

    def test_duplicate_calendar_row_rejected(self):
        row = pl.DataFrame(
            {
                "market": ["SZ"],
                "date": [dt.date(2026, 7, 10)],
                "is_open": [True],
                "is_connect_open": [False],
                "is_half_day": [False],
            }
        )
        with pytest.raises(pandera.errors.SchemaError):
            TradeCalendarSchema.validate(pl.concat([row, row]))

    def test_reversed_membership_range_rejected(self):
        membership = pl.DataFrame(
            {
                "universe": ["CSI300"],
                "symbol": ["000001.SZ"],
                "effective_from": [dt.date(2026, 7, 10)],
                "effective_to": [dt.date(2026, 7, 9)],
            }
        )
        with pytest.raises(pandera.errors.SchemaError):
            UniverseMembershipSchema.validate(membership)

    def test_duplicate_factor_value_rejected(self):
        row = pl.DataFrame(
            {
                "as_of": [dt.date(2026, 7, 10)],
                "symbol": ["000001.SZ"],
                "factor": ["momentum_20d"],
                "value": [0.1],
                "factor_version": ["1.0.0"],
            }
        )
        with pytest.raises(pandera.errors.SchemaError):
            FactorValueSchema.validate(pl.concat([row, row]))

    def test_order_update_before_creation_rejected(self):
        order = pl.DataFrame(
            {
                "order_id": ["order-1"],
                "broker_order_id": [None],
                "symbol": ["000001.SZ"],
                "side": ["BUY"],
                "quantity": [100],
                "limit_price": [10.0],
                "status": ["CREATED"],
                "created_at": [dt.datetime(2026, 7, 10, 9, 30)],
                "updated_at": [dt.datetime(2026, 7, 10, 9, 29)],
            }
        )
        with pytest.raises(pandera.errors.SchemaError):
            OrderSchema.validate(order)

    def test_sellable_above_position_rejected(self):
        position = pl.DataFrame(
            {
                "as_of": [dt.datetime(2026, 7, 10, 15, 0)],
                "symbol": ["000001.SZ"],
                "quantity": [100],
                "sellable": [200],
                "avg_cost": [10.0],
            }
        )
        with pytest.raises(pandera.errors.SchemaError):
            PositionSchema.validate(position)

    def test_available_cash_above_balance_rejected(self):
        cash = pl.DataFrame(
            {
                "as_of": [dt.datetime(2026, 7, 10, 15, 0)],
                "currency": ["CNY"],
                "balance": [1_000.0],
                "available": [1_001.0],
            }
        )
        with pytest.raises(pandera.errors.SchemaError):
            CashSchema.validate(cash)


class TestAdjustmentFactorSchema:
    def test_duplicate_factor_event_rejected(self):
        row = pl.DataFrame(
            {
                "symbol": ["000001.SZ"],
                "effective_date": [dt.date(2026, 6, 12)],
                "adj_factor": [124.911625],
                "source": ["baostock"],
            }
        )

        AdjustmentFactorSchema.validate(row)
        with pytest.raises(pandera.errors.SchemaError):
            AdjustmentFactorSchema.validate(pl.concat([row, row]))


class TestM3ExecutionInputSchemas:
    def test_price_limit_requires_unique_ordered_finite_values(self) -> None:
        row = pl.DataFrame({
            "symbol": ["600000.SH"],
            "trade_date": [dt.date(2026, 7, 10)],
            "pre_close": [10.0],
            "has_price_limit": [True],
            "up_limit": [11.0],
            "down_limit": [9.0],
            "source": ["tushare"],
            "source_snapshot_id": ["raw-1"],
        })
        PriceLimit1dSchema.validate(row)
        with pytest.raises(pandera.errors.SchemaError):
            PriceLimit1dSchema.validate(pl.concat([row, row]))
        with pytest.raises(pandera.errors.SchemaError):
            PriceLimit1dSchema.validate(
                row.with_columns(pl.lit(8.0).alias("up_limit"))
            )
        PriceLimit1dSchema.validate(
            row.with_columns(
                pl.lit(False).alias("has_price_limit"),
                pl.lit(None, dtype=pl.Float64).alias("up_limit"),
                pl.lit(None, dtype=pl.Float64).alias("down_limit"),
            )
        )

    def test_corporate_action_requires_effect_and_ordered_dates(self) -> None:
        row = pl.DataFrame({
            "event_id": ["event-1"],
            "symbol": ["600000.SH"],
            "ex_date": [dt.date(2026, 6, 12)],
            "action_type": ["DIVIDEND_DISTRIBUTION"],
            "cash_per_share_gross": [0.1],
            "stock_ratio": [0.0],
            "rights_price": [None],
            "rights_ratio": [0.0],
            "rights_actual_shares": [None],
            "rights_pre_shares": [None],
            "rights_post_shares": [None],
            "rights_pre_circulating_shares": [None],
            "rights_post_circulating_shares": [None],
            "rights_mixed_change_proof_sha256": [None],
            "record_date": [dt.date(2026, 6, 11)],
            "pay_date": [dt.date(2026, 6, 12)],
            "stock_list_date": [None],
            "vendor_record_id": [None],
            "source": ["tushare"],
            "source_snapshot_id": ["raw-2"],
        })
        CorporateActionLedgerSchema.validate(row)
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionLedgerSchema.validate(
                row.with_columns(
                    pl.lit(0.0).alias("cash_per_share_gross"),
                    pl.lit(0.0).alias("stock_ratio"),
                )
            )
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionLedgerSchema.validate(
                row.with_columns(pl.lit(dt.date(2026, 6, 13)).alias("record_date"))
            )
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionLedgerSchema.validate(
                row.with_columns(pl.lit(None, dtype=pl.Date).alias("pay_date"))
            )
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionLedgerSchema.validate(
                row.with_columns(pl.lit(None, dtype=pl.Date).alias("record_date"))
            )
        # dividend must keep capital fields null.
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionLedgerSchema.validate(
                row.with_columns(pl.lit(100.0).alias("rights_actual_shares"))
            )
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionLedgerSchema.validate(
                row.with_columns(
                    pl.lit(100.0).alias("rights_pre_circulating_shares")
                )
            )

    def test_corporate_action_rights_branch_validates(self) -> None:
        row = pl.DataFrame({
            "event_id": ["event-rights-1"],
            "symbol": ["000661.SZ"],
            "ex_date": [dt.date(2026, 6, 12)],
            "action_type": ["RIGHTS"],
            "cash_per_share_gross": [0.0],
            "stock_ratio": [0.0],
            "rights_price": [45.68],
            "rights_ratio": [0.3],
            "rights_actual_shares": [300.0],
            "rights_pre_shares": [1000.0],
            "rights_post_shares": [1300.0],
            "rights_pre_circulating_shares": [None],
            "rights_post_circulating_shares": [None],
            "rights_mixed_change_proof_sha256": [None],
            "record_date": [dt.date(2026, 6, 10)],
            "pay_date": [None],
            "stock_list_date": [dt.date(2026, 6, 20)],
            "vendor_record_id": ["987755581"],
            "source": ["cninfo"],
            "source_snapshot_id": ["raw-rights-1"],
        })
        CorporateActionLedgerSchema.validate(row)
        # rights_price must be null-free and positive.
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionLedgerSchema.validate(
                row.with_columns(pl.lit(None, dtype=pl.Float64).alias("rights_price"))
            )
        # rights_ratio must be positive for RIGHTS.
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionLedgerSchema.validate(
                row.with_columns(pl.lit(0.0).alias("rights_ratio"))
            )
        # cash/stock must remain zero for RIGHTS.
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionLedgerSchema.validate(
                row.with_columns(pl.lit(0.1).alias("cash_per_share_gross"))
            )
        # RIGHTS never has a cash pay_date.
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionLedgerSchema.validate(
                row.with_columns(pl.lit(dt.date(2026, 6, 12)).alias("pay_date"))
            )
        # RIGHTS always requires a stock_list_date even though stock_ratio==0.
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionLedgerSchema.validate(
                row.with_columns(pl.lit(None, dtype=pl.Date).alias("stock_list_date"))
            )
        # capital fields required and post-pre==actual.
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionLedgerSchema.validate(
                row.with_columns(
                    pl.lit(None, dtype=pl.Float64).alias("rights_actual_shares")
                )
            )
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionLedgerSchema.validate(
                row.with_columns(pl.lit(200.0).alias("rights_actual_shares"))
            )

    def test_mixed_rights_ledger_branch_validates(self) -> None:
        row = pl.DataFrame({
            "event_id": ["event-rights-mixed-1"],
            "symbol": ["601016.SH"],
            "ex_date": [dt.date(2022, 11, 28)],
            "action_type": ["RIGHTS"],
            "cash_per_share_gross": [0.0],
            "stock_ratio": [0.0],
            "rights_price": [2.28],
            "rights_ratio": [0.3],
            "rights_actual_shares": [146252.3613],
            "rights_pre_shares": [501254.9956],
            "rights_post_shares": [647507.6893],
            "rights_pre_circulating_shares": [448071.9637],
            "rights_post_circulating_shares": [594324.6574],
            "rights_mixed_change_proof_sha256": ["a" * 64],
            "record_date": [dt.date(2022, 11, 17)],
            "pay_date": [None],
            "stock_list_date": [dt.date(2022, 12, 13)],
            "vendor_record_id": ["5067319259"],
            "source": ["cninfo"],
            "source_snapshot_id": ["raw-rights-mixed-1"],
        })
        CorporateActionLedgerSchema.validate(row)

        for invalid in (
            row.with_columns(
                pl.lit(None, dtype=pl.Float64).alias(
                    "rights_pre_circulating_shares"
                )
            ),
            row.with_columns(
                pl.lit(594325.6574).alias("rights_post_circulating_shares")
            ),
            row.with_columns(
                pl.lit(None, dtype=pl.Utf8).alias(
                    "rights_mixed_change_proof_sha256"
                )
            ),
            # A residual within the Decimal representation band is not mixed.
            row.with_columns(
                pl.lit(146252.69369999).alias("rights_actual_shares")
            ),
        ):
            with pytest.raises(pandera.errors.SchemaError):
                CorporateActionLedgerSchema.validate(invalid)

        strict_with_representation_residual = row.with_columns(
            pl.lit(146252.69369999).alias("rights_actual_shares"),
            pl.lit(None, dtype=pl.Float64).alias(
                "rights_pre_circulating_shares"
            ),
            pl.lit(None, dtype=pl.Float64).alias(
                "rights_post_circulating_shares"
            ),
            pl.lit(None, dtype=pl.Utf8).alias(
                "rights_mixed_change_proof_sha256"
            ),
        )
        CorporateActionLedgerSchema.validate(strict_with_representation_residual)
        small_but_real_mixed_residual = row.with_columns(
            pl.lit(146252.6936).alias("rights_actual_shares")
        )
        CorporateActionLedgerSchema.validate(small_but_real_mixed_residual)

    def test_share_consideration_ledger_branch_validates(self) -> None:
        row = pl.DataFrame({
            "event_id": ["event-share-consideration-1"],
            "symbol": ["600733.SH"],
            "ex_date": [dt.date(2018, 8, 23)],
            "action_type": ["SHARE_CONSIDERATION"],
            "cash_per_share_gross": [0.0],
            "stock_ratio": [0.5],
            "rights_price": [None],
            "rights_ratio": [0.0],
            "rights_actual_shares": [None],
            "rights_pre_shares": [None],
            "rights_post_shares": [None],
            "rights_pre_circulating_shares": [None],
            "rights_post_circulating_shares": [None],
            "rights_mixed_change_proof_sha256": [None],
            "record_date": [dt.date(2018, 2, 1)],
            "pay_date": [None],
            "stock_list_date": [dt.date(2018, 8, 23)],
            "vendor_record_id": ["cninfo-consideration-row-1"],
            "source": ["cninfo"],
            "source_snapshot_id": ["raw-share-consideration-1"],
        })
        CorporateActionLedgerSchema.validate(row)
        for invalid in (
            row.with_columns(pl.lit(0.0).alias("stock_ratio")),
            row.with_columns(pl.lit(0.01).alias("cash_per_share_gross")),
            row.with_columns(pl.lit(0.1).alias("rights_ratio")),
            row.with_columns(
                pl.lit(dt.date(2018, 8, 24)).alias("stock_list_date")
            ),
            row.with_columns(pl.lit(dt.date(2018, 8, 23)).alias("pay_date")),
            row.with_columns(
                pl.lit("a" * 64).alias("rights_mixed_change_proof_sha256")
            ),
        ):
            with pytest.raises(pandera.errors.SchemaError):
                CorporateActionLedgerSchema.validate(invalid)

    def test_corporate_action_selection_evidence_rank_and_selected(self) -> None:
        row = pl.DataFrame({
            "economic_event_key_sha256": ["a" * 64],
            "candidate_id": ["b" * 64],
            "symbol": ["600000.SH"],
            "action_type": ["DIVIDEND_DISTRIBUTION"],
            "end_date": [dt.date(2025, 12, 31)],
            "record_date": [dt.date(2026, 6, 11)],
            "ex_date": [dt.date(2026, 6, 12)],
            "imp_ann_date": [dt.date(2026, 6, 1)],
            "ann_date": [None],
            "cash_per_share_gross": [0.1],
            "stock_ratio": [0.0],
            "rights_price": [None],
            "rights_ratio": [0.0],
            "rights_actual_shares": [None],
            "rights_pre_shares": [None],
            "rights_post_shares": [None],
            "rights_pre_circulating_shares": [None],
            "rights_post_circulating_shares": [None],
            "rights_mixed_change_proof_sha256": [None],
            "rights_mixed_change_proof_json": [None],
            "pay_date": [dt.date(2026, 6, 12)],
            "stock_list_date": [None],
            "vendor_record_id": [None],
            "candidate_rank": [1],
            "candidate_count": [1],
            "raw_row_count": [1],
            "selected": [True],
            "selection_reason": ["SELECTED_LATEST"],
            "source": ["tushare"],
            "source_request_id": ["c" * 64],
            "source_snapshot_id": ["d" * 64],
        })
        CorporateActionSelectionEvidenceSchema.validate(row)
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionSelectionEvidenceSchema.validate(
                row.with_columns(
                    pl.lit(False).alias("selected"),
                    pl.lit("SUPERSEDED_OLDER").alias("selection_reason"),
                )
            )
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionSelectionEvidenceSchema.validate(
                row.with_columns(
                    pl.lit("{}").alias("rights_mixed_change_proof_json")
                )
            )

    def test_share_consideration_selection_evidence_branch_validates(self) -> None:
        row = pl.DataFrame({
            "economic_event_key_sha256": ["a" * 64],
            "candidate_id": ["b" * 64],
            "symbol": ["600733.SH"],
            "action_type": ["SHARE_CONSIDERATION"],
            "end_date": [None],
            "record_date": [dt.date(2018, 2, 1)],
            "ex_date": [dt.date(2018, 8, 23)],
            "imp_ann_date": [None],
            "ann_date": [dt.date(2018, 8, 20)],
            "cash_per_share_gross": [0.0],
            "stock_ratio": [0.5],
            "rights_price": [None],
            "rights_ratio": [0.0],
            "rights_actual_shares": [None],
            "rights_pre_shares": [None],
            "rights_post_shares": [None],
            "rights_pre_circulating_shares": [None],
            "rights_post_circulating_shares": [None],
            "rights_mixed_change_proof_sha256": [None],
            "rights_mixed_change_proof_json": [None],
            "pay_date": [None],
            "stock_list_date": [dt.date(2018, 8, 23)],
            "vendor_record_id": ["cninfo-consideration-row-1"],
            "candidate_rank": [1],
            "candidate_count": [1],
            "raw_row_count": [1],
            "selected": [True],
            "selection_reason": ["SELECTED_LATEST"],
            "source": ["cninfo"],
            "source_request_id": ["c" * 64],
            "source_snapshot_id": ["d" * 64],
        })
        CorporateActionSelectionEvidenceSchema.validate(row)
        for invalid in (
            row.with_columns(pl.lit(dt.date(2018, 8, 20)).alias("end_date")),
            row.with_columns(pl.lit(0.0).alias("stock_ratio")),
            row.with_columns(pl.lit(0.01).alias("cash_per_share_gross")),
            row.with_columns(
                pl.lit(dt.date(2018, 8, 24)).alias("stock_list_date")
            ),
            row.with_columns(
                pl.lit("{}").alias("rights_mixed_change_proof_json")
            ),
        ):
            with pytest.raises(pandera.errors.SchemaError):
                CorporateActionSelectionEvidenceSchema.validate(invalid)

    def test_mixed_rights_selection_evidence_branch_validates(self) -> None:
        proof_json = (
            '{"schema_version":"m3-g1-cninfo-rights-mixed-change-proof-v1"}'
        )
        row = pl.DataFrame({
            "economic_event_key_sha256": ["a" * 64],
            "candidate_id": ["b" * 64],
            "symbol": ["601016.SH"],
            "action_type": ["RIGHTS"],
            "end_date": [dt.date(2022, 11, 10)],
            "record_date": [dt.date(2022, 11, 17)],
            "ex_date": [dt.date(2022, 11, 28)],
            "imp_ann_date": [dt.date(2022, 11, 24)],
            "ann_date": [dt.date(2022, 11, 10)],
            "cash_per_share_gross": [0.0],
            "stock_ratio": [0.0],
            "rights_price": [2.28],
            "rights_ratio": [0.3],
            "rights_actual_shares": [146252.3613],
            "rights_pre_shares": [501254.9956],
            "rights_post_shares": [647507.6893],
            "rights_pre_circulating_shares": [448071.9637],
            "rights_post_circulating_shares": [594324.6574],
            "rights_mixed_change_proof_sha256": ["c" * 64],
            "rights_mixed_change_proof_json": [proof_json],
            "pay_date": [None],
            "stock_list_date": [dt.date(2022, 12, 13)],
            "vendor_record_id": ["5067319259"],
            "candidate_rank": [1],
            "candidate_count": [1],
            "raw_row_count": [1],
            "selected": [True],
            "selection_reason": ["SELECTED_LATEST"],
            "source": ["cninfo"],
            "source_request_id": ["d" * 64],
            "source_snapshot_id": ["e" * 64],
        })
        CorporateActionSelectionEvidenceSchema.validate(row)

        for invalid in (
            row.with_columns(
                pl.lit(None, dtype=pl.Utf8).alias(
                    "rights_mixed_change_proof_json"
                )
            ),
            row.with_columns(
                pl.lit(None, dtype=pl.Utf8).alias(
                    "rights_mixed_change_proof_sha256"
                )
            ),
            row.with_columns(
                pl.lit(594325.6574).alias("rights_post_circulating_shares")
            ),
            row.with_columns(
                pl.lit(146252.69369999).alias("rights_actual_shares")
            ),
        ):
            with pytest.raises(pandera.errors.SchemaError):
                CorporateActionSelectionEvidenceSchema.validate(invalid)

        strict = row.with_columns(
            pl.lit(146252.6937).alias("rights_actual_shares"),
            pl.lit(None, dtype=pl.Float64).alias(
                "rights_pre_circulating_shares"
            ),
            pl.lit(None, dtype=pl.Float64).alias(
                "rights_post_circulating_shares"
            ),
            pl.lit(None, dtype=pl.Utf8).alias(
                "rights_mixed_change_proof_sha256"
            ),
            pl.lit(None, dtype=pl.Utf8).alias(
                "rights_mixed_change_proof_json"
            ),
        )
        CorporateActionSelectionEvidenceSchema.validate(strict)
        small_but_real_mixed_residual = row.with_columns(
            pl.lit(146252.6936).alias("rights_actual_shares")
        )
        CorporateActionSelectionEvidenceSchema.validate(
            small_but_real_mixed_residual
        )

    def test_corporate_action_reconciliation_status_branches(self) -> None:
        no_event = pl.DataFrame({
            "symbol": ["600000.SH"],
            "previous_factor_date": [dt.date(2026, 6, 10)],
            "effective_date": [dt.date(2026, 6, 11)],
            "previous_close_date": [None],
            "previous_close": [None],
            "ex_reference_price": [None],
            "daily_request_id": ["a" * 64],
            "daily_stable_response_sha256": ["b" * 64],
            "event_count": [0],
            "event_ids_json": ["[]"],
            "event_ids_sha256": ["c" * 64],
            "stock_ratio_terms_json": ["[]"],
            "stock_ratio_terms_sha256": ["d" * 64],
            "cash_per_share_gross": [0.0],
            "stock_ratio": [0.0],
            "rights_ratio": [0.0],
            "rights_subscription_cash_per_share": [0.0],
            "declared_dividend_factor_ratio": [1.0],
            "market_reference_factor_ratio": [None],
            "actual_factor_ratio": [1.0],
            "market_reference_relative_error": [None],
            "declared_dividend_relative_error": [0.0],
            "factor_ratio_rtol": [0.001],
            "status": ["NO_EVENT_STABLE_FACTOR"],
            "source": ["tushare"],
        })
        CorporateActionReconciliationSchema.validate(no_event)
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionReconciliationSchema.validate(
                no_event.with_columns(pl.lit(0.02).alias("factor_ratio_rtol"))
            )
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionReconciliationSchema.validate(
                no_event.with_columns(
                    pl.lit('[{"event_id":"event-1"}]').alias(
                        "stock_ratio_terms_json"
                    )
                )
            )
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionReconciliationSchema.validate(
                no_event.with_columns(
                    pl.lit("not-json").alias("stock_ratio_terms_json")
                )
            )
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionReconciliationSchema.validate(
                no_event.with_columns(
                    pl.lit("not-a-sha256").alias("stock_ratio_terms_sha256")
                )
            )

        matched = no_event.with_columns(
            pl.lit(dt.date(2026, 6, 10)).alias("previous_close_date"),
            pl.lit(10.0).alias("previous_close"),
            pl.lit(1).alias("event_count"),
            pl.lit('["event-share-consideration-1"]').alias("event_ids_json"),
            pl.lit("e" * 64).alias("event_ids_sha256"),
            pl.lit(
                '[{"basis_multiplier":"3.5",'
                '"effective_stock_ratio":"0.142857142857142857",'
                '"event_id":"event-share-consideration-1",'
                '"raw_stock_ratio":"0.5"}]'
            ).alias("stock_ratio_terms_json"),
            pl.lit("f" * 64).alias("stock_ratio_terms_sha256"),
            pl.lit(0.5 / 3.5).alias("stock_ratio"),
            pl.lit(1.0 + 0.5 / 3.5).alias(
                "declared_dividend_factor_ratio"
            ),
            pl.lit(1.0 + 0.5 / 3.5).alias("actual_factor_ratio"),
            pl.lit(0.0).alias("declared_dividend_relative_error"),
            pl.lit("MATCHED_EVENT_DECLARED_FORMULA_NO_MARKET_REFERENCE").alias(
                "status"
            ),
        )
        CorporateActionReconciliationSchema.validate(matched)
        with pytest.raises(pandera.errors.SchemaError):
            CorporateActionReconciliationSchema.validate(
                matched.with_columns(pl.lit("[]").alias("stock_ratio_terms_json"))
            )
