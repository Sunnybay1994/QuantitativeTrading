import datetime as dt
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quant.factors.pit_quality import PIT_QUALITY_FACTOR_NAMES
from quant.research.factor_financials import attach_quality_factors, attach_financial_factors, financial_input_names
from quant.research.pit_quality_research import build_pit_quality_signal_values
from tests.unit.test_pit_quality_research import _histories
from tests.unit.test_factor_expressions import prepared, sample_bars
from quant.factors import compute


def test_announcements_conflicting_revisions_and_missing_bars_match_daily_reselection():
    income, balance, cash = _histories()
    # A new conflicting annual revision must erase an earlier valid score.
    revision = income.tail(1).with_columns(
        pl.lit(dt.date(2024, 4, 25)).alias("available_date"),
        pl.lit(dt.date(2024, 4, 25)).alias("ann_date"),
        pl.lit(dt.date(2024, 4, 25)).alias("f_ann_date"),
    )
    income = pl.concat([income, revision, revision.with_columns(pl.lit(999.).alias("n_income"))])
    histories = {"income": income, "balancesheet": balance, "cashflow": cash}
    dates = tuple(dt.date(2024, 4, day) for day in (22, 23, 24, 25, 26, 29))
    panel = pl.DataFrame({"trade_date": dates, "symbol": ["000001.SZ"] * len(dates),
                          "close": [10., 10., None, 10., 10., 10.]})
    expected = build_pit_quality_signal_values(
        income_history=income, balance_history=balance, cash_history=cash,
        signal_dates=dates, candidate_symbols=("000001.SZ",), allowed_report_types=("1",),
    ).factors.select("symbol", "trade_date", *PIT_QUALITY_FACTOR_NAMES)
    expected = panel.join(expected, on=["symbol", "trade_date"]).with_columns(
        pl.when(pl.col("close").is_not_null()).then(pl.col(name)).otherwise(None).alias(name)
        for name in PIT_QUALITY_FACTOR_NAMES
    ).sort("symbol", "trade_date")
    actual = attach_quality_factors(panel, histories)
    assert_frame_equal(actual, expected)
    assert actual.filter(pl.col("trade_date") == dt.date(2024, 4, 23))["pit_roa_ttm"].item() is not None
    assert actual.filter(pl.col("trade_date") == dt.date(2024, 4, 26))["pit_roa_ttm"].item() is None
    cutoff = dt.date(2024, 4, 25)
    assert_frame_equal(actual.filter(pl.col("trade_date") <= cutoff), attach_quality_factors(
        panel.filter(pl.col("trade_date") <= cutoff), histories))
    wide = {name: frame.with_columns(pl.lit(1.).alias("unrelated_measure"))
            for name, frame in histories.items()}
    duplicate = wide["income"].filter(pl.col("end_date") == dt.date(2023, 6, 30)).with_columns(
        pl.lit(2.).alias("unrelated_measure"))
    wide["income"] = pl.concat([wide["income"], duplicate])
    assert_frame_equal(actual, attach_quality_factors(panel, wide))


def test_quality_batch_reads_history_and_increment_matches_full(tmp_path, monkeypatch):
    dates = tuple(dt.date(2024, 4, day) for day in (22, 23, 24, 25, 26, 29))
    bars = sample_bars().filter(pl.col("symbol") == "600000.SH").head(len(dates)).with_columns(
        pl.Series("trade_date", dates, dtype=pl.Date), pl.lit("000001.SZ").alias("symbol"))
    monkeypatch.setattr(compute, "available_sessions", lambda root, end: tuple(d for d in dates if d <= end))

    def read(root, config, start, end, sessions):
        subset = bars.filter(pl.col("trade_date").is_between(start, end))
        return prepared(subset), subset

    monkeypatch.setattr(compute, "read_factor_inputs", read)
    config = tmp_path / "refresh.toml"
    config.write_text('financial_snapshot="fixture"\n')
    library = tmp_path / "library"
    library.mkdir()
    for name in PIT_QUALITY_FACTOR_NAMES:
        (library / f"{name}.toml").write_text(
            f'id="{name}"\nexpr="{name}"\nfamily="pit_quality"\ndirection=1\nsource_ref="fixture"\n')
    income, balance, cash = _histories()
    for mode in ("full", "increment"):
        root = tmp_path / mode / "clean/tushare_financials/fixture"
        root.mkdir(parents=True)
        for name, frame in (("income", income), ("balancesheet", balance), ("cashflow", cash)):
            frame.write_parquet(root / f"{name}.parquet")
    common = dict(refresh_config=config, library=library, selected="all", start=dates[0],
                  artifact_root=tmp_path / "artifacts")
    compute.run(**common, data_root=tmp_path / "increment", end=dates[2])
    compute.run(**common, data_root=tmp_path / "increment", end=dates[-1])
    compute.run(**common, data_root=tmp_path / "full", end=dates[-1])
    for name in PIT_QUALITY_FACTOR_NAMES:
        path = Path("factors") / name / "year=2024/data.parquet"
        full = pl.read_parquet(tmp_path / "full" / path)
        assert full["value"].count() > 0
        assert_frame_equal(full, pl.read_parquet(tmp_path / "increment" / path))
    assert compute.run(**common, data_root=tmp_path / "increment", end=dates[-1])["years"] == []


