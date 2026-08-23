from __future__ import annotations

import datetime as dt
import tomllib
from copy import deepcopy
from pathlib import Path

import polars as pl
import pytest

import quant.research.run_classic_factors as classic_runner
from quant.research.lightweight_run import ResearchFoldV1
from quant.research.run_classic_factors import (
    _cost_periods,
    _cost_schedule_binding,
    _cost_schedule_binding_from_payload,
    _cost_schedule_input_digest,
    _validate_config,
    apply_fifth_batch_admission_gates,
    apply_fourth_batch_admission_gates,
    apply_market_risk_admission_gates,
    evaluate_factor_coverage,
    evaluate_primary_group_monotonicity,
    evaluate_rebalance_schedule_alignment,
    main,
    select_frozen_liquid_universe,
    summarize_factors,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_COST_SEMANTIC_SHA256 = "b2041d8495aa408de0bd264d6c03eb7e4d174e03f120289bc8471cbb5ea0a959"


def _cost_payload() -> bytes:
    return (PROJECT_ROOT / "configs/research/m3_qlib_example.toml").read_bytes().replace(
        b"\r\n", b"\n"
    )


def test_cost_schedule_semantic_digest_ignores_non_cost_serialization_only() -> None:
    periods, digest = _cost_schedule_binding_from_payload(_cost_payload())
    assert len(periods) == 3
    assert digest == _COST_SEMANTIC_SHA256

    equivalent = (
        _cost_payload()
        .decode("utf-8")
        .replace("commission_min = 5.0", "commission_min = 5.0000")
        .replace("commission_rate = 0.00025", "commission_rate = 2.5e-4")
        .replace("log_model = true", "log_model = false")
        .replace("\n", "\r\n")
        .encode("utf-8")
    )
    assert _cost_schedule_binding_from_payload(equivalent) == (periods, digest)

    for changed in (
        _cost_payload().replace(
            b'a_share_research_cost_schedule_v1', b'a_share_research_cost_schedule_v2'
        ),
        _cost_payload().replace(b"www.mof.gov.cn", b"example.invalid"),
        _cost_payload().replace(b"commission_rate = 0.00025", b"commission_rate = 0.00026", 1),
    ):
        assert _cost_schedule_binding_from_payload(changed)[1] != digest

    changed_scaled_components = _cost_payload().replace(
        b'scaled_components = ["commission_rate", "commission_min", "slippage"]',
        b'scaled_components = ["commission_rate", "slippage"]',
    )
    with pytest.raises(ValueError, match="invalid A-share cost schedule"):
        _cost_schedule_binding_from_payload(changed_scaled_components)


@pytest.mark.parametrize(
    "changed",
    (
        _cost_payload().replace(
            b'scaled_components = ["commission_rate", "commission_min", "slippage"]',
            b'scaled_components = ["commission_rate", "commission_min", "slippage"]\nunexpected = 1',
        ),
        _cost_payload().replace(
            b'schedule_version = "a_share_research_cost_schedule_v1"\n', b"", 1
        ),
        _cost_payload().replace(
            b"commission_rate = 0.00025",
            b"commission_rate = 0.00025\nunexpected = 1",
            1,
        ),
        _cost_payload().replace(b"commission_rate = 0.00025\n", b"", 1),
        _cost_payload().replace(b"effective_from = 2022-04-29", b"effective_from = 2022-04-30"),
        _cost_payload().replace(b"effective_from = 2022-04-29", b"effective_from = 2022-04-28"),
        _cost_payload().replace(b"effective_to = 2022-04-28\n", b"", 1),
        _cost_payload().replace(b"commission_min = 5.0", b"commission_min = true", 1),
    ),
    ids=(
        "cost-root-extra-key",
        "cost-root-missing-key",
        "period-extra-key",
        "period-missing-key",
        "period-gap",
        "period-overlap",
        "non-final-open-period",
        "boolean-decimal",
    ),
)
def test_cost_schedule_rejects_structural_and_numeric_drift(changed: bytes) -> None:
    with pytest.raises(ValueError, match="invalid A-share cost schedule"):
        _cost_schedule_binding_from_payload(changed)


def test_cost_periods_compatibility_and_single_payload_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    portfolio = {"cost_config_relative_path": "configs/cost.toml"}
    cost_path = tmp_path / "configs/cost.toml"
    cost_path.parent.mkdir(parents=True)
    original_payload = _cost_payload()
    cost_path.write_bytes(original_payload)
    expected = _cost_schedule_binding_from_payload(original_payload)
    original_read_bytes = Path.read_bytes
    reads = 0

    def read_then_drift(path: Path) -> bytes:
        nonlocal reads
        payload = original_read_bytes(path)
        if path.resolve() == cost_path.resolve():
            reads += 1
            cost_path.write_bytes(
                payload.replace(
                    b'scaled_components = ["commission_rate", "commission_min", "slippage"]',
                    b'scaled_components = ["commission_rate", "commission_min", "slippage"]\nunexpected = 1',
                )
            )
        return payload

    monkeypatch.setattr(Path, "read_bytes", read_then_drift)
    assert _cost_schedule_binding(tmp_path, portfolio) == expected
    assert reads == 1

    cost_path.write_bytes(original_payload)
    monkeypatch.undo()
    assert _cost_periods(tmp_path, portfolio) == expected[0]


def test_cost_input_is_canonical() -> None:
    periods, semantic_sha256 = _cost_schedule_binding_from_payload(_cost_payload())
    assert _cost_schedule_input_digest(periods, semantic_sha256).name == (
        "a-share-cost-schedule"
    )
    assert _cost_schedule_input_digest(periods, semantic_sha256).rows == 3
    assert _cost_schedule_input_digest(periods, semantic_sha256).min_date is None
    assert _cost_schedule_input_digest(periods, semantic_sha256).max_date is None
    assert _cost_schedule_input_digest(periods, semantic_sha256).content_sha256 == (
        _COST_SEMANTIC_SHA256
    )


def _frozen_max_config_payload() -> bytes:
    return (PROJECT_ROOT / "configs/research/m2_classic_daily_factors_fifth_batch.toml").read_bytes()


def _classic_project(
    tmp_path: Path, *, config_payload: bytes
) -> tuple[Path, Path, Path, Path]:
    project_root = tmp_path / "project"
    config_path = project_root / "configs/research/m2_classic_daily_factors_fifth_batch.toml"
    cost_path = project_root / "configs/research/m3_qlib_example.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes(config_payload)
    cost_path.write_bytes((PROJECT_ROOT / "configs/research/m3_qlib_example.toml").read_bytes())
    data_root = project_root / "data"
    data_root.mkdir()
    return project_root, config_path, cost_path, data_root


def _classic_main_args(project_root: Path, data_root: Path) -> list[str]:
    return [
        "--config",
        "configs/research/m2_classic_daily_factors_fifth_batch.toml",
        "--data-root",
        str(data_root),
        "--artifact-root",
        "artifacts-test",
        "--project-root",
        str(project_root),
        "--threads",
        "2",
    ]


@pytest.mark.parametrize(
    ("replacement", "message"),
    (
        (None, "invalid classic-factor config"),
        ("f" * 63, "invalid classic-factor config"),
        (_COST_SEMANTIC_SHA256.upper(), "invalid classic-factor config"),
        ("0" * 64, "classic cost schedule semantic identity mismatch"),
    ),
)
def test_classic_cost_identity_rejects_before_snapshot_or_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str | None,
    message: str,
) -> None:
    payload = _frozen_max_config_payload()
    expected_line = (
        f'cost_schedule_semantic_sha256 = "{_COST_SEMANTIC_SHA256}"\n'.encode()
    )
    if replacement is None:
        payload = payload.replace(expected_line, b"")
    else:
        payload = payload.replace(
            expected_line,
            f'cost_schedule_semantic_sha256 = "{replacement}"\n'.encode(),
        )
    project_root, _, _, data_root = _classic_project(tmp_path, config_payload=payload)
    verifier_calls: list[str] = []

    def unexpected_verifier(**_: object) -> object:
        verifier_calls.append("called")
        raise AssertionError("snapshot verifier must not run")

    monkeypatch.setattr(classic_runner, "verify_tushare_bulk_clean_snapshot", unexpected_verifier)
    with pytest.raises(ValueError, match=message):
        main(_classic_main_args(project_root, data_root))
    assert verifier_calls == []
    assert not (project_root / "artifacts-test").exists()


