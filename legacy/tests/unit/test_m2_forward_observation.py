import datetime as dt
import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import pytest

import quant.research.run_s2_forward_observation as forward_module
from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchFoldV1,
    ResearchInputDigestV1,
    canonical_json_bytes,
    publish_lightweight_research_run,
    verify_lightweight_research_run,
)
from quant.research.run_s2_forward_observation import (
    M2ForwardObservationError,
    publish_forward_research_run,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FORWARD_CONFIG = (
    PROJECT_ROOT / "configs/research/m2_s2_volatility_target_forward.toml"
)
SOURCE_CONFIG = PROJECT_ROOT / "configs/research/m2_s2_volatility_target.toml"
AS_OF = dt.date(2026, 8, 31)


@dataclass(frozen=True)
class _Fixture:
    project_root: Path
    artifact_root: Path
    config_path: Path
    source_run_root: Path
    data_root: Path
    source_run: LightweightResearchRunV1


def _business_dates(count: int) -> list[dt.date]:
    result: list[dt.date] = []
    cursor = AS_OF
    while len(result) < count:
        if cursor.weekday() < 5:
            result.append(cursor)
        cursor -= dt.timedelta(days=1)
    return list(reversed(result))


def _candidate_symbols(config: dict[str, object]) -> tuple[str, ...]:
    universe = config["universe"]
    assert isinstance(universe, dict)
    return tuple(
        sorted(
            symbol
            for group in ("wide", "industry", "hong_kong_theme")
            for symbol in universe[group]
        )
    )


def _write_code_paths(project_root: Path) -> None:
    for relative in forward_module._CODE_PATHS:
        path = project_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# fixture for {relative}\n", encoding="utf-8")


def _write_data(data_root: Path, symbols: tuple[str, ...], dates: list[dt.date]) -> None:
    for date_index, date in enumerate(dates):
        rows = [
            {
                "symbol": symbol,
                "trade_date": date,
                "adjusted_close": 1.0
                + symbol_index * 0.05
                + date_index * (0.001 + symbol_index * 0.00005),
                "adjustment_method": "TOTAL_RETURN_DIVIDEND",
                "source": "forward-fixture",
            }
            for symbol_index, symbol in enumerate(symbols)
        ]
        partition = (
            data_root
            / "clean"
            / "research_price_1d"
            / f"date={date.isoformat()}"
        )
        partition.mkdir(parents=True)
        pl.DataFrame(rows).write_parquet(partition / "data.parquet")

    calendar_dates = [
        dt.date(2026, 8, 1) + dt.timedelta(days=offset)
        for offset in range(36)
    ]
    for market in ("SH", "SZ", "HK"):
        partition = data_root / "clean" / "trade_calendar" / f"market={market}"
        partition.mkdir(parents=True)
        pl.DataFrame(
            {
                "market": [market] * len(calendar_dates),
                "date": calendar_dates,
                "is_open": [date.weekday() < 5 for date in calendar_dates],
                "is_connect_open": [False] * len(calendar_dates),
                "is_half_day": [False] * len(calendar_dates),
            }
        ).write_parquet(partition / "data.parquet")


def _source_folds() -> tuple[ResearchFoldV1, ...]:
    return (
        ResearchFoldV1(
            1,
            dt.date(2023, 1, 1),
            dt.date(2024, 12, 31),
            dt.date(2025, 1, 1),
            dt.date(2025, 6, 30),
            dt.date(2025, 7, 1),
            dt.date(2025, 12, 31),
        ),
        ResearchFoldV1(
            2,
            dt.date(2023, 7, 1),
            dt.date(2025, 6, 30),
            dt.date(2025, 7, 1),
            dt.date(2025, 12, 31),
            dt.date(2026, 1, 1),
            dt.date(2026, 6, 30),
        ),
    )


def _build_fixture(tmp_path: Path, *, source_top_k: int = 2) -> _Fixture:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_code_paths(project_root)

    source_config_path = project_root / "configs/research/m2_s2_volatility_target.toml"
    source_config_path.parent.mkdir(parents=True, exist_ok=True)
    source_config_payload = SOURCE_CONFIG.read_bytes()
    source_config_path.write_bytes(source_config_payload)

    dates = _business_dates(65)
    template = FORWARD_CONFIG.read_text(encoding="utf-8")
    template = template.replace(
        "start_date = 2023-01-01", f"start_date = {dates[0].isoformat()}"
    ).replace(
        "end_date = 2026-07-10", f"end_date = {dates[0].isoformat()}"
    ).replace(
        "minimum_history_observations = 121",
        "minimum_history_observations = 65",
    ).replace("momentum_windows = [20, 60, 120]", "momentum_windows = [2, 3, 4]")
    parsed = tomllib.loads(template)
    symbols = _candidate_symbols(parsed)
    _write_data(project_root / "data", symbols, dates)

    report_payload = canonical_json_bytes(
        {
            "config": "configs/research/m2_s2_volatility_target.toml",
            "folds": [
                {
                    "fold": 1,
                    "selected_parameters": {"regression_window": 60, "top_k": 1},
                },
                {
                    "fold": 2,
                    "selected_parameters": {
                        "regression_window": 60,
                        "top_k": source_top_k,
                    },
                },
            ],
            "hypothesis_id": parsed["research"]["hypothesis_id"],
            "selection_metric": parsed["walk_forward"]["selection_metric"],
        }
    )
    source = LightweightResearchRunV1(
        schema_version="lightweight-research-run-v1",
        run_id="",
        hypothesis_id=parsed["research"]["hypothesis_id"],
        hypothesis=parsed["research"]["hypothesis"],
        strategy_name=parsed["research"]["strategy_kind"],
        strategy_version=parsed["research"]["strategy_version"],
        conclusion="RESEARCH_ONLY",
        random_seed=parsed["research"]["random_seed"],
        config_relative_path="configs/research/m2_s2_volatility_target.toml",
        config_sha256=hashlib.sha256(source_config_payload).hexdigest(),
        code_sha256=hashlib.sha256(b"source-code").hexdigest(),
        universe_name=parsed["universe"]["name"],
        universe_frozen_as_of=parsed["universe"]["frozen_as_of"],
        candidate_symbols=symbols,
        data_start=dates[0],
        data_end=dates[0],
        signal_timing="close",
        execution_timing="next_session_open",
        valuation_timing="close",
        folds=_source_folds(),
        cost_multipliers=(0.5, 1.0, 2.0),
        selection_metric="net_sharpe",
        inputs=(
            ResearchInputDigestV1(
                "source-fixture",
                1,
                dates[0],
                dates[0],
                hashlib.sha256(b"source-input").hexdigest(),
            ),
        ),
        outputs=(),
        aggregate_metrics=(("fold_count", 2),),
        caveats=("Source research-only fixture.",),
    )
    source_run_root, published_source, _ = publish_lightweight_research_run(
        artifact_root=project_root / "source-artifacts",
        run=source,
        output_payloads={"report.json": report_payload},
    )
    forward_config_path = (
        project_root / "configs/research/m2_s2_volatility_target_forward.toml"
    )
    template = template.replace(
        "e43da184f942286ae7e8b79aa25bc540f692cb467821003ce193c9d35fb7a96f",
        published_source.run_id,
    )
    forward_config_path.write_text(template, encoding="utf-8")
    return _Fixture(
        project_root=project_root,
        artifact_root=project_root / "forward-artifacts",
        config_path=forward_config_path,
        source_run_root=source_run_root,
        data_root=project_root / "data",
        source_run=published_source,
    )


def _publish(fixture: _Fixture, *, as_of: dt.date = AS_OF):
    return publish_forward_research_run(
        project_root=fixture.project_root,
        artifact_root=fixture.artifact_root,
        config_path=fixture.config_path,
        source_run_root=fixture.source_run_root,
        data_root=fixture.data_root,
        as_of=as_of,
    )


def _assert_observation_invalid(callable_) -> None:
    with pytest.raises(
        M2ForwardObservationError, match="^M2_FORWARD_OBSERVATION_INVALID$"
    ) as caught:
        callable_()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_production_config_binds_canonical_r10_source() -> None:
    config = tomllib.loads(FORWARD_CONFIG.read_text(encoding="utf-8"))
    forward = config["forward_observation"]
    assert forward["candidate_source_run_id"] == (
        "e43da184f942286ae7e8b79aa25bc540f692cb467821003ce193c9d35fb7a96f"
    )
    assert forward["candidate_source_config_relative_path"] == (
        "configs/research/m2_s2_volatility_target.toml"
    )
    assert forward["candidate_source_config_sha256"] == (
        "fd2ce82c4c3772752f383c7eb4439f1b89ee46d0272be4ce369eca84fbfaa9bf"
    )


def test_forward_run_freshly_binds_source_and_reuses_standard_bundle(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    root, run, reused = _publish(fixture)

    assert not reused
    assert verify_lightweight_research_run(run_root=root) == run
    assert run.conclusion == "RESEARCH_ONLY"
    assert run.run_id == root.name
    assert {path.name for path in root.iterdir()} == {
        "run.json",
        "scheduled_targets.parquet",
        "source_binding.json",
        "source_data_receipt.json",
        "target_weights.parquet",
    }
    assert not any(
        token in name
        for name, _ in run.aggregate_metrics
        for token in ("return", "sharpe", "drawdown")
    )
    binding = json.loads((root / "source_binding.json").read_bytes())
    assert binding["source_run_id"] == fixture.source_run.run_id
    assert binding["source_config_sha256"] == fixture.source_run.config_sha256
    assert binding["source_selected_parameters"] == {
        "regression_window": 60,
        "top_k": 2,
    }
    assert binding["forward_as_of"] == "2026-08-31"
    targets = pl.read_parquet(root / "target_weights.parquet")
    scheduled = pl.read_parquet(root / "scheduled_targets.parquet")
    assert scheduled.get_column("execution_date").unique().to_list() == [
        dt.date(2026, 9, 1)
    ]
    assert scheduled.drop("execution_date").equals(targets)
    assert 0 < targets.get_column("weight").sum() <= 1.0

    same_root, same_run, reused = _publish(fixture)
    assert reused
    assert (same_root, same_run) == (root, run)


@pytest.mark.parametrize("mutation", ["source_run_id", "source_config_sha256"])
def test_forward_run_rejects_source_identity_drift_before_artifact_creation(
    tmp_path: Path, mutation: str
) -> None:
    fixture = _build_fixture(tmp_path)
    payload = fixture.config_path.read_text(encoding="utf-8")
    if mutation == "source_run_id":
        payload = payload.replace(fixture.source_run.run_id, "0" * 64)
    else:
        payload = payload.replace(fixture.source_run.config_sha256, "0" * 64)
    fixture.config_path.write_text(payload, encoding="utf-8")

    _assert_observation_invalid(lambda: _publish(fixture))
    assert not fixture.artifact_root.exists()


def test_forward_run_rejects_valid_source_with_wrong_selected_parameters(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path, source_top_k=1)
    _assert_observation_invalid(lambda: _publish(fixture))
    assert not fixture.artifact_root.exists()


def test_forward_run_rechecks_source_and_data_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path)
    original_verify = forward_module.verify_lightweight_research_run
    calls = 0

    def drift_on_second_verify(*, run_root: Path):
        nonlocal calls
        calls += 1
        verified = original_verify(run_root=run_root)
        if calls == 2:
            raise ValueError("hostile source drift")
        return verified

    monkeypatch.setattr(
        forward_module, "verify_lightweight_research_run", drift_on_second_verify
    )
    _assert_observation_invalid(lambda: _publish(fixture))
    assert calls == 2
    assert not fixture.artifact_root.exists()


@pytest.mark.parametrize("condition", ["pre_freeze", "missing_price", "no_next_open"])
def test_forward_run_rejects_incomplete_forward_inputs_before_artifact_creation(
    tmp_path: Path, condition: str
) -> None:
    fixture = _build_fixture(tmp_path)
    as_of = AS_OF
    if condition == "pre_freeze":
        as_of = dt.date(2026, 8, 14)
    elif condition == "missing_price":
        price_path = (
            fixture.data_root
            / "clean/research_price_1d/date=2026-08-31/data.parquet"
        )
        pl.read_parquet(price_path).filter(
            pl.col("symbol") != fixture.source_run.candidate_symbols[0]
        ).write_parquet(price_path)
    else:
        for market in ("SH", "SZ"):
            path = (
                fixture.data_root
                / "clean"
                / "trade_calendar"
                / f"market={market}"
                / "data.parquet"
            )
            pl.read_parquet(path).with_columns(
                pl.when(pl.col("date") > AS_OF)
                .then(False)
                .otherwise(pl.col("is_open"))
                .alias("is_open")
            ).write_parquet(path)

    _assert_observation_invalid(lambda: _publish(fixture, as_of=as_of))
    assert not fixture.artifact_root.exists()


def test_forward_config_change_only_changes_forward_identity(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    first_root, first_run, _ = _publish(fixture)
    first_binding = json.loads((first_root / "source_binding.json").read_bytes())

    payload = fixture.config_path.read_text(encoding="utf-8").replace(
        "Forward-only observation of the frozen M2 unlevered volatility-target candidate",
        "Forward-only observation of the frozen M2 candidate with a documentation change",
    )
    fixture.config_path.write_text(payload, encoding="utf-8")
    second_root, second_run, reused = _publish(fixture)
    second_binding = json.loads((second_root / "source_binding.json").read_bytes())

    assert not reused
    assert second_run.run_id != first_run.run_id
    assert second_run.config_sha256 != first_run.config_sha256
    assert second_binding["source_run_id"] == first_binding["source_run_id"]
    assert (
        second_binding["source_config_sha256"]
        == first_binding["source_config_sha256"]
    )
