import copy
import datetime as dt
import json

import polars as pl
from polars.testing import assert_frame_equal
import pytest

from quant.backtest import DailyMarketState
from quant.research import factor_battery_costs as costs
from quant.research import factor_cost_checkpoint as checkpoints
from quant.research.classic_monthly_baseline import replay
from tests.unit.test_paper_ledger import SYMBOL, inputs

DAYS = [dt.date(2020, 12, day) for day in (29, 30, 31)] + [dt.date(2021, 1, day) for day in (4, 5)]


def scenario(kind="deferred"):
    source, _ = inputs()
    source["bars"] = pl.concat([source["bars"].head(1).with_columns(
        pl.lit(date).alias("trade_date")) for date in DAYS])
    source["calendar"] = pl.concat([source["calendar"].head(1).with_columns(
        pl.lit(date).alias("date")) for date in DAYS])
    source["instruments"] = source["instruments"].with_columns(pl.lit("STOCK").alias("instrument_type"))
    source["market_states"] = {(date, SYMBOL): DailyMarketState() for date in DAYS}
    cash = {"symbol": SYMBOL, "ann_date": DAYS[0], "record_date": DAYS[0],
        "ex_date": DAYS[1], "pay_date": DAYS[-1], "div_cash": 1., "share_ratio": 0.,
        "share_list_date": DAYS[-1]}
    bonus = {**cash, "ex_date": DAYS[3], "div_cash": 0., "share_ratio": .5}
    if kind == "restricted":
        cash["share_ratio"] = .5
        source["dividends"] = pl.from_dicts([cash])
    else:
        if kind == "reduction":
            bonus["share_ratio"] = -.2
        source["dividends"] = pl.from_dicts([cash, bonus])
    executions = [DAYS[0], DAYS[-1]] if kind == "reduction" else [DAYS[0], DAYS[2], DAYS[-1]]
    source["targets"] = pl.from_dicts([{"symbol": SYMBOL, "as_of": day-dt.timedelta(days=1),
        "execution_date": day, "strategy": "probe", "strategy_version": "1", "weight": float(i == 0)}
        for i, day in enumerate(executions)])
    source["config"] = {"portfolio": {"initial_cash": 1100., "stock_dividend_withholding": 0.,
        "cost_multipliers": [.5, 1., 2.]}, "costs": source["config"]["costs"],
        "run": {"as_of": DAYS[-1]}, "data": {"refresh_config": "unused"}}
    return source


def setup_run(monkeypatch, output, kind="deferred"):
    source = scenario(kind)
    reads = []

    def read(**kwargs):
        reads.append(kwargs["start"].year)
        assert SYMBOL in kwargs["symbols"]
        return {**{name: source[name] for name in ("bars", "calendar", "instruments", "dividends")},
                "limits": pl.DataFrame(), "suspensions": pl.DataFrame()}

    monkeypatch.setattr(costs, "read_battery_execution", read)
    monkeypatch.setattr(costs, "stock_session_states", lambda **kwargs: source["market_states"])
    output.mkdir()
    kwargs = dict(settings=source["config"], plans={"raw": ("probe", source["targets"])},
        sessions=tuple(DAYS), output=output, data_root=output.parent,
        execution_snapshot="fixture", factor="fixture")
    return source, reads, kwargs


@pytest.mark.parametrize("kind", ["deferred", "restricted", "reduction"])
def test_year_resume_matches_continuous_account_and_does_not_repeat_actions(tmp_path, monkeypatch, kind):
    source, reads, kwargs = setup_run(monkeypatch, tmp_path / "interrupted", kind)
    expected_state = {}
    expected = replay(**source, sessions=DAYS, name="probe", validate_once=True, account_state=expected_state)
    original = costs.replay

    def interrupt(**kw):
        if kw["sessions"][0].year == 2021:
            raise RuntimeError("simulated process interruption")
        return original(**kw)

    monkeypatch.setattr(costs, "replay", interrupt)
    with pytest.raises(RuntimeError, match="interruption"):
        costs.run_cost_plans(**kwargs)
    year = kwargs["output"] / "raw/cost_1/2020"
    state = json.loads((year / "account.json").read_text())["account"]
    assert state["receivables"][0]["amount"] == 100.
    if kind == "deferred":
        assert not state["holdings"]
        assert state["share_distribution_entitlements"][f"{SYMBOL}|{DAYS[3]}"]["quantity"] == 100
    elif kind == "restricted":
        assert state["restricted_shares"][0]["quantity"] == 50
    else:
        assert state["share_reduction_entitlements"][f"{SYMBOL}|{DAYS[3]}"] == 100
    original_bytes = {p.name: p.read_bytes() for p in year.iterdir()}
    monkeypatch.setattr(costs, "replay", original)
    reads.clear()
    result = costs.run_cost_plans(**kwargs, resume=True)
    assert reads == [2021]
    assert len(result["rows"]) == 3
    assert original_bytes == {p.name: p.read_bytes() for p in year.iterdir()}
    for multiplier in (.5, 1., 2.):
        folder = kwargs["output"] / "raw" / f"cost_{multiplier:g}"
        for index, kind_name in enumerate(checkpoints.KINDS):
            combined = pl.concat([pl.read_parquet(folder / str(y) / f"{kind_name}.parquet")
                                  for y in (2020, 2021)], how="vertical_relaxed")
            assert_frame_equal(combined, expected[index], check_exact=True)
        actual = json.loads((folder / "2021/account.json").read_text())["account"]
        for key in checkpoints.OPTIONAL_STATE:
            expected_state.setdefault(key, copy.deepcopy(checkpoints.OPTIONAL_STATE[key]))
        assert actual == expected_state
        assert not actual["receivables"] and not actual["share_distribution_entitlements"]
    reads.clear()
    assert costs.run_cost_plans(**kwargs, resume=True)["rows"] == result["rows"]
    assert reads == []