def test_classic_main_and_cost_each_use_one_stable_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, config_path, cost_path, data_root = _classic_project(
        tmp_path, config_payload=_frozen_max_config_payload()
    )
    original_read_bytes = Path.read_bytes
    reads = {config_path.resolve(): 0, cost_path.resolve(): 0}

    def read_then_drift(path: Path) -> bytes:
        payload = original_read_bytes(path)
        resolved = path.resolve()
        if resolved == config_path.resolve():
            reads[resolved] += 1
            zero_sha = "0" * 64
            config_path.write_bytes(
                payload.replace(
                    f'cost_schedule_semantic_sha256 = "{_COST_SEMANTIC_SHA256}"'.encode(),
                    f'cost_schedule_semantic_sha256 = "{zero_sha}"'.encode(),
                )
            )
        elif resolved == cost_path.resolve():
            reads[resolved] += 1
            cost_path.write_bytes(
                payload.replace(
                    b'scaled_components = ["commission_rate", "commission_min", "slippage"]',
                    b'scaled_components = ["commission_rate", "commission_min", "slippage"]\nunexpected = 1',
                )
            )
        return payload

    def stop_at_snapshot_verifier(**_: object) -> object:
        raise RuntimeError("SNAPSHOT_SENTINEL")

    monkeypatch.setattr(Path, "read_bytes", read_then_drift)
    monkeypatch.setattr(
        classic_runner,
        "verify_tushare_bulk_clean_snapshot",
        stop_at_snapshot_verifier,
    )
    with pytest.raises(RuntimeError, match="SNAPSHOT_SENTINEL"):
        main(_classic_main_args(project_root, data_root))
    assert reads == {config_path.resolve(): 1, cost_path.resolve(): 1}
    assert not (project_root / "artifacts-test").exists()


