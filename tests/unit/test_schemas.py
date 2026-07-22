"""数据契约最小单测:合法数据通过,非法数据被拒绝。"""

import datetime as dt

import pandera.errors
import polars as pl
import pytest

from quant.domain import (
    AdjustmentFactorSchema,
    Bar1dSchema,
    CashSchema,
    CorporateActionLedgerSchema,
    CorporateActionReconciliationSchema,
    CorporateActionSelectionEvidenceSchema,
    FactorValueSchema,
    InstrumentSchema,
    OrderSchema,
    PositionSchema,
    PriceLimit1dSchema,
    TargetWeightSchema,
    TradeCalendarSchema,
    UniverseMembershipSchema,
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
            "cash_per_share_gross": [0.1],
            "stock_ratio": [0.0],
            "record_date": [dt.date(2026, 6, 11)],
            "pay_date": [dt.date(2026, 6, 12)],
            "stock_list_date": [None],
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

    def test_corporate_action_selection_evidence_rank_and_selected(self) -> None:
        row = pl.DataFrame({
            "economic_event_key_sha256": ["a" * 64],
            "candidate_id": ["b" * 64],
            "symbol": ["600000.SH"],
            "end_date": [dt.date(2025, 12, 31)],
            "record_date": [dt.date(2026, 6, 11)],
            "ex_date": [dt.date(2026, 6, 12)],
            "imp_ann_date": [dt.date(2026, 6, 1)],
            "ann_date": [None],
            "cash_per_share_gross": [0.1],
            "stock_ratio": [0.0],
            "pay_date": [dt.date(2026, 6, 12)],
            "stock_list_date": [None],
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
            "cash_per_share_gross": [0.0],
            "stock_ratio": [0.0],
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