def test_annual_report_expires_without_another_announcement():
    income, balance, cash = _histories()
    cash = cash.with_columns(pl.lit(5.).alias("depr_fa_coga_dpba"),
                             pl.lit(4.).alias("c_pay_acq_const_fiolta"))
    balance = balance.with_columns(*[pl.lit(value).alias(name) for name, value in
        (("total_cur_assets", 50.), ("total_cur_liab", 20.), ("money_cap", 5.),
         ("st_borr", 3.), ("taxes_payable", 2.))])
    panel = pl.DataFrame({"symbol": ["000001.SZ"] * 3,
        "trade_date": [dt.date(2024, 4, 23), dt.date(2025, 6, 30), dt.date(2025, 7, 1)],
        "close": [10., 10., 10.]})
    name = "pit_annual_cash_profitability"
    actual = attach_financial_factors(panel, {"income": income, "balancesheet": balance,
                                             "cashflow": cash}, (name,))
    assert actual[name].to_list() == [pytest.approx(71 / 120), pytest.approx(71 / 120), None]
    assert financial_input_names((f"rank({name}) + pit_roa_ttm", "close")) == (
        "pit_annual_cash_profitability", "pit_roa_ttm")


def _expanded_histories():
    income, balance, cash = _histories()
    income = income.with_columns((pl.col("n_income") * 2).alias("revenue"),
        pl.col("n_income").alias("oper_cost"), pl.lit(20.).alias("ebit"))
    cash = cash.with_columns(pl.lit(5.).alias("depr_fa_coga_dpba"), pl.lit(4.).alias("c_pay_acq_const_fiolta"))
    balance = balance.with_columns(*[pl.lit(value).alias(name) for name, value in
        (("total_cur_assets", 50.), ("total_cur_liab", 20.), ("money_cap", 5.), ("st_borr", 3.),
         ("taxes_payable", 2.), ("surplus_rese", 10.), ("undistr_porfit", 30.), ("total_liab", 50.),
         ("lt_borr", 5.), ("bond_payable", 0.))])
    return {"income": income, "balancesheet": balance, "cashflow": cash}


def test_market_value_is_current_and_missing_first_day_does_not_erase_financials():
    panel = pl.DataFrame({"symbol": ["000001.SZ"] * 3,
        "trade_date": [dt.date(2024, 4, day) for day in (23, 24, 25)], "close": [10.] * 3,
        "total_market_value": [None, 1000., 2000.]})
    actual = attach_financial_factors(panel, _expanded_histories(), ("pit_cash_yield_ttm", "pit_annual_zscore"))
    assert actual["pit_cash_yield_ttm"].to_list() == [None, pytest.approx(.068), pytest.approx(.034)]
    assert actual["pit_annual_zscore"][0] is None
    assert actual["pit_annual_zscore"][2] - actual["pit_annual_zscore"][1] == pytest.approx(5.)