def test_frozen_universe_uses_only_ranked_pre_research_liquidity() -> None:
    rows: list[dict[str, object]] = []
    for symbol, amount in (("600001.SH", 30.0), ("600002.SH", 50.0), ("600003.SH", 40.0)):
        for offset in range(3):
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": dt.date(2019, 1, 1) + dt.timedelta(days=offset),
                    "amount": amount,
                }
            )
    universe = select_frozen_liquid_universe(
        pl.DataFrame(rows),
        top_n=2,
        minimum_observations=3,
        minimum_average_amount=35.0,
    )
    assert universe == ("600002.SH", "600003.SH")


def test_summary_applies_preregistered_thresholds_without_paper_status() -> None:
    rows: list[dict[str, object]] = []
    for factor, rank_ic, direction, returns in (
        ("pass", 0.02, 1, (0.03, 0.02)),
        ("reject", -0.01, -1, (-0.02, -0.03)),
    ):
        for fold in (1, 2, 3):
            for multiplier, total_return in zip((1.0, 2.0), returns, strict=True):
                rows.append(
                    {
                        "factor": factor,
                        "fold": fold,
                        "direction": direction,
                        "cost_multiplier": multiplier,
                        "test_rank_ic": rank_ic,
                        "total_return": total_return,
                    }
                )
    result = summarize_factors(
        pl.DataFrame(rows),
        factors=("pass", "reject"),
        admission={
            "minimum_mean_test_rank_ic": 0.01,
            "minimum_positive_test_folds": 2,
            "require_direction_consistency": True,
            "require_positive_2x_cost_return": True,
        },
    )
    assert result.select("factor", "research_status").rows() == [
        ("pass", "RESEARCH_ONLY"),
        ("reject", "REJECTED"),
    ]
    assert "PAPER_CANDIDATE" not in result.get_column("research_status").to_list()