def test_interrupted_publication_retained_and_only_unfinished_scenario_replayed(tmp_path, monkeypatch):
    _, _, kwargs = setup_run(monkeypatch, tmp_path / "interrupted")
    original = costs.save_year

    def interrupted(folder, **kw):
        if folder.parent.name == "cost_1":
            stage = folder.parent / ".2020-unfinished-fixture"
            stage.mkdir(parents=True)
            kw["chunks"][0].write_parquet(stage / "nav.parquet")
            raise RuntimeError("partial write")
        return original(folder, **kw)

    monkeypatch.setattr(costs, "save_year", interrupted)
    with pytest.raises(RuntimeError, match="partial write"):
        costs.run_cost_plans(**kwargs)
    partial = kwargs["output"] / "raw/cost_1/.2020-unfinished-fixture/nav.parquet"
    before = partial.read_bytes()
    monkeypatch.setattr(costs, "save_year", original)
    calls = []
    original_replay = costs.replay

    def counted(**kw):
        calls.append(kw["sessions"][0].year)
        return original_replay(**kw)

    monkeypatch.setattr(costs, "replay", counted)
    costs.run_cost_plans(**kwargs, resume=True)
    assert calls.count(2020) == 2 and calls.count(2021) == 3
    assert partial.read_bytes() == before


@pytest.mark.parametrize("changed", ["settings", "targets", "old_year", "incomplete_state", "gap"])
def test_resume_rejects_changed_or_incomplete_inputs(tmp_path, monkeypatch, changed):
    _, reads, kwargs = setup_run(monkeypatch, tmp_path / "saved")
    costs.run_cost_plans(**kwargs)
    year = kwargs["output"] / "raw/cost_1/2020"
    if changed == "settings":
        kwargs["settings"]["portfolio"]["initial_cash"] = 1200.
    elif changed == "targets":
        name, targets = kwargs["plans"]["raw"]
        kwargs["plans"]["raw"] = (name, targets.with_columns(pl.lit(.5).alias("weight")))
    elif changed == "old_year":
        (year / "account.json").unlink()
    elif changed == "incomplete_state":
        saved = json.loads((year / "account.json").read_text())
        del saved["account"]["share_distribution_entitlements"]
        (year / "account.json").write_text(json.dumps(saved))
    else:
        year.rename(year.with_name(".2020-retained"))
    reads.clear()
    with pytest.raises(ValueError):
        costs.run_cost_plans(**kwargs, resume=True)
    assert reads == []


def test_legacy_partial_is_preserved_without_attempting_resume(tmp_path):
    partial = tmp_path / "targets_raw.parquet"
    partial.write_bytes(b"old incomplete run")
    source = scenario()
    with pytest.raises(ValueError, match="Old partial"):
        costs.run_cost_plans(settings=source["config"], plans={"raw": ("probe", source["targets"])},
            sessions=tuple(DAYS), output=tmp_path, data_root=tmp_path, execution_snapshot="fixture",
            factor="fixture", resume=True)
    assert partial.read_bytes() == b"old incomplete run"


def test_cash_only_year_is_saved_after_last_liquidation(tmp_path, monkeypatch):
    source, _, kwargs = setup_run(monkeypatch, tmp_path / "cash")
    source["dividends"] = source["dividends"].head(0)
    source["targets"] = source["targets"].head(2)
    kwargs["plans"]["raw"] = ("probe", source["targets"])
    kwargs["settings"]["portfolio"]["cost_multipliers"] = [1.]
    kwargs["settings"]["costs"]["a_share"]["commission_min"] = 1.
    reads = []

    def read(**kw):
        reads.append(kw["symbols"])
        return {**{name: source[name] if kw["symbols"] or name == "calendar" else source[name].head(0)
                   for name in ("bars", "calendar", "instruments", "dividends")},
                "limits": pl.DataFrame(), "suspensions": pl.DataFrame()}

    monkeypatch.setattr(costs, "read_battery_execution", read)
    costs.run_cost_plans(**kwargs)
    assert reads[-1] == []
    state = json.loads((kwargs["output"] / "raw/cost_1/2021/account.json").read_text())["account"]
    assert state["date"] == str(DAYS[-1]) and len(state["nav"]) == len(DAYS)
    assert not state["holdings"]
    assert state["cash"] == 1098. and state["cumulative_fees"] == 2.
    reads.clear()
    costs.run_cost_plans(**kwargs, resume=True)
    assert reads == []