def test_profitability_rank_uses_each_days_full_observed_universe():
    frames = {name: [] for name in _expanded_histories()}
    for index in (1, 2, 3):
        for name, frame in _expanded_histories().items():
            frame = frame.with_columns(pl.lit(f"00000{index}.SZ").alias("symbol"))
            if name == "income":
                frame = frame.with_columns(pl.col(column) * index
                    for column in ("n_income", "n_income_attr_p", "revenue", "oper_cost"))
            frames[name].append(frame)
    histories = {name: pl.concat(parts) for name, parts in frames.items()}
    panel = pl.DataFrame({"symbol": [f"00000{index}.SZ" for index in (1, 2, 3)]}).join(
        pl.DataFrame({"trade_date": [dt.date(2024, 4, 23), dt.date(2024, 4, 24)]}), how="cross"
    ).with_columns(pl.when(~((pl.col("symbol") == "000003.SZ") &
        (pl.col("trade_date") == dt.date(2024, 4, 24)))).then(10.).alias("close"))
    actual = attach_financial_factors(panel, histories,
        ("pit_annual_profitability", "pit_annual_cash_profitability", "pit_annual_gpoa"))
    first = actual.filter(pl.col("symbol") == "000001.SZ")["pit_annual_profitability"]
    assert first.to_list() == [pytest.approx(-(1.5 ** .5)), pytest.approx(-1.)]
    assert actual.filter((pl.col("symbol") == "000003.SZ") &
        (pl.col("trade_date") == dt.date(2024, 4, 24)))["pit_annual_profitability"].item() is None


def test_added_ratios_match_statement_totals_and_invalid_denominators():
    histories = _expanded_histories()
    panel = pl.DataFrame({"symbol": ["000001.SZ"], "trade_date": [dt.date(2024, 4, 23)], "close": [10.]})
    names = ("pit_net_margin_ttm", "pit_asset_turnover_ttm", "pit_cash_to_liabilities_ttm")
    actual = attach_financial_factors(panel, histories, names)
    assert actual.select(names).row(0) == (pytest.approx(.5), pytest.approx(140 / 110), pytest.approx(68 / 50))
    histories["balancesheet"] = histories["balancesheet"].with_columns(
        pl.lit(0.).alias("total_liab"), pl.lit(-1.).alias("total_assets"))
    histories["income"] = histories["income"].with_columns(pl.lit(0.).alias("revenue"))
    invalid = attach_financial_factors(panel, histories, names)
    assert invalid.select(names).row(0) == (None, None, None)


def test_cash_profitability_retains_its_own_revision_scope_alongside_composite():
    histories = _expanded_histories()
    extra = histories["income"].tail(1).with_columns(pl.lit(999.).alias("oper_cost"))
    histories["income"] = pl.concat([histories["income"], extra])
    panel = pl.DataFrame({"symbol": ["000001.SZ"], "trade_date": [dt.date(2024, 4, 23)], "close": [10.]})
    actual = attach_financial_factors(panel, histories, ("pit_annual_cash_profitability", "pit_annual_profitability"))
    assert actual["pit_annual_cash_profitability"].item() == pytest.approx(71 / 120)


def test_fscore_updates_when_a_clarifying_notice_becomes_available():
    from tests.unit.test_annual_fscore import histories as fscore_histories

    income, cash, balance, _, _ = fscore_histories()

    def published(frame):
        return frame.with_columns((pl.col("end_date") + pl.duration(days=80)).alias("ann_date"),
            (pl.col("end_date") + pl.duration(days=80)).alias("f_ann_date"),
            (pl.col("end_date") + pl.duration(days=80)).alias("available_date"),
            pl.lit("1").alias("report_type"), pl.lit("1").alias("comp_type"),
            pl.lit("0").alias("update_flag"))

    histories = {"income": published(income), "cashflow": published(cash), "balancesheet": published(balance),
        "share_change_events": pl.DataFrame({"symbol": ["000001.SZ"], "event_date": [dt.date(2023, 3, 31)],
            "ann_date": [dt.date(2023, 4, 1)], "change_type_codes": ["015999"], "notice_non_issuance": [True],
            "notice_available_date": [dt.date(2024, 4, 2)]}),
        "share_change_coverage": pl.DataFrame({"symbol": ["000001.SZ"], "start": [dt.date(2019, 1, 1)],
            "end": [dt.date(2026, 9, 10)], "empty_response": [False]})}
    panel = pl.DataFrame({"symbol": ["000001.SZ"] * 3,
        "trade_date": [dt.date(2024, 4, day) for day in (1, 2, 3)], "close": [10.] * 3})
    actual = attach_financial_factors(panel, histories, ("pit_annual_fscore",))
    assert actual["pit_annual_fscore"].to_list() == [None, None, 9.]