def test_all_classic_factor_batch_configs_are_exactly_frozen() -> None:
    paths = (
        PROJECT_ROOT / "configs/research/m2_classic_daily_factors.toml",
        PROJECT_ROOT / "configs/research/m2_classic_daily_factors_second_batch.toml",
        PROJECT_ROOT / "configs/research/m2_classic_daily_factors_third_batch.toml",
        PROJECT_ROOT / "configs/research/m2_classic_downside_beta_510300.toml",
        PROJECT_ROOT / "configs/research/m2_classic_daily_factors_fourth_batch.toml",
        PROJECT_ROOT / "configs/research/m2_classic_daily_factors_fifth_batch.toml",
    )
    configs = []
    for path in paths:
        with path.open("rb") as stream:
            config = tomllib.load(stream)
        _validate_config(config, threads=2)
        configs.append(config)

    changed = deepcopy(configs[1])
    changed["factors"]["maximum_median_absolute_rank_correlation"] = 0.81
    with pytest.raises(ValueError, match="invalid classic-factor config"):
        _validate_config(changed, threads=2)

    changed = deepcopy(configs[2])
    changed["factors"]["redundancy_reference_names"].reverse()
    with pytest.raises(ValueError, match="invalid classic-factor config"):
        _validate_config(changed, threads=2)

    for section, key, value in (
        ("market_risk", "benchmark", "000300.SH"),
        ("market_risk", "expected_direction", 1),
        ("coverage", "minimum_rebalance_symbols", 99),
    ):
        changed = deepcopy(configs[3])
        changed[section][key] = value
        with pytest.raises(ValueError, match="invalid classic-factor config"):
            _validate_config(changed, threads=2)

    for section, key, value in (
        ("factors", "maximum_median_absolute_rank_correlation", 0.81),
        ("coverage", "minimum_rebalance_symbols", 99),
    ):
        changed = deepcopy(configs[4])
        changed[section][key] = value
        with pytest.raises(ValueError, match="invalid classic-factor config"):
            _validate_config(changed, threads=2)

    changed = deepcopy(configs[4])
    changed["factors"]["redundancy_reference_names"].reverse()
    with pytest.raises(ValueError, match="invalid classic-factor config"):
        _validate_config(changed, threads=2)

    for section, key, value in (
        ("factors", "maximum_median_absolute_rank_correlation", 0.81),
        ("max_lottery", "window_sessions", 21),
        ("max_lottery", "expected_direction", 1),
        ("max_lottery", "trial_budget", 2),
        ("coverage", "minimum_rebalance_symbols", 99),
    ):
        changed = deepcopy(configs[5])
        changed[section][key] = value
        with pytest.raises(ValueError, match="invalid classic-factor config"):
            _validate_config(changed, threads=2)

    changed = deepcopy(configs[5])
    changed["factors"]["redundancy_reference_names"].reverse()
    with pytest.raises(ValueError, match="invalid classic-factor config"):
        _validate_config(changed, threads=2)


