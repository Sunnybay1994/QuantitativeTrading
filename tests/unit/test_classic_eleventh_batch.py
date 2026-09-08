from __future__ import annotations

import datetime as dt
import math
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.factors import classic_eleventh_batch as eleventh
from quant.factors.classic_eleventh_batch import (
    ELEVENTH_BATCH_FACTOR_NAMES,
    compute_eleventh_batch_daily_factors,
    compute_eleventh_batch_daily_factors_with_trace,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/research/m2_classic_daily_factors_eleventh_batch.toml"


def _sessions(count: int) -> tuple[dt.date, ...]:
    return tuple(dt.date(2025, 1, 2) + dt.timedelta(days=i) for i in range(count))


def _bars(sessions: tuple[dt.date, ...], *, volumes: dict[str, list[float]] | None = None, returns: dict[str, list[float]] | None = None, price_differences: dict[str, list[float]] | None = None, common_open: float | None = None, missing: set[tuple[str, dt.date]] | None = None) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    omitted = missing or set()
    defaults = {symbol: [base * (index + 1) for index in range(len(sessions))] for symbol, base in zip(("600001.SH", "600002.SH", "600003.SH"), (100.0, 130.0, 170.0), strict=True)}
    default_returns = {symbol: [0.01 + 0.01 * ((index + offset) % 3) for index in range(len(sessions))] for symbol, offset in zip(("600001.SH", "600002.SH", "600003.SH"), (0, 1, 2), strict=True)}
    for symbol, base in zip(("600001.SH", "600002.SH", "600003.SH"), (10.0, 20.0, 30.0), strict=True):
        symbol_volumes = (volumes or {}).get(symbol, defaults[symbol])
        symbol_returns = (returns or {}).get(symbol, default_returns[symbol])
        for index, day in enumerate(sessions):
            if (symbol, day) in omitted:
                continue
            open_price = 100.0 + base if common_open is None else common_open
            close = (open_price + price_differences[symbol][index]) if price_differences is not None else open_price * (1.0 + symbol_returns[index])
            rows.append({"symbol": symbol, "trade_date": day, "open": open_price, "high": close + 1.0, "low": open_price - 1.0, "close": close, "volume": symbol_volumes[index], "amount": close * symbol_volumes[index], "adj_factor": 1.0, "source": "fixture"})
    return pl.DataFrame(rows)


def _pattern_bars(sessions: tuple[dt.date, ...]) -> pl.DataFrame:
    # Hand-selected log-volume deltas make target A ranks [0,.5,1,0,.5,1].
    d_volume = {"600001.SH": [1, 2, 3, 1, 2, 3], "600002.SH": [2, 3, 1, 2, 3, 1], "600003.SH": [3, 1, 2, 3, 1, 2]}
    d_return = {"600001.SH": [3, 2, 1, 3, 2, 1], "600002.SH": [2, 3, 1, 2, 3, 1], "600003.SH": [1, 3, 2, 1, 3, 2]}
    volumes: dict[str, list[float]] = {}
    returns: dict[str, list[float]] = {}
    for symbol in d_volume:
        log_values = [4.0, 4.5]
        for delta in d_volume[symbol]:
            log_values.append(log_values[-2] + delta)
        volumes[symbol] = [math.exp(value) for value in log_values]
        returns[symbol] = [0.0, 0.0] + [float(value) for value in d_return[symbol]]
    return _bars(sessions, volumes=volumes, returns={symbol: [0.0] * len(sessions) for symbol in d_volume}, price_differences=returns, common_open=128.0)


def _relation_bars(sessions: tuple[dt.date, ...], *, reverse: bool) -> pl.DataFrame:
    order = [1.0, 2.0, 3.0]
    volume_deltas = {"600001.SH": order * 2, "600002.SH": [2.0, 3.0, 1.0] * 2, "600003.SH": [3.0, 1.0, 2.0] * 2}
    return_deltas = volume_deltas if not reverse else {"600001.SH": [3.0, 2.0, 1.0] * 2, "600002.SH": [2.0, 1.0, 3.0] * 2, "600003.SH": [1.0, 3.0, 2.0] * 2}
    volumes: dict[str, list[float]] = {}
    differences: dict[str, list[float]] = {}
    for index, symbol in enumerate(volume_deltas):
        logs = [4.0 + index, 4.5 + index]
        for delta in volume_deltas[symbol]:
            logs.append(logs[-2] + delta)
        volumes[symbol] = [math.exp(value) for value in logs]
        differences[symbol] = [0.0, 0.0] + return_deltas[symbol]
    return _bars(sessions, volumes=volumes, price_differences=differences, common_open=128.0)


def _zero_correlation_bars(sessions: tuple[dt.date, ...]) -> pl.DataFrame:
    volume_deltas = {
        "600001.SH": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
        "600002.SH": [2.0, 3.0, 1.0, 2.0, 3.0, 1.0],
        "600003.SH": [3.0, 1.0, 2.0, 3.0, 1.0, 2.0],
    }
    return_differences = {
        "600001.SH": [1.0, 3.0, 1.0, 3.0, 1.0, 3.0],
        "600002.SH": [2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
        "600003.SH": [3.0, 1.0, 3.0, 1.0, 3.0, 1.0],
    }
    volumes: dict[str, list[float]] = {}
    differences: dict[str, list[float]] = {}
    for index, symbol in enumerate(volume_deltas):
        log_values = [4.0 + index, 4.5 + index]
        for delta in volume_deltas[symbol]:
            log_values.append(log_values[-2] + delta)
        volumes[symbol] = [math.exp(value) for value in log_values]
        differences[symbol] = [0.0, 0.0] + return_differences[symbol]
    return _bars(
        sessions,
        volumes=volumes,
        returns={symbol: [0.0] * len(sessions) for symbol in volume_deltas},
        price_differences=differences,
        common_open=128.0,
    )


def test_runtime_import_identity_is_current_worktree() -> None:
    assert Path(eleventh.__file__).resolve() == ROOT / "src/quant/factors/classic_eleventh_batch.py"


def test_public_identity_exact8_and_output_contract() -> None:
    sessions = _sessions(8)
    result = compute_eleventh_batch_daily_factors(_pattern_bars(sessions), sessions=sessions)
    assert ELEVENTH_BATCH_FACTOR_NAMES == ("alpha101_002",)
    assert result.columns == ["symbol", "trade_date", "alpha101_002"]
    assert result.schema == {"symbol": pl.String, "trade_date": pl.Date, "alpha101_002": pl.Float64}
    assert result.filter(pl.col("trade_date") != sessions[-1]).get_column("alpha101_002").null_count() == 21
    expected = 3.0 * math.sqrt(3.0) / (2.0 * math.sqrt(13.0))
    assert result.filter(pl.col("trade_date") == sessions[-1]).get_column("alpha101_002").to_list() == pytest.approx([expected, -1.0, expected])


def test_exact6_pearson_negative_and_first_value_is_session_eight(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = _sessions(8)
    captured_inputs: list[pl.DataFrame] = []
    captured_outputs: list[pl.DataFrame] = []
    original = eleventh.rank_cross_sectional_components

    def spy(frame: pl.DataFrame) -> pl.DataFrame:
        captured_inputs.append(frame)
        result = original(frame)
        captured_outputs.append(result)
        return result

    with monkeypatch.context() as context:
        context.setattr(eleventh, "rank_cross_sectional_components", spy)
        result = compute_eleventh_batch_daily_factors(_pattern_bars(sessions), sessions=sessions)
    assert len(captured_inputs) == 1
    assert len(captured_outputs) == 1
    rank_input = captured_inputs[0]
    ranks = captured_outputs[0]
    assert rank_input.height == 3 * 8 * 2
    assert not rank_input.select(pl.struct("signal_date", "component", "symbol").is_duplicated().any()).item()
    assert set(rank_input.get_column("signal_date").unique().to_list()) == set(sessions)
    assert set(rank_input.get_column("component").unique().to_list()) == {"volume_change", "intraday_return"}
    assert set(rank_input.get_column("symbol").unique().to_list()) == {"600001.SH", "600002.SH", "600003.SH"}
    assert rank_input.filter(pl.col("signal_date").is_in(list(sessions[2:8]))).height == 3 * 6 * 2
    expected_volume_input = {"600001.SH": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0], "600002.SH": [2.0, 3.0, 1.0, 2.0, 3.0, 1.0], "600003.SH": [3.0, 1.0, 2.0, 3.0, 1.0, 2.0]}
    expected_return_input = {"600001.SH": [3.0 / 128.0, 2.0 / 128.0, 1.0 / 128.0, 3.0 / 128.0, 2.0 / 128.0, 1.0 / 128.0], "600002.SH": [2.0 / 128.0, 3.0 / 128.0, 1.0 / 128.0, 2.0 / 128.0, 3.0 / 128.0, 1.0 / 128.0], "600003.SH": [1.0 / 128.0, 3.0 / 128.0, 2.0 / 128.0, 1.0 / 128.0, 3.0 / 128.0, 2.0 / 128.0]}
    expected_volume_rank = {"600001.SH": [0.0, 0.5, 1.0, 0.0, 0.5, 1.0], "600002.SH": [0.5, 1.0, 0.0, 0.5, 1.0, 0.0], "600003.SH": [1.0, 0.0, 0.5, 1.0, 0.0, 0.5]}
    expected_return_rank = {"600001.SH": [1.0, 0.0, 0.25, 1.0, 0.0, 0.25], "600002.SH": [0.5, 0.75, 0.25, 0.5, 0.75, 0.25], "600003.SH": [0.0, 0.75, 1.0, 0.0, 0.75, 1.0]}
    for symbol in expected_volume_input:
        for component, expected in (("volume_change", expected_volume_input[symbol]), ("intraday_return", expected_return_input[symbol])):
            actual = rank_input.filter((pl.col("symbol") == symbol) & (pl.col("component") == component) & pl.col("signal_date").is_in(list(sessions[2:8]))).sort("signal_date").get_column("value").to_list()
            if component == "volume_change":
                assert actual == pytest.approx(expected)
            else:
                assert actual == expected
        for component, expected in (("volume_change", expected_volume_rank[symbol]), ("intraday_return", expected_return_rank[symbol])):
            actual = ranks.filter((pl.col("symbol") == symbol) & (pl.col("component") == component) & pl.col("signal_date").is_in(list(sessions[2:8]))).sort("signal_date").get_column("normalized_rank").to_list()
            assert actual == expected
    expected = {"600001.SH": 3.0 * math.sqrt(3.0) / (2.0 * math.sqrt(13.0)), "600002.SH": -1.0, "600003.SH": 3.0 * math.sqrt(3.0) / (2.0 * math.sqrt(13.0))}
    for symbol, value in expected.items():
        values = result.filter(pl.col("symbol") == symbol).get_column("alpha101_002")
        assert values.head(7).null_count() == 7
        assert values.tail(1).item() == pytest.approx(value)


def test_exact_same_order_and_reverse_order_oracles() -> None:
    sessions = _sessions(8)
    same = compute_eleventh_batch_daily_factors(_relation_bars(sessions, reverse=False), sessions=sessions)
    reverse = compute_eleventh_batch_daily_factors(_relation_bars(sessions, reverse=True), sessions=sessions)
    assert same.filter(pl.col("trade_date") == sessions[-1]).get_column("alpha101_002").to_list() == pytest.approx([-1.0, -1.0, -1.0])
    assert reverse.filter(pl.col("trade_date") == sessions[-1]).get_column("alpha101_002").to_list() == pytest.approx([1.0, 1.0, 1.0])


def test_zero_variance_components_are_null() -> None:
    sessions = _sessions(8)
    sequence = [100.0, 130.0, 170.0, 250.0, 370.0, 530.0, 790.0, 1100.0]
    same_volume = {symbol: sequence for symbol in ("600001.SH", "600002.SH", "600003.SH")}
    same_return = {symbol: [0.01] * 8 for symbol in same_volume}
    result = compute_eleventh_batch_daily_factors(_bars(sessions, volumes=same_volume, returns=same_return), sessions=sessions)
    assert result.get_column("alpha101_002").null_count() == result.height


def test_rank_helper_is_called_once_with_independent_members_and_matches_real_call(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = _sessions(8)
    bars = _bars(sessions, volumes={"600001.SH": [0.0] + [100.0 + i * 17.0 for i in range(7)]})
    calls: list[pl.DataFrame] = []
    original = eleventh.rank_cross_sectional_components

    def spy(frame: pl.DataFrame) -> pl.DataFrame:
        calls.append(frame)
        return original(frame)

    with monkeypatch.context() as context:
        context.setattr(eleventh, "rank_cross_sectional_components", spy)
        spied = compute_eleventh_batch_daily_factors(bars, sessions=sessions)
    plain = compute_eleventh_batch_daily_factors(bars, sessions=sessions)
    ranked = original(calls[0])
    assert len(calls) == 1
    assert calls[0].columns == ["signal_date", "component", "symbol", "value"]
    assert calls[0].height == 2 * 3 * 8
    assert calls[0].filter((pl.col("component") == "volume_change") & (pl.col("symbol") == "600001.SH")).get_column("value").null_count() >= 2
    intraday_rank = ranked.filter((pl.col("component") == "intraday_return") & (pl.col("symbol") == "600001.SH"))
    volume_rank = ranked.filter((pl.col("component") == "volume_change") & (pl.col("symbol") == "600001.SH"))
    assert intraday_rank.get_column("normalized_rank").drop_nulls().len() == 8
    assert volume_rank.filter(pl.col("normalized_rank").is_null()).height >= 2
    assert spied.equals(plain)


def test_internal_gap_zero_volume_and_seven_sessions_never_bridge() -> None:
    short_sessions = _sessions(7)
    short = compute_eleventh_batch_daily_factors(_bars(short_sessions), sessions=short_sessions)
    assert short.get_column("alpha101_002").null_count() == short.height
    sessions = _sessions(9)
    bars = _bars(sessions, missing={("600001.SH", sessions[4])})
    result = compute_eleventh_batch_daily_factors(bars, sessions=sessions)
    values = result.filter(pl.col("symbol") == "600001.SH").get_column("alpha101_002")
    assert values.len() == 8
    assert values.null_count() == 8
    zero_volume = _bars(sessions, volumes={"600001.SH": [100.0, 110.0, 0.0, 140.0, 160.0, 180.0, 200.0, 220.0, 240.0]})
    zero_result = compute_eleventh_batch_daily_factors(zero_volume, sessions=sessions)
    assert zero_result.height == zero_volume.height


def test_raw_volume_log_lag2_and_same_day_return_have_exact_oracles() -> None:
    sessions = _sessions(3)
    bars = _bars(
        sessions,
        volumes={
            "600001.SH": [10.0, 20.0, 30.0],
            "600002.SH": [11.0, 21.0, 31.0],
            "600003.SH": [12.0, 22.0, 32.0],
        },
        returns={symbol: [0.0, 0.0, 0.1] for symbol in ("600001.SH", "600002.SH", "600003.SH")},
    )
    captured: list[pl.DataFrame] = []
    original = eleventh.rank_cross_sectional_components

    def spy(frame: pl.DataFrame) -> pl.DataFrame:
        captured.append(frame)
        return original(frame)

    with pytest.MonkeyPatch.context() as context:
        context.setattr(eleventh, "rank_cross_sectional_components", spy)
        compute_eleventh_batch_daily_factors(bars, sessions=sessions)
    day = sessions[2]
    row = captured[0].filter((pl.col("symbol") == "600001.SH") & (pl.col("signal_date") == day))
    assert row.filter(pl.col("component") == "volume_change").get_column("value").item() == pytest.approx(math.log(3.0))
    assert row.filter(pl.col("component") == "intraday_return").get_column("value").item() == pytest.approx(0.1)


def test_negative_volume_fails_closed() -> None:
    sessions = _sessions(8)
    bars = _bars(sessions).with_columns(
        pl.when((pl.col("symbol") == "600001.SH") & (pl.col("trade_date") == sessions[2]))
        .then(-1.0)
        .otherwise(pl.col("volume"))
        .alias("volume")
    )
    with pytest.raises(ValueError):
        compute_eleventh_batch_daily_factors(bars, sessions=sessions)


def test_missing_lag1_bar_nulls_volume_feature_at_next_session() -> None:
    sessions = _sessions(8)
    bars = _bars(sessions, missing={("600001.SH", sessions[3])})
    captured: list[pl.DataFrame] = []
    original = eleventh.rank_cross_sectional_components

    def spy(frame: pl.DataFrame) -> pl.DataFrame:
        captured.append(frame)
        return original(frame)

    with pytest.MonkeyPatch.context() as context:
        context.setattr(eleventh, "rank_cross_sectional_components", spy)
        compute_eleventh_batch_daily_factors(bars, sessions=sessions)
    target = captured[0].filter(
        (pl.col("symbol") == "600001.SH")
        & (pl.col("signal_date") == sessions[4])
        & (pl.col("component") == "volume_change")
    )
    assert target.get_column("value").item() is None


def test_public_rank_n1_n2_ties_and_null_are_component_specific() -> None:
    day = _sessions(1)[0]
    frame = pl.DataFrame({"signal_date": [day] * 4, "component": ["a", "a", "b", "b"], "symbol": ["A", "B", "A", "B"], "value": [1.0, 1.0, 2.0, None]}, schema={"signal_date": pl.Date, "component": pl.String, "symbol": pl.String, "value": pl.Float64})
    ranked = eleventh.rank_cross_sectional_components(frame)
    assert ranked.filter(pl.col("component") == "a").get_column("normalized_rank").to_list() == [0.5, 0.5]
    assert ranked.filter(pl.col("component") == "b").get_column("normalized_rank").to_list() == [None, None]
    distinct = pl.DataFrame({"signal_date": [day, day], "component": ["d", "d"], "symbol": ["A", "B"], "value": [1.0, 2.0]}, schema={"signal_date": pl.Date, "component": pl.String, "symbol": pl.String, "value": pl.Float64})
    distinct_rank = eleventh.rank_cross_sectional_components(distinct)
    assert distinct_rank.get_column("normalized_rank").to_list() == [0.0, 1.0]
    one = pl.DataFrame({"signal_date": [day, day], "component": ["c", "c"], "symbol": ["A", "B"], "value": [None, None]}, schema={"signal_date": pl.Date, "component": pl.String, "symbol": pl.String, "value": pl.Float64})
    assert eleventh.rank_cross_sectional_components(one).get_column("normalized_rank").null_count() == 2
    assert eleventh.rank_cross_sectional_components(frame.reverse()).equals(ranked)


def test_permutations_preserve_canonical_result_and_invalid_calendar_fails() -> None:
    sessions = _sessions(8)
    bars = _pattern_bars(sessions)
    expected = compute_eleventh_batch_daily_factors(bars, sessions=sessions)
    assert compute_eleventh_batch_daily_factors(bars.reverse(), sessions=sessions).equals(expected)
    superset = (*sessions, sessions[-1] + dt.timedelta(days=1))
    assert compute_eleventh_batch_daily_factors(bars, sessions=superset).equals(expected)
    with pytest.raises(ValueError):
        compute_eleventh_batch_daily_factors(bars, sessions=tuple(reversed(sessions)))
    with pytest.raises(ValueError):
        compute_eleventh_batch_daily_factors(bars, sessions=(sessions[0], *sessions))
    with pytest.raises(ValueError):
        compute_eleventh_batch_daily_factors(bars, sessions=sessions[1:])


def test_helper_failure_is_not_replaced_by_private_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_: pl.DataFrame) -> pl.DataFrame:
        raise RuntimeError("sentinel helper failure")

    monkeypatch.setattr(eleventh, "rank_cross_sectional_components", fail)
    with pytest.raises(RuntimeError, match="sentinel helper failure"):
        compute_eleventh_batch_daily_factors(_pattern_bars(_sessions(8)), sessions=_sessions(8))


def test_invalid_duplicate_nonfinite_and_schema_contract_fail_closed() -> None:
    sessions = _sessions(8)
    bars = _bars(sessions)
    with pytest.raises(ValueError):
        compute_eleventh_batch_daily_factors(pl.concat([bars, bars.head(1)]), sessions=sessions)
    with pytest.raises(ValueError):
        compute_eleventh_batch_daily_factors(bars.with_columns(pl.lit(float("nan")).alias("volume")), sessions=sessions)
    with pytest.raises(ValueError):
        compute_eleventh_batch_daily_factors(bars.with_columns(pl.lit(True).alias("volume")), sessions=sessions)


def test_trace_tables_have_exact_contract_and_legacy_factor_identity() -> None:
    sessions = _sessions(8)
    bars = _pattern_bars(sessions)
    legacy = compute_eleventh_batch_daily_factors(bars, sessions=sessions)
    trace = compute_eleventh_batch_daily_factors_with_trace(bars, sessions=sessions)

    assert list(trace) == ["factors", "component_counts", "observations"]
    factors = trace["factors"]
    assert factors.equals(legacy)
    assert factors.columns == ["symbol", "trade_date", "alpha101_002"]
    assert factors.schema == {
        "symbol": pl.String,
        "trade_date": pl.Date,
        "alpha101_002": pl.Float64,
    }

    counts = trace["component_counts"]
    assert counts.columns == [
        "trade_date",
        "component",
        "grid_symbols",
        "finite_values",
        "ranked_values",
    ]
    assert counts.schema == {
        "trade_date": pl.Date,
        "component": pl.String,
        "grid_symbols": pl.UInt32,
        "finite_values": pl.UInt32,
        "ranked_values": pl.UInt32,
    }
    assert counts.equals(counts.sort("trade_date", "component"))
    assert counts.height == 2 * len(sessions)
    assert counts.get_column("grid_symbols").to_list() == [3] * counts.height
    for component, finite in (("volume_change", [0, 0, 3, 3, 3, 3, 3, 3]), ("intraday_return", [3] * 8)):
        actual = counts.filter(pl.col("component") == component).sort("trade_date")
        assert actual.get_column("finite_values").to_list() == finite
        assert actual.get_column("ranked_values").to_list() == finite
    assert counts.filter(pl.col("component") == "volume_change").head(2).get_column("ranked_values").to_list() == [0, 0]

    observations = trace["observations"]
    assert observations.columns == [
        "symbol",
        "trade_date",
        "bar_present",
        "volume_change",
        "intraday_return",
        "volume_rank",
        "return_rank",
        "window_ready",
        "pair_count",
        "volume_ss",
        "return_ss",
        "alpha101_002",
        "primary_reason",
        "session_index",
        "current_bar_missing",
        "lag1_bar_missing",
        "lag2_bar_missing",
        "current_volume_zero",
        "lag2_volume_zero",
        "volume_rank_members_lt2",
        "return_rank_members_lt2",
    ]
    assert observations.schema == {
        "symbol": pl.String,
        "trade_date": pl.Date,
        "bar_present": pl.Boolean,
        "volume_change": pl.Float64,
        "intraday_return": pl.Float64,
        "volume_rank": pl.Float64,
        "return_rank": pl.Float64,
        "window_ready": pl.Boolean,
        "pair_count": pl.Int64,
        "volume_ss": pl.Float64,
        "return_ss": pl.Float64,
        "alpha101_002": pl.Float64,
        "primary_reason": pl.String,
        "session_index": pl.UInt32,
        "current_bar_missing": pl.Boolean,
        "lag1_bar_missing": pl.Boolean,
        "lag2_bar_missing": pl.Boolean,
        "current_volume_zero": pl.Boolean,
        "lag2_volume_zero": pl.Boolean,
        "volume_rank_members_lt2": pl.Boolean,
        "return_rank_members_lt2": pl.Boolean,
    }
    assert observations.height == 3 * len(sessions)
    assert observations.equals(observations.sort("symbol", "trade_date"))
    assert observations.get_column("bar_present").all()
    assert observations.filter(pl.col("session_index") < 7).get_column("primary_reason").unique().to_list() == [
        "WARMUP_LT8_SESSIONS"
    ]
    assert observations.filter(pl.col("session_index") == 7).get_column("primary_reason").to_list() == [
        "VALID",
        "VALID",
        "VALID",
    ]


def test_trace_calls_public_rank_once_and_keeps_one_long_form(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = _sessions(8)
    calls: list[pl.DataFrame] = []
    original = eleventh.rank_cross_sectional_components

    def spy(frame: pl.DataFrame) -> pl.DataFrame:
        calls.append(frame)
        return original(frame)

    monkeypatch.setattr(eleventh, "rank_cross_sectional_components", spy)
    compute_eleventh_batch_daily_factors_with_trace(_pattern_bars(sessions), sessions=sessions)

    assert len(calls) == 1
    assert calls[0].columns == ["signal_date", "component", "symbol", "value"]
    assert calls[0].height == 3 * len(sessions) * 2
    assert calls[0].select(pl.struct("signal_date", "component", "symbol").is_duplicated().any()).item() is False


def test_zero_correlation_is_positive_zero_across_legacy_trace_and_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = _sessions(8)
    bars = _zero_correlation_bars(sessions)
    legacy = compute_eleventh_batch_daily_factors(bars, sessions=sessions)

    captured: list[pl.DataFrame] = []
    original = eleventh.rank_cross_sectional_components

    def spy(frame: pl.DataFrame) -> pl.DataFrame:
        ranked = original(frame)
        captured.append(ranked)
        return ranked

    monkeypatch.setattr(eleventh, "rank_cross_sectional_components", spy)
    trace = compute_eleventh_batch_daily_factors_with_trace(bars, sessions=sessions)

    assert len(captured) == 1
    expected_ranks = {
        ("volume_change", "600001.SH"): [0.0, 0.5, 1.0, 0.0, 0.5, 1.0],
        ("volume_change", "600002.SH"): [0.5, 1.0, 0.0, 0.5, 1.0, 0.0],
        ("volume_change", "600003.SH"): [1.0, 0.0, 0.5, 1.0, 0.0, 0.5],
        ("intraday_return", "600001.SH"): [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
        ("intraday_return", "600002.SH"): [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        ("intraday_return", "600003.SH"): [1.0, 0.0, 1.0, 0.0, 1.0, 0.0],
    }
    ranks = captured[0]
    for (component, symbol), expected in expected_ranks.items():
        actual = (
            ranks.filter(
                (pl.col("component") == component)
                & (pl.col("symbol") == symbol)
                & pl.col("signal_date").is_in(list(sessions[2:]))
            )
            .sort("signal_date")
            .get_column("normalized_rank")
            .to_list()
        )
        assert actual == expected

    u = [0.0, 0.5, 1.0, 0.0, 0.5, 1.0]
    r = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    u_mean = sum(u) / len(u)
    r_mean = sum(r) / len(r)
    volume_ss = sum((value - u_mean) ** 2 for value in u)
    return_ss = sum((value - r_mean) ** 2 for value in r)
    cross_ss = sum((volume - u_mean) * (returned - r_mean) for volume, returned in zip(u, r, strict=True))
    assert volume_ss == 1.0
    assert return_ss == 1.5
    assert cross_ss == 0.0
    assert -cross_ss / math.sqrt(volume_ss * return_ss) == 0.0

    def target_value(frame: pl.DataFrame, column: str) -> float | None:
        return (
            frame.filter(
                (pl.col("symbol") == "600001.SH")
                & (pl.col("trade_date") == sessions[-1])
            )
            .get_column(column)
            .item()
        )

    for value in (
        target_value(legacy, "alpha101_002"),
        target_value(trace["factors"], "alpha101_002"),
        target_value(trace["observations"], "alpha101_002"),
    ):
        assert value is not None
        assert value == 0.0
        assert math.copysign(1.0, value) == 1.0
    assert (
        trace["observations"]
        .filter(
            (pl.col("symbol") == "600001.SH")
            & (pl.col("trade_date") == sessions[-1])
        )
        .get_column("primary_reason")
        .item()
        == "VALID"
    )


def test_trace_three_tables_are_identical_for_permuted_bar_rows() -> None:
    sessions = _sessions(8)
    bars = _pattern_bars(sessions)
    expected = compute_eleventh_batch_daily_factors_with_trace(bars, sessions=sessions)
    actual = compute_eleventh_batch_daily_factors_with_trace(bars.reverse(), sessions=sessions)

    assert list(actual) == ["factors", "component_counts", "observations"]
    for key in actual:
        assert actual[key].equals(expected[key])


def test_trace_calendar_superset_keeps_factor_keys_and_exposes_no_bar_grid_rows() -> None:
    base_sessions = _sessions(8)
    sessions = (*base_sessions, base_sessions[-1] + dt.timedelta(days=1))
    bars = _pattern_bars(base_sessions)
    expected = compute_eleventh_batch_daily_factors(bars, sessions=sessions)
    trace = compute_eleventh_batch_daily_factors_with_trace(bars, sessions=sessions)

    assert trace["factors"].equals(expected)
    trailing = trace["observations"].filter(pl.col("trade_date") == sessions[-1])
    assert trailing.height == 3
    assert trailing.get_column("bar_present").to_list() == [False, False, False]
    assert trailing.get_column("current_bar_missing").to_list() == [True, True, True]
    assert trailing.get_column("primary_reason").to_list() == [
        "MISSING_CURRENT_BAR",
        "MISSING_CURRENT_BAR",
        "MISSING_CURRENT_BAR",
    ]
    assert trailing.get_column("alpha101_002").null_count() == 3
    counts = trace["component_counts"].filter(pl.col("trade_date") == sessions[-1])
    assert counts.get_column("finite_values").to_list() == [0, 0]
    assert counts.get_column("ranked_values").to_list() == [0, 0]
    assert counts.get_column("grid_symbols").to_list() == [3, 3]


def test_trace_missing_bar_preserves_calendar_lags_warmup_and_pair_reason() -> None:
    sessions = _sessions(10)
    bars = _bars(
        sessions,
        missing={("600001.SH", sessions[3]), ("600002.SH", sessions[1])},
    )
    observations = compute_eleventh_batch_daily_factors_with_trace(
        bars, sessions=sessions
    )["observations"]
    target = observations.filter(pl.col("symbol") == "600001.SH").sort("session_index")

    assert target.get_column("session_index").to_list() == list(range(10))
    assert target.get_column("lag1_bar_missing").head(1).item() is None
    assert target.get_column("lag2_bar_missing").head(2).to_list() == [None, None]
    assert target.filter(pl.col("session_index") == 3).get_column("bar_present").item() is False
    assert target.filter(pl.col("session_index") == 3).get_column("current_bar_missing").item() is True
    assert target.filter(pl.col("session_index") == 3).get_column("primary_reason").item() == "MISSING_CURRENT_BAR"
    assert target.filter(pl.col("session_index") == 4).get_column("lag1_bar_missing").item() is True
    assert target.filter(pl.col("session_index") == 5).get_column("lag2_bar_missing").item() is True
    assert target.filter(pl.col("session_index") == 4).get_column("volume_change").item() is None
    assert target.get_column("window_ready").to_list() == [False] * 5 + [True] * 5
    assert target.filter(pl.col("session_index") == 5).get_column("primary_reason").item() == "WARMUP_LT8_SESSIONS"
    pair_row = target.filter(pl.col("session_index") == 7)
    assert pair_row.get_column("bar_present").item() is True
    assert pair_row.get_column("pair_count").item() == 3
    assert pair_row.get_column("primary_reason").item() == "PAIR_INCOMPLETE"


def test_trace_zero_volume_flags_and_lag1_zero_does_not_filter_feature() -> None:
    sessions = _sessions(8)
    volumes = {
        "600001.SH": [100.0, 110.0, 0.0, 140.0, 160.0, 180.0, 200.0, 220.0],
    }
    observations = compute_eleventh_batch_daily_factors_with_trace(
        _bars(sessions, volumes=volumes), sessions=sessions
    )["observations"]
    target = observations.filter(pl.col("symbol") == "600001.SH").sort("session_index")

    zero_row = target.filter(pl.col("session_index") == 2)
    assert zero_row.get_column("current_volume_zero").item() is True
    assert zero_row.get_column("volume_change").item() is None
    assert zero_row.get_column("return_rank").item() is not None
    lag1_zero_row = target.filter(pl.col("session_index") == 3)
    assert lag1_zero_row.get_column("lag1_bar_missing").item() is False
    assert lag1_zero_row.get_column("current_volume_zero").item() is False
    assert lag1_zero_row.get_column("lag2_volume_zero").item() is False
    assert lag1_zero_row.get_column("volume_change").item() == pytest.approx(math.log(140.0 / 110.0))
    lag2_zero_row = target.filter(pl.col("session_index") == 4)
    assert lag2_zero_row.get_column("lag2_volume_zero").item() is True
    assert lag2_zero_row.get_column("volume_change").item() is None


def test_trace_single_member_and_all_tie_rank_diagnostics_are_distinct() -> None:
    sessions = _sessions(8)
    single_member = compute_eleventh_batch_daily_factors_with_trace(
        _bars(
            sessions,
            missing={("600002.SH", sessions[1]), ("600003.SH", sessions[1])},
        ),
        sessions=sessions,
    )
    day = single_member["observations"].filter(pl.col("session_index") == 2)
    assert single_member["component_counts"].filter(
        (pl.col("trade_date") == sessions[2]) & (pl.col("component") == "volume_change")
    ).select("finite_values", "ranked_values").row(0) == (1, 0)
    only_volume = day.filter(pl.col("symbol") == "600001.SH")
    assert only_volume.get_column("volume_change").item() is not None
    assert only_volume.get_column("volume_rank").item() is None
    assert only_volume.get_column("volume_rank_members_lt2").item() is True
    assert only_volume.get_column("return_rank").item() is not None
    assert only_volume.get_column("return_rank_members_lt2").item() is False

    same_volume = [100.0, 130.0, 170.0, 250.0, 370.0, 530.0, 790.0, 1100.0]
    tied = compute_eleventh_batch_daily_factors_with_trace(
        _bars(
            sessions,
            volumes={symbol: same_volume for symbol in ("600001.SH", "600002.SH", "600003.SH")},
            returns={symbol: [0.01] * 8 for symbol in ("600001.SH", "600002.SH", "600003.SH")},
            common_open=128.0,
        ),
        sessions=sessions,
    )["observations"].filter(pl.col("session_index") == 7)
    assert tied.get_column("volume_rank_members_lt2").to_list() == [False, False, False]
    assert tied.get_column("return_rank_members_lt2").to_list() == [False, False, False]
    assert tied.get_column("volume_rank").to_list() == [0.5, 0.5, 0.5]
    assert tied.get_column("return_rank").to_list() == [0.5, 0.5, 0.5]
    assert tied.get_column("primary_reason").to_list() == [
        "BOTH_VARIANCES_NONPOSITIVE",
        "BOTH_VARIANCES_NONPOSITIVE",
        "BOTH_VARIANCES_NONPOSITIVE",
    ]
    assert tied.get_column("alpha101_002").null_count() == 3


def test_trace_return_variance_reason_preserves_positive_component_ss() -> None:
    sessions = _sessions(8)
    log_volumes = {
        "600001.SH": [4.0, 4.5, 5.5, 7.0, 9.0, 11.5, 14.5, 18.0],
        "600002.SH": [5.0, 5.2, 6.4, 8.3, 10.7, 13.6, 17.0, 20.5],
        "600003.SH": [6.0, 6.8, 8.3, 10.5, 13.0, 15.8, 19.0, 23.0],
    }
    bars = _bars(
        sessions,
        volumes={symbol: [math.exp(value) for value in values] for symbol, values in log_volumes.items()},
        returns={symbol: [0.01] * 8 for symbol in log_volumes},
    )
    last = compute_eleventh_batch_daily_factors_with_trace(bars, sessions=sessions)["observations"].filter(
        pl.col("session_index") == 7
    )
    assert last.get_column("return_ss").to_list() == [0.0, 0.0, 0.0]
    assert all(value is not None and value > 0.0 for value in last.get_column("volume_ss").to_list())
    assert last.get_column("primary_reason").to_list() == [
        "RETURN_VARIANCE_NONPOSITIVE",
        "RETURN_VARIANCE_NONPOSITIVE",
        "RETURN_VARIANCE_NONPOSITIVE",
    ]
    assert last.get_column("alpha101_002").null_count() == 3


def test_trace_rejection_order_matches_legacy_input_validation() -> None:
    sessions = _sessions(8)
    bars = _bars(sessions)
    invalid_cases = (
        bars.with_columns(
            pl.when(
                (pl.col("symbol") == "600001.SH") & (pl.col("trade_date") == sessions[2])
            )
            .then(-1.0)
            .otherwise(pl.col("volume"))
            .alias("volume")
        ),
        bars.with_columns(pl.lit(float("nan")).alias("volume")),
        bars.with_columns(pl.lit(True).alias("volume")),
    )
    for invalid in invalid_cases:
        with pytest.raises(ValueError):
            compute_eleventh_batch_daily_factors(invalid, sessions=sessions)
        with pytest.raises(ValueError):
            compute_eleventh_batch_daily_factors_with_trace(invalid, sessions=sessions)


def test_trace_only_unbarred_ss_anomaly_rejects_without_changing_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    base_sessions = _sessions(8)
    sessions = (*base_sessions, base_sessions[-1] + dt.timedelta(days=1))
    bars = _pattern_bars(base_sessions)
    expected = compute_eleventh_batch_daily_factors(bars, sessions=sessions)
    original_core = eleventh._compute_eleventh_batch_core

    def inject(
        frame: pl.DataFrame,
        *,
        sessions: tuple[dt.date, ...],
    ) -> object:
        computation = original_core(frame, sessions=sessions)
        injected_grid = computation.grid.with_columns(
            pl.when(
                pl.col("_bar_present").is_null() & (pl.col("_session_index") == 8)
            )
            .then(1.0)
            .otherwise(pl.col("_u_ss"))
            .alias("_u_ss")
        )
        return eleventh._EleventhBatchComputation(
            factors=computation.factors,
            grid=injected_grid,
        )

    monkeypatch.setattr(eleventh, "_compute_eleventh_batch_core", inject)
    assert compute_eleventh_batch_daily_factors(bars, sessions=sessions).equals(expected)
    with pytest.raises(ValueError, match="unexplained intermediate"):
        compute_eleventh_batch_daily_factors_with_trace(bars, sessions=sessions)


def test_trace_nonfinite_intermediate_rejects_without_partial_or_legacy_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = _sessions(8)
    bars = _pattern_bars(sessions)
    expected = compute_eleventh_batch_daily_factors(bars, sessions=sessions)
    original_core = eleventh._compute_eleventh_batch_core

    def inject(
        frame: pl.DataFrame,
        *,
        sessions: tuple[dt.date, ...],
    ) -> object:
        computation = original_core(frame, sessions=sessions)
        injected_grid = computation.grid.with_columns(
            pl.when(
                pl.col("_bar_present").is_not_null() & (pl.col("_session_index") == 7)
            )
            .then(float("nan"))
            .otherwise(pl.col("_cross_ss"))
            .alias("_cross_ss")
        )
        return eleventh._EleventhBatchComputation(
            factors=computation.factors,
            grid=injected_grid,
        )

    monkeypatch.setattr(eleventh, "_compute_eleventh_batch_core", inject)
    assert compute_eleventh_batch_daily_factors(bars, sessions=sessions).equals(expected)
    returned: object | None = None
    with pytest.raises(ValueError, match="unexplained intermediate"):
        returned = compute_eleventh_batch_daily_factors_with_trace(bars, sessions=sessions)
    assert returned is None


def test_trace_pair_count_six_with_null_ss_rejects_without_partial_or_legacy_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = _sessions(8)
    bars = _pattern_bars(sessions)
    expected = compute_eleventh_batch_daily_factors(bars, sessions=sessions)
    baseline = compute_eleventh_batch_daily_factors_with_trace(bars, sessions=sessions)
    assert baseline["observations"].filter(pl.col("session_index") == 7).get_column("pair_count").to_list() == [6, 6, 6]
    original_core = eleventh._compute_eleventh_batch_core

    def inject(
        frame: pl.DataFrame,
        *,
        sessions: tuple[dt.date, ...],
    ) -> object:
        computation = original_core(frame, sessions=sessions)
        injected_grid = computation.grid.with_columns(
            pl.when(
                (pl.col("_bar_present").is_not_null())
                & (pl.col("_session_index") == 7)
                & (pl.col("_pair_count") == 6)
            )
            .then(pl.lit(None, dtype=pl.Float64))
            .otherwise(pl.col("_u_ss"))
            .alias("_u_ss")
        )
        return eleventh._EleventhBatchComputation(
            factors=computation.factors,
            grid=injected_grid,
        )

    monkeypatch.setattr(eleventh, "_compute_eleventh_batch_core", inject)
    assert compute_eleventh_batch_daily_factors(bars, sessions=sessions).equals(expected)
    returned: object | None = None
    with pytest.raises(ValueError, match="unexplained intermediate"):
        returned = compute_eleventh_batch_daily_factors_with_trace(bars, sessions=sessions)
    assert returned is None


def test_config_exact_identity_contract() -> None:
    with CONFIG.open("rb") as handle:
        config = tomllib.load(handle)
    assert list(config) == ["research", "data", "universe", "factors", "alpha101_eleventh_batch", "coverage", "portfolio", "admission", "walk_forward"]
    assert config["research"]["hypothesis_id"] == "m2-alpha101-002-price-volume-divergence-v1"
    assert config["research"]["hypothesis"] == "Higher values of the fixed Alpha101 #002 price-volume divergence factor predict higher future returns; this remains unassessed until a separately authorized walk-forward run."
    assert config["research"]["strategy_name"] == "classic_alpha101_002_price_volume_divergence_top50"
    assert config["research"]["strategy_version"] == "v1"
    assert type(config["research"]["random_seed"]) is int
    assert config["data"] == {"snapshot_id": "b79a7b5e66dee0ae439c030078414157ca6c1f3b6ce7fbe5e36ff3910c1089d2", "warmup_start": dt.date(2019, 1, 1), "research_start": dt.date(2020, 1, 1), "research_end": dt.date(2026, 8, 13)}
    assert config["universe"] == {"freeze_start": dt.date(2019, 1, 1), "freeze_end": dt.date(2019, 12, 31), "top_n": 800, "minimum_observations": 120, "minimum_average_amount": 20000000.0}
    assert config["factors"]["catalog"] == "alpha101_price_volume_divergence_eleventh_batch_v1"
    assert config["factors"]["names"] == ["alpha101_002"]
    assert config["factors"]["redundancy_reference_names"] == ["alpha101_011", "alpha101_033", "alpha101_101", "alpha158_corr20", "liquidity_20"]
    assert config["factors"]["horizons"] == [1, 5, 20]
    assert config["factors"]["minimum_history_rows"] == 120
    assert config["factors"]["minimum_daily_symbols"] == 100
    assert config["factors"]["groups"] == 5
    assert config["factors"]["maximum_median_absolute_rank_correlation"] == pytest.approx(0.80)
    alpha = config["alpha101_eleventh_batch"]
    assert list(alpha) == ["schema_version", "hypothesis_id", "factors", "volume_basis", "volume_transform", "intraday_return", "cross_section_rank", "correlation", "required_contiguous_sessions", "expected_direction", "direction_policy", "attempt_ordinal", "trial_budget", "trial_delta", "economic_execution"]
    assert alpha["trial_delta"] == 0
    assert alpha["economic_execution"] == "BLOCKED_PENDING_PUBLIC_RECEIPT_AND_RUN_TASKBOOK"
    frozen = {
        "schema_version": ("m2-alpha101-eleventh-batch-v1", str),
        "hypothesis_id": ("m2-alpha101-002-price-volume-divergence-v1", str),
        "factors": (["alpha101_002"], list),
        "volume_basis": ("raw_shares", str),
        "volume_transform": ("natural_log_delta_2_sessions", str),
        "intraday_return": ("raw_close_minus_open_divided_by_open", str),
        "cross_section_rank": ("average_normalized_zero_one_ascending_component_specific", str),
        "correlation": ("pearson_exact_6_contiguous_pairs", str),
        "required_contiguous_sessions": (8, int),
        "expected_direction": (1, int),
        "direction_policy": ("pre_registered_fixed_positive", str),
        "attempt_ordinal": (1, int),
        "trial_budget": (1, int),
        "trial_delta": (0, int),
        "economic_execution": ("BLOCKED_PENDING_PUBLIC_RECEIPT_AND_RUN_TASKBOOK", str),
    }
    for key, (value, expected_type) in frozen.items():
        assert type(alpha[key]) is expected_type
        assert alpha[key] == value
    assert config["coverage"] == {"minimum_rebalance_symbols": 100, "minimum_median_coverage": 0.80}
    assert config["portfolio"] == {"selection_horizon_sessions": 20, "rebalance_every_sessions": 20, "top_k": 50, "initial_cash": 1000000.0, "cost_multipliers": [0.5, 1.0, 2.0], "cost_config_relative_path": "configs/research/m3_qlib_example.toml", "cost_schedule_semantic_sha256": "b2041d8495aa408de0bd264d6c03eb7e4d174e03f120289bc8471cbb5ea0a959"}
    assert config["admission"] == {"minimum_mean_test_rank_ic": 0.01, "minimum_positive_test_folds": 2, "require_direction_consistency": True, "require_positive_2x_cost_return": True}
    assert len(config["walk_forward"]["folds"]) == 3
    assert all(type(fold[key]) is dt.date for fold in config["walk_forward"]["folds"] for key in ("train_start", "train_end", "validation_start", "validation_end", "test_start", "test_end"))