def test_factor_coverage_and_rebalance_schedule_are_fail_closed() -> None:
    trade_date = dt.date(2025, 1, 6)
    rows = [
        {
            "symbol": f"{index:06d}.SH",
            "trade_date": trade_date,
            "exit_date_20": trade_date,
            "downside_beta": float(index) if index < 80 else None,
        }
        for index in range(100)
    ]
    panel = pl.DataFrame(rows)
    fold = ResearchFoldV1(
        fold=1,
        train_start=dt.date(2024, 1, 1),
        train_end=dt.date(2024, 6, 30),
        validation_start=dt.date(2024, 7, 1),
        validation_end=dt.date(2024, 12, 31),
        test_start=trade_date,
        test_end=trade_date,
    )
    daily, summary = evaluate_factor_coverage(
        panel,
        factors=("downside_beta",),
        start_date=trade_date,
        end_date=trade_date,
        folds=(fold,),
        rebalance_every_sessions=20,
        minimum_rebalance_symbols=80,
        minimum_median_coverage=0.80,
    )
    assert daily.select("valid_rows", "coverage", "scheduled_rebalance").row(0) == (
        80,
        0.8,
        True,
    )
    assert summary.get_column("coverage_passed").item() is True

    changed = panel.with_columns(
        pl.when(pl.col("symbol") == "000079.SH")
        .then(None)
        .otherwise(pl.col("downside_beta"))
        .alias("downside_beta")
    )
    _, failed = evaluate_factor_coverage(
        changed,
        factors=("downside_beta",),
        start_date=trade_date,
        end_date=trade_date,
        folds=(fold,),
        rebalance_every_sessions=20,
        minimum_rebalance_symbols=80,
        minimum_median_coverage=0.80,
    )
    assert failed.get_column("coverage_passed").item() is False

    targets = pl.DataFrame(
        {"factor": ["downside_beta"], "fold": [1], "as_of": [trade_date]}
    )
    aligned = evaluate_rebalance_schedule_alignment(
        panel,
        targets,
        factors=("downside_beta",),
        folds=(fold,),
        rebalance_every_sessions=20,
    )
    assert aligned.get_column("schedule_aligned").item() is True
    shifted = targets.with_columns(
        pl.lit(trade_date + dt.timedelta(days=1)).alias("as_of")
    )
    misaligned = evaluate_rebalance_schedule_alignment(
        panel,
        shifted,
        factors=("downside_beta",),
        folds=(fold,),
        rebalance_every_sessions=20,
    )
    assert misaligned.select(
        "missing_rebalance_dates", "unexpected_rebalance_dates", "schedule_aligned"
    ).row(0) == (1, 1, False)
    assert misaligned.get_column("missing_dates").to_list() == [[trade_date]]
    assert misaligned.get_column("unexpected_dates").to_list() == [
        [trade_date + dt.timedelta(days=1)]
    ]


def test_market_risk_gates_enforce_direction_redundancy_coverage_and_schedule() -> None:
    summary = pl.DataFrame(
        {
            "factor": ["downside_beta"],
            "mean_test_rank_ic": [0.02],
            "positive_test_folds": [3],
            "direction_consistent": [True],
            "one_x_chained_return": [0.03],
            "two_x_chained_return": [0.01],
            "research_status": ["RESEARCH_ONLY"],
        }
    )
    folds = pl.DataFrame(
        {
            "factor": ["downside_beta"] * 3,
            "cost_multiplier": [1.0] * 3,
            "direction": [-1] * 3,
        }
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["downside_beta"],
            "factor_b": ["control"],
            "median_abs_rank_corr": [0.79],
        }
    )
    coverage = pl.DataFrame(
        {
            "factor": ["downside_beta"],
            "dates": [100],
            "scheduled_rebalance_dates": [10],
            "minimum_rebalance_valid_rows": [100],
            "median_coverage": [0.80],
            "coverage_passed": [True],
        }
    )
    schedule = pl.DataFrame(
        {
            "factor": ["downside_beta"],
            "fold": [1],
            "schedule_aligned": [True],
        }
    )

    def apply(
        *,
        fold_metrics: pl.DataFrame = folds,
        redundancy_summary: pl.DataFrame = redundancy,
        coverage_summary: pl.DataFrame = coverage,
        schedule_alignment: pl.DataFrame = schedule,
    ) -> pl.DataFrame:
        return apply_market_risk_admission_gates(
            summary,
            fold_metrics=fold_metrics,
            redundancy_summary=redundancy_summary,
            coverage_summary=coverage_summary,
            schedule_alignment=schedule_alignment,
            expected_direction=-1,
            maximum_median_absolute_rank_correlation=0.80,
        )

    assert apply().get_column("research_status").item() == "RESEARCH_ONLY"
    assert (
        apply(
            redundancy_summary=redundancy.with_columns(
                pl.lit(0.80).alias("median_abs_rank_corr")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )
    assert (
        apply(
            fold_metrics=folds.with_columns(pl.lit(1).alias("direction"))
        ).get_column("research_status").item()
        == "REJECTED"
    )
    assert (
        apply(
            coverage_summary=coverage.with_columns(
                pl.lit(False).alias("coverage_passed")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )
    assert (
        apply(
            schedule_alignment=schedule.with_columns(
                pl.lit(False).alias("schedule_aligned")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )


def test_fourth_batch_gates_enforce_redundancy_coverage_and_schedule() -> None:
    summary = pl.DataFrame(
        {
            "factor": ["alpha158_resi20"],
            "mean_test_rank_ic": [0.02],
            "positive_test_folds": [3],
            "direction_consistent": [True],
            "one_x_chained_return": [0.03],
            "two_x_chained_return": [0.01],
            "research_status": ["RESEARCH_ONLY"],
            "max_median_abs_rank_corr": [0.79],
            "combination_eligible": [True],
        }
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["alpha158_resi20"],
            "factor_b": ["alpha158_beta20"],
            "median_abs_rank_corr": [0.79],
        }
    )
    coverage = pl.DataFrame(
        {
            "factor": ["alpha158_resi20"],
            "dates": [100],
            "scheduled_rebalance_dates": [10],
            "minimum_rebalance_valid_rows": [100],
            "median_coverage": [0.80],
            "coverage_passed": [True],
        }
    )
    schedule = pl.DataFrame(
        {
            "factor": ["alpha158_resi20"],
            "fold": [1],
            "schedule_aligned": [True],
        }
    )

    def apply(
        *,
        redundancy_summary: pl.DataFrame = redundancy,
        coverage_summary: pl.DataFrame = coverage,
        schedule_alignment: pl.DataFrame = schedule,
    ) -> pl.DataFrame:
        return apply_fourth_batch_admission_gates(
            summary,
            redundancy_summary=redundancy_summary,
            coverage_summary=coverage_summary,
            schedule_alignment=schedule_alignment,
            maximum_median_absolute_rank_correlation=0.80,
        )

    assert apply().get_column("research_status").item() == "RESEARCH_ONLY"
    assert (
        apply(
            redundancy_summary=redundancy.with_columns(
                pl.lit(0.80).alias("median_abs_rank_corr")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )
    assert (
        apply(
            coverage_summary=coverage.with_columns(
                pl.lit(False).alias("coverage_passed")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )
    assert (
        apply(
            schedule_alignment=schedule.with_columns(
                pl.lit(False).alias("schedule_aligned")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )


def _monotonicity_fixture(
    *,
    fold_values: tuple[tuple[float, ...], ...] = (
        (5.0, 4.0, 3.0, 2.0, 1.0),
        (4.0, 3.0, 2.0, 1.0, 0.0),
        (1.0, 2.0, 3.0, 2.0, 1.0),
    ),
) -> tuple[pl.DataFrame, pl.DataFrame, tuple[ResearchFoldV1, ...]]:
    factor = "max_daily_return_20"
    folds: list[ResearchFoldV1] = []
    panel_rows: list[dict[str, object]] = []
    group_rows: list[dict[str, object]] = []
    for fold_number, values in enumerate(fold_values, 1):
        test_start = dt.date(2020 + fold_number, 1, 1)
        test_dates = (test_start, test_start + dt.timedelta(days=1))
        folds.append(
            ResearchFoldV1(
                fold=fold_number,
                train_start=dt.date(2019, 1, 1),
                train_end=dt.date(2019, 6, 30),
                validation_start=dt.date(2019, 7, 1),
                validation_end=dt.date(2019, 12, 31),
                test_start=test_start,
                test_end=test_dates[-1],
            )
        )
        for trade_date in test_dates:
            panel_rows.append(
                {
                    "trade_date": trade_date,
                    "exit_date_20": trade_date,
                }
            )
            for group, value in enumerate(values, 1):
                group_rows.append(
                    {
                        "factor": factor,
                        "fold": fold_number,
                        "period": "test",
                        "horizon": 20,
                        "direction": -1,
                        "trade_date": trade_date,
                        "group": group,
                        "n_symbols": 20,
                        "mean_return": value,
                        "factor_count": 20,
                        "paired_count": 20,
                        "coverage_numerator": 20,
                        "coverage_denominator": 20,
                        "coverage_status": "PASS",
                    }
                )
    return pl.DataFrame(group_rows), pl.DataFrame(panel_rows), tuple(folds)


def test_primary_group_monotonicity_is_date_equal_and_fail_closed() -> None:
    group_returns, panel, folds = _monotonicity_fixture()
    result = evaluate_primary_group_monotonicity(
        group_returns,
        panel=panel,
        factor="max_daily_return_20",
        folds=folds,
        minimum_symbols=100,
        expected_direction=-1,
    )
    assert result.select("fold", "monotonicity_passed").rows() == [
        (0, True),
        (1, True),
        (2, True),
        (3, False),
    ]
    assert result.filter(pl.col("fold") == 0).select(
        "group_1_mean_return",
        "group_2_mean_return",
        "group_3_mean_return",
        "group_4_mean_return",
        "group_5_mean_return",
    ).row(0) == (10.0 / 3.0, 3.0, 8.0 / 3.0, 5.0 / 3.0, 2.0 / 3.0)

    diagnostic_drift = pl.concat(
        [
            group_returns,
            group_returns.with_columns(
                pl.lit(1).cast(pl.Int64).alias("horizon"),
                pl.lit(float("inf")).alias("mean_return"),
                pl.lit("FAIL").alias("coverage_status"),
            ),
            group_returns.with_columns(
                pl.lit(5).cast(pl.Int64).alias("horizon"),
                pl.lit(float("inf")).alias("mean_return"),
                pl.lit("FAIL").alias("coverage_status"),
            ),
        ]
    )
    assert evaluate_primary_group_monotonicity(
        diagnostic_drift,
        panel=panel,
        factor="max_daily_return_20",
        folds=folds,
        minimum_symbols=100,
        expected_direction=-1,
    ).filter(pl.col("fold") == 0).get_column("monotonicity_passed").item() is True

    missing_group = group_returns.filter(
        ~((pl.col("fold") == 1) & (pl.col("group") == 5))
    )
    assert evaluate_primary_group_monotonicity(
        missing_group,
        panel=panel,
        factor="max_daily_return_20",
        folds=folds,
        minimum_symbols=100,
        expected_direction=-1,
    ).filter(pl.col("fold") == 1).get_column("monotonicity_passed").item() is False

    duplicate_group = pl.concat([group_returns, group_returns.head(1)])
    assert evaluate_primary_group_monotonicity(
        duplicate_group,
        panel=panel,
        factor="max_daily_return_20",
        folds=folds,
        minimum_symbols=100,
        expected_direction=-1,
    ).filter(pl.col("fold") == 1).get_column("monotonicity_passed").item() is False

    failed_coverage = group_returns.with_columns(
        pl.when((pl.col("fold") == 1) & (pl.col("group") == 1))
        .then(pl.lit("FAIL"))
        .otherwise(pl.col("coverage_status"))
        .alias("coverage_status")
    )
    assert evaluate_primary_group_monotonicity(
        failed_coverage,
        panel=panel,
        factor="max_daily_return_20",
        folds=folds,
        minimum_symbols=100,
        expected_direction=-1,
    ).filter(pl.col("fold") == 1).get_column("monotonicity_passed").item() is False


def test_fifth_batch_gates_enforce_fixed_direction_and_all_fail_closed_edges() -> None:
    factor = "max_daily_return_20"
    summary = pl.DataFrame(
        {
            "factor": [factor],
            "mean_test_rank_ic": [0.02],
            "positive_test_folds": [3],
            "direction_consistent": [True],
            "one_x_chained_return": [0.03],
            "two_x_chained_return": [0.01],
            "research_status": ["RESEARCH_ONLY"],
            "max_median_abs_rank_corr": [0.79],
            "combination_eligible": [True],
        }
    )
    folds = pl.DataFrame(
        {
            "factor": [factor] * 3,
            "fold": [1, 2, 3],
            "cost_multiplier": [1.0] * 3,
            "direction": [-1] * 3,
            "validation_observed_direction": [-1] * 3,
        }
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": [factor],
            "factor_b": ["alpha158_std20"],
            "median_abs_rank_corr": [0.79],
        }
    )
    coverage = pl.DataFrame(
        {
            "factor": [factor],
            "dates": [100],
            "scheduled_rebalance_dates": [10],
            "minimum_rebalance_valid_rows": [100],
            "median_coverage": [0.80],
            "coverage_passed": [True],
        }
    )
    schedule = pl.DataFrame(
        {
            "factor": [factor],
            "fold": [1],
            "schedule_aligned": [True],
        }
    )
    monotonicity = pl.DataFrame(
        {
            "factor": [factor] * 4,
            "fold": [0, 1, 2, 3],
            "period": ["test"] * 4,
            "horizon": [20] * 4,
            "expected_direction": [-1] * 4,
            "monotonicity_passed": [True, True, True, False],
        }
    )

    def apply(
        *,
        fold_metrics: pl.DataFrame = folds,
        redundancy_summary: pl.DataFrame = redundancy,
        coverage_summary: pl.DataFrame = coverage,
        schedule_alignment: pl.DataFrame = schedule,
        primary_group_monotonicity: pl.DataFrame = monotonicity,
    ) -> pl.DataFrame:
        return apply_fifth_batch_admission_gates(
            summary,
            fold_metrics=fold_metrics,
            redundancy_summary=redundancy_summary,
            coverage_summary=coverage_summary,
            schedule_alignment=schedule_alignment,
            expected_direction=-1,
            maximum_median_absolute_rank_correlation=0.80,
            primary_group_monotonicity=primary_group_monotonicity,
        )

    assert apply().get_column("research_status").item() == "RESEARCH_ONLY"
    assert (
        apply(
            primary_group_monotonicity=monotonicity.with_columns(
                pl.when(pl.col("fold") == 2)
                .then(pl.lit(False))
                .otherwise(pl.col("monotonicity_passed"))
                .alias("monotonicity_passed")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )
    assert (
        apply(
            primary_group_monotonicity=monotonicity.with_columns(
                pl.when(pl.col("fold") == 0)
                .then(pl.lit(False))
                .otherwise(pl.col("monotonicity_passed"))
                .alias("monotonicity_passed")
            )
        )
        .get_column("research_status")
        .item()
        == "REJECTED"
    )
    assert (
        apply(
            fold_metrics=folds.with_columns(
                pl.when(pl.col("fold") == 2)
                .then(1)
                .otherwise(pl.col("validation_observed_direction"))
                .alias("validation_observed_direction")
            )
        ).get_column("research_status").item()
        == "REJECTED"
    )
    assert (
        apply(
            fold_metrics=folds.with_columns(pl.lit(1).alias("direction"))
        ).get_column("research_status").item()
        == "REJECTED"
    )
    assert (
        apply(
            redundancy_summary=redundancy.with_columns(
                pl.lit(0.80).alias("median_abs_rank_corr")
            )
        ).get_column("research_status").item()
        == "REJECTED"
    )
    assert (
        apply(
            coverage_summary=coverage.with_columns(
                pl.lit(False).alias("coverage_passed")
            )
        ).get_column("research_status").item()
        == "REJECTED"
    )
    assert (
        apply(
            schedule_alignment=schedule.with_columns(
                pl.lit(False).alias("schedule_aligned")
            )
        ).get_column("research_status").item()
        == "REJECTED"
    )
