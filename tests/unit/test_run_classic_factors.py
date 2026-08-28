from __future__ import annotations

import datetime as dt
import hashlib
import json
import tomllib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

import quant.research.run_classic_factors as classic_runner
from quant.research.lightweight_run import ResearchFoldV1
from quant.research.lightweight_run import ResearchInputDigestV1
from quant.research.run_classic_factors import (
    _aggregate_redundancy_by_factor,
    _build_input_digests,
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
_FROZEN_MAX_R15_CONFIG_SHA256 = (
    "baa384bbdcc1406fa53b6b7c689087ac03eeebf99db852f37ba9d03e40ca2c6e"
)


def _cost_payload() -> bytes:
    return (PROJECT_ROOT / "configs/research/m3_qlib_example.toml").read_bytes().replace(
        b"\r\n", b"\n"
    )


def _canonical_main_config_payload(payload: bytes) -> bytes:
    return payload.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode(
        "utf-8"
    )


def _with_eols(payload: bytes, eols: tuple[bytes, ...]) -> bytes:
    lines = payload.split(b"\n")
    return b"".join(
        line + (eols[index % len(eols)] if index < len(lines) - 1 else b"")
        for index, line in enumerate(lines)
    )


def test_redundancy_aggregation_is_symmetric_and_preserves_summary_order() -> None:
    summary = pl.DataFrame(
        {
            "factor": ["candidate_b", "candidate_a"],
            "research_status": ["RESEARCH_ONLY", "RESEARCH_ONLY"],
        }
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["reference", "candidate_a", "candidate_b"],
            "factor_b": ["candidate_a", "candidate_b", "reference"],
            "median_abs_rank_corr": [0.83, 0.79, 0.42],
        }
    )
    expected = [
        {"factor": "candidate_b", "max_median_abs_rank_corr": 0.79},
        {"factor": "candidate_a", "max_median_abs_rank_corr": 0.83},
    ]

    assert _aggregate_redundancy_by_factor(summary, redundancy).rows(named=True) == expected

    swapped_and_reordered = pl.DataFrame(
        {
            "factor_a": ["candidate_b", "reference", "candidate_a"],
            "factor_b": ["reference", "candidate_a", "candidate_b"],
            "median_abs_rank_corr": [0.42, 0.83, 0.79],
        }
    )
    assert (
        _aggregate_redundancy_by_factor(summary, swapped_and_reordered).rows(named=True)
        == expected
    )


def test_reference_only_pairs_do_not_create_summary_rows() -> None:
    summary = pl.DataFrame(
        {"factor": ["candidate"], "research_status": ["RESEARCH_ONLY"]}
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["candidate", "reference"],
            "factor_b": ["reference", "control"],
            "median_abs_rank_corr": [0.42, 0.91],
        }
    )

    result = _aggregate_redundancy_by_factor(summary, redundancy)

    assert result.rows(named=True) == [
        {"factor": "candidate", "max_median_abs_rank_corr": 0.42}
    ]


def test_candidate_self_pair_is_rejected_before_aggregation() -> None:
    summary = pl.DataFrame(
        {"factor": ["candidate"], "research_status": ["RESEARCH_ONLY"]}
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["candidate"],
            "factor_b": ["candidate"],
            "median_abs_rank_corr": [0.10],
        }
    )

    with pytest.raises(ValueError, match="not distinct"):
        _aggregate_redundancy_by_factor(summary, redundancy)


def test_candidate_without_an_incident_is_rejected() -> None:
    summary = pl.DataFrame(
        {
            "factor": ["candidate_a", "candidate_b"],
            "research_status": ["RESEARCH_ONLY", "RESEARCH_ONLY"],
        }
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["candidate_a"],
            "factor_b": ["reference"],
            "median_abs_rank_corr": [0.42],
        }
    )

    aggregated = _aggregate_redundancy_by_factor(summary, redundancy)

    assert aggregated.rows(named=True) == [
        {"factor": "candidate_a", "max_median_abs_rank_corr": 0.42},
        {"factor": "candidate_b", "max_median_abs_rank_corr": None},
    ]

    gated = apply_fourth_batch_admission_gates(
        summary,
        redundancy_summary=redundancy,
        coverage_summary=pl.DataFrame(
            {"factor": ["candidate_a", "candidate_b"], "coverage_passed": [True, True]}
        ),
        schedule_alignment=pl.DataFrame(
            {
                "factor": ["candidate_a", "candidate_b"],
                "schedule_aligned": [True, True],
            }
        ),
        maximum_median_absolute_rank_correlation=0.80,
    )
    assert gated.select("factor", "research_status").rows() == [
        ("candidate_a", "RESEARCH_ONLY"),
        ("candidate_b", "REJECTED"),
    ]


def test_duplicate_summary_factor_is_rejected_before_aggregation() -> None:
    summary = pl.DataFrame(
        {
            "factor": ["candidate", "candidate"],
            "research_status": ["RESEARCH_ONLY", "RESEARCH_ONLY"],
        }
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["candidate"],
            "factor_b": ["reference"],
            "median_abs_rank_corr": [0.42],
        }
    )

    with pytest.raises(ValueError, match="summary factors are not unique"):
        _aggregate_redundancy_by_factor(summary, redundancy)


@pytest.mark.parametrize(
    ("factor_value", "status_value"),
    (
        (None, "RESEARCH_ONLY"),
        (1, "RESEARCH_ONLY"),
        ("", "RESEARCH_ONLY"),
        ("candidate", None),
        ("candidate", False),
        ("candidate", 1),
        ("candidate", ""),
        ("candidate", "HOLD"),
    ),
    ids=(
        "null-factor",
        "non-string-factor",
        "empty-factor",
        "null-status",
        "non-string-status-bool",
        "non-string-status-int",
        "empty-status",
        "unexpected-status",
    ),
)
def test_summary_factor_and_status_contract_is_strict(
    factor_value: object, status_value: object
) -> None:
    summary = pl.DataFrame(
        {"factor": [factor_value], "research_status": [status_value]}
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["candidate"],
            "factor_b": ["reference"],
            "median_abs_rank_corr": [0.42],
        }
    )

    with pytest.raises(ValueError, match="summary (string|status) contract"):
        _aggregate_redundancy_by_factor(summary, redundancy)


def test_redundancy_required_fields_are_rejected() -> None:
    summary = pl.DataFrame(
        {"factor": ["candidate"], "research_status": ["RESEARCH_ONLY"]}
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["candidate"],
            "factor_b": ["reference"],
            "median_abs_rank_corr": [0.42],
        }
    )

    with pytest.raises(ValueError, match="invalid classic redundancy aggregation"):
        _aggregate_redundancy_by_factor(
            summary.drop("factor"),
            redundancy,
        )
    with pytest.raises(ValueError, match="invalid classic redundancy aggregation"):
        _aggregate_redundancy_by_factor(
            summary,
            redundancy.drop("median_abs_rank_corr"),
        )


@pytest.mark.parametrize("bad_endpoint", (None, 1, ""), ids=("null", "non-string", "empty"))
def test_redundancy_endpoints_must_be_non_empty_strings(bad_endpoint: object) -> None:
    summary = pl.DataFrame(
        {"factor": ["candidate"], "research_status": ["RESEARCH_ONLY"]}
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": [bad_endpoint],
            "factor_b": ["reference"],
            "median_abs_rank_corr": [0.42],
        }
    )

    with pytest.raises(ValueError, match="endpoint contract"):
        _aggregate_redundancy_by_factor(summary, redundancy)


@pytest.mark.parametrize(
    "bad_correlation",
    (None, True, float("nan"), float("inf"), float("-inf"), "0.42"),
    ids=("null", "bool", "nan", "positive-infinity", "negative-infinity", "string"),
)
def test_redundancy_correlation_must_be_finite_numeric_not_bool(
    bad_correlation: object,
) -> None:
    summary = pl.DataFrame(
        {"factor": ["candidate"], "research_status": ["RESEARCH_ONLY"]}
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["candidate"],
            "factor_b": ["reference"],
            "median_abs_rank_corr": [bad_correlation],
        }
    )

    with pytest.raises(ValueError, match="correlation contract"):
        _aggregate_redundancy_by_factor(summary, redundancy)


@pytest.mark.parametrize(
    "bad_correlation",
    (-0.01, 1.01),
    ids=("negative", "greater-than-one"),
)
def test_redundancy_correlation_range_fails_closed_before_admission(
    bad_correlation: float,
) -> None:
    summary = pl.DataFrame(
        {"factor": ["candidate"], "research_status": ["RESEARCH_ONLY"]}
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["candidate"],
            "factor_b": ["reference"],
            "median_abs_rank_corr": [bad_correlation],
        }
    )

    with pytest.raises(ValueError, match="between 0 and 1"):
        apply_fourth_batch_admission_gates(
            summary,
            redundancy_summary=redundancy,
            coverage_summary=pl.DataFrame(
                {"factor": ["candidate"], "coverage_passed": [True]}
            ),
            schedule_alignment=pl.DataFrame(
                {"factor": ["candidate"], "schedule_aligned": [True]}
            ),
            maximum_median_absolute_rank_correlation=0.80,
        )


@pytest.mark.parametrize(
    "pairs",
    (
        (("candidate", "reference"), ("candidate", "reference")),
        (("candidate", "reference"), ("reference", "candidate")),
    ),
    ids=("exact-duplicate", "reverse-duplicate"),
)
def test_duplicate_or_reverse_duplicate_pairs_are_rejected(
    pairs: tuple[tuple[str, str], tuple[str, str]],
) -> None:
    summary = pl.DataFrame(
        {"factor": ["candidate"], "research_status": ["RESEARCH_ONLY"]}
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": [pair[0] for pair in pairs],
            "factor_b": [pair[1] for pair in pairs],
            "median_abs_rank_corr": [0.42, 0.43],
        }
    )

    with pytest.raises(ValueError, match="pairs are not unique"):
        _aggregate_redundancy_by_factor(summary, redundancy)


def test_candidate_candidate_pair_constrains_both_sides_and_rejected_stays_rejected() -> None:
    summary = pl.DataFrame(
        {
            "factor": ["candidate_b", "candidate_a"],
            "research_status": ["RESEARCH_ONLY", "RESEARCH_ONLY"],
        }
    )
    redundancy = pl.DataFrame(
        {
            "factor_a": ["candidate_a"],
            "factor_b": ["candidate_b"],
            "median_abs_rank_corr": [0.80],
        }
    )
    coverage = pl.DataFrame(
        {
            "factor": ["candidate_b", "candidate_a"],
            "coverage_passed": [True, True],
        }
    )
    schedule = pl.DataFrame(
        {
            "factor": ["candidate_b", "candidate_a"],
            "schedule_aligned": [True, True],
        }
    )

    rejected = apply_fourth_batch_admission_gates(
        summary,
        redundancy_summary=redundancy,
        coverage_summary=coverage,
        schedule_alignment=schedule,
        maximum_median_absolute_rank_correlation=0.80,
    )
    assert rejected.select("factor", "research_status").rows() == [
        ("candidate_a", "REJECTED"),
        ("candidate_b", "REJECTED"),
    ]
    assert rejected.select("factor", "max_median_abs_rank_corr").rows() == [
        ("candidate_a", 0.80),
        ("candidate_b", 0.80),
    ]

    below_threshold = redundancy.with_columns(
        pl.lit(0.79).alias("median_abs_rank_corr")
    )
    passed = apply_fourth_batch_admission_gates(
        summary,
        redundancy_summary=below_threshold,
        coverage_summary=coverage,
        schedule_alignment=schedule,
        maximum_median_absolute_rank_correlation=0.80,
    )
    assert passed.get_column("research_status").to_list() == [
        "RESEARCH_ONLY",
        "RESEARCH_ONLY",
    ]

    already_rejected = summary.with_columns(pl.lit("REJECTED").alias("research_status"))
    remains_rejected = apply_fourth_batch_admission_gates(
        already_rejected,
        redundancy_summary=below_threshold,
        coverage_summary=coverage,
        schedule_alignment=schedule,
        maximum_median_absolute_rank_correlation=0.80,
    )
    assert remains_rejected.get_column("research_status").to_list() == [
        "REJECTED",
        "REJECTED",
    ]


def test_all_four_classic_redundancy_call_sites_use_one_private_helper() -> None:
    source = (PROJECT_ROOT / "src/quant/research/run_classic_factors.py").read_text(
        encoding="utf-8"
    )

    assert source.count("_aggregate_redundancy_by_factor(") == 5
    assert 'group_by("factor_a")' not in source


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


def test_classic_input_identity_adds_cost_only_for_fifth_batch() -> None:
    market_input = ResearchInputDigestV1(
        name="tushare-stock-bars",
        rows=1,
        min_date=dt.date(2019, 1, 1),
        max_date=dt.date(2019, 1, 1),
        content_sha256="0" * 64,
    )
    market_inputs = (market_input,)
    periods, semantic_sha256 = _cost_schedule_binding_from_payload(_cost_payload())

    assert _build_input_digests(
        market_inputs,
        fifth_batch=False,
        cost_periods=None,
        cost_semantic_sha256=None,
    ) == market_inputs
    assert _build_input_digests(
        market_inputs,
        fifth_batch=True,
        cost_periods=periods,
        cost_semantic_sha256=semantic_sha256,
    ) == (_cost_schedule_input_digest(periods, semantic_sha256), *market_inputs)
    assert _build_input_digests(
        market_inputs,
        fifth_batch=False,
        sixth_batch=True,
        cost_periods=periods,
        cost_semantic_sha256=semantic_sha256,
    ) == (_cost_schedule_input_digest(periods, semantic_sha256), *market_inputs)


def _frozen_max_config_payload() -> bytes:
    payload = (
        PROJECT_ROOT / "configs/research/m2_classic_daily_factors_fifth_batch.toml"
    ).read_bytes()
    assert (
        hashlib.sha256(_canonical_main_config_payload(payload)).hexdigest()
        == _FROZEN_MAX_R15_CONFIG_SHA256
    )
    return payload


def _classic_project(
    tmp_path: Path,
    *,
    config_payload: bytes,
    config_name: str = "m2_classic_daily_factors_fifth_batch.toml",
) -> tuple[Path, Path, Path, Path]:
    project_root = tmp_path / "project"
    config_path = project_root / "configs/research" / config_name
    cost_path = project_root / "configs/research/m3_qlib_example.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes(config_payload)
    cost_path.write_bytes((PROJECT_ROOT / "configs/research/m3_qlib_example.toml").read_bytes())
    data_root = project_root / "data"
    data_root.mkdir()
    return project_root, config_path, cost_path, data_root


def _classic_main_args(
    project_root: Path,
    data_root: Path,
    *,
    config_name: str = "m2_classic_daily_factors_fifth_batch.toml",
) -> list[str]:
    return [
        "--config",
        f"configs/research/{config_name}",
        "--data-root",
        str(data_root),
        "--artifact-root",
        "artifacts-test",
        "--project-root",
        str(project_root),
        "--threads",
        "2",
    ]


def _run_fifth_main_to_publish(
    project_root: Path,
    data_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    factor = classic_runner.FIFTH_BATCH_FACTOR_NAMES[0]
    trade_date = dt.date(2020, 1, 2)
    captured_runs: list[object] = []

    def factor_frame(names: tuple[str, ...]) -> pl.DataFrame:
        values: dict[str, object] = {
            "symbol": ["000001.SZ"],
            "trade_date": [trade_date],
        }
        values.update({name: [0.0] for name in names})
        return pl.DataFrame(values)

    def snapshot_verifier(*, data_root: Path, snapshot_id: str) -> object:
        del data_root
        return SimpleNamespace(
            snapshot_id=snapshot_id,
            manifest_sha256="a" * 64,
            stock_rows=1,
            fund_rows=0,
        )

    def stock_reader(*_: object, **__: object) -> pl.DataFrame:
        return pl.DataFrame({"trade_date": [trade_date]})

    def labels(**_: object) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "trade_date": [trade_date],
                "history_rows": [120],
                "liquidity_20": [20_000_000.0],
            }
        )

    def evaluate(**_: object) -> dict[str, pl.DataFrame]:
        frame = pl.DataFrame({"value": [1]})
        return {
            "daily_ic": frame,
            "group_returns": frame,
            "fold_metrics": frame,
            "targets": frame,
            "portfolio_nav": frame,
        }

    def summarize(
        _metrics: pl.DataFrame,
        *,
        factors: tuple[str, ...],
        admission: object,
    ) -> pl.DataFrame:
        del admission
        return pl.DataFrame(
            {
                "factor": list(factors),
                "mean_test_rank_ic": [0.0] * len(factors),
                "positive_test_folds": [0] * len(factors),
                "direction_consistent": [True] * len(factors),
                "one_x_chained_return": [0.0] * len(factors),
                "two_x_chained_return": [0.0] * len(factors),
                "research_status": ["RESEARCH_ONLY"] * len(factors),
            }
        )

    def publish(
        *, artifact_root: Path, run: object, output_payloads: dict[str, bytes]
    ) -> tuple[Path, object, bool]:
        del output_payloads
        captured_runs.append(run)
        return artifact_root, run, False

    monkeypatch.setattr(classic_runner, "verify_tushare_bulk_clean_snapshot", snapshot_verifier)
    monkeypatch.setattr(classic_runner, "read_tushare_bulk_clean_stock_bars", stock_reader)
    monkeypatch.setattr(
        classic_runner,
        "select_frozen_liquid_universe",
        lambda *_args, **_kwargs: ("000001.SZ",),
    )
    monkeypatch.setattr(
        classic_runner,
        "compute_classic_daily_factors",
        lambda *_args, **_kwargs: factor_frame(classic_runner.CLASSIC_FACTOR_NAMES),
    )
    monkeypatch.setattr(
        classic_runner,
        "compute_second_batch_daily_factors",
        lambda *_args, **_kwargs: factor_frame(classic_runner.SECOND_BATCH_FACTOR_NAMES),
    )
    monkeypatch.setattr(
        classic_runner,
        "compute_third_batch_daily_factors",
        lambda *_args, **_kwargs: factor_frame(classic_runner.THIRD_BATCH_FACTOR_NAMES),
    )
    monkeypatch.setattr(
        classic_runner,
        "compute_fourth_batch_daily_factors",
        lambda *_args, **_kwargs: factor_frame(classic_runner.FOURTH_BATCH_FACTOR_NAMES),
    )
    monkeypatch.setattr(
        classic_runner,
        "compute_fifth_batch_daily_factors",
        lambda *_args, **_kwargs: factor_frame(classic_runner.FIFTH_BATCH_FACTOR_NAMES),
    )
    monkeypatch.setattr(classic_runner, "build_next_open_factor_labels", labels)
    monkeypatch.setattr(
        classic_runner,
        "_cost_schedule_binding",
        lambda *_args, **_kwargs: ((), _COST_SEMANTIC_SHA256),
    )
    monkeypatch.setattr(classic_runner, "evaluate_walk_forward", evaluate)
    monkeypatch.setattr(classic_runner, "summarize_factors", summarize)
    monkeypatch.setattr(
        classic_runner,
        "evaluate_factor_redundancy",
        lambda *_args, **_kwargs: (
            pl.DataFrame({"value": [1]}),
            pl.DataFrame(
                {
                    "factor_a": [factor],
                    "factor_b": ["alpha158_std20"],
                    "median_abs_rank_corr": [0.79],
                }
            ),
        ),
    )
    monkeypatch.setattr(
        classic_runner,
        "evaluate_factor_coverage",
        lambda *_args, **_kwargs: (
            pl.DataFrame({"value": [1]}),
            pl.DataFrame({"factor": [factor], "coverage_passed": [True]}),
        ),
    )
    monkeypatch.setattr(
        classic_runner,
        "evaluate_rebalance_schedule_alignment",
        lambda *_args, **_kwargs: pl.DataFrame(
            {"factor": [factor], "fold": [1], "schedule_aligned": [True]}
        ),
    )
    monkeypatch.setattr(
        classic_runner,
        "evaluate_primary_group_monotonicity",
        lambda *_args, **_kwargs: pl.DataFrame(
            {
                "factor": [factor],
                "fold": [0],
                "period": ["test"],
                "horizon": [20],
                "expected_direction": [-1],
                "monotonicity_passed": [True],
            }
        ),
    )
    monkeypatch.setattr(
        classic_runner,
        "apply_fifth_batch_admission_gates",
        lambda summary, **_kwargs: summary.with_columns(
            pl.lit(True).alias("coverage_passed"),
            pl.lit(True).alias("primary_monotonicity_passed"),
        ),
    )
    monkeypatch.setattr(classic_runner, "compute_code_sha256", lambda **_kwargs: "b" * 64)
    monkeypatch.setattr(classic_runner, "publish_lightweight_research_run", publish)

    assert main(_classic_main_args(project_root, data_root)) == 0
    assert len(captured_runs) == 1
    return captured_runs[0]


def test_sixth_batch_main_binds_raw_config_and_cost_before_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_payload = (
        PROJECT_ROOT
        / "configs/research/m2_classic_daily_factors_sixth_batch.toml"
    ).read_bytes()
    project_root, config_path, _, data_root = _classic_project(
        tmp_path,
        config_payload=config_payload,
        config_name="m2_classic_daily_factors_sixth_batch.toml",
    )
    factor_names = classic_runner.SIXTH_BATCH_FACTOR_NAMES
    trade_date = dt.date(2020, 1, 2)
    events: list[str] = []
    captured_runs: list[object] = []
    captured_output_payloads: list[dict[str, bytes]] = []

    def factor_frame(names: tuple[str, ...]) -> pl.DataFrame:
        values: dict[str, object] = {
            "symbol": ["000001.SZ"],
            "trade_date": [trade_date],
        }
        values.update({name: [0.0] for name in names})
        return pl.DataFrame(values)

    def snapshot_verifier(*, data_root: Path, snapshot_id: str) -> object:
        del data_root
        events.append("snapshot")
        assert snapshot_id == "b79a7b5e66dee0ae439c030078414157ca6c1f3b6ce7fbe5e36ff3910c1089d2"
        return SimpleNamespace(
            snapshot_id=snapshot_id,
            manifest_sha256="a" * 64,
            stock_rows=1,
            fund_rows=0,
        )

    def stock_reader(*_: object, **__: object) -> pl.DataFrame:
        return pl.DataFrame({"trade_date": [trade_date]})

    def sixth_compute(*_: object, **__: object) -> pl.DataFrame:
        events.append("sixth-factor")
        return factor_frame(factor_names)

    def labels(**_: object) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "trade_date": [trade_date],
                "history_rows": [120],
                "liquidity_20": [20_000_000.0],
            }
        )

    def evaluate(**_: object) -> dict[str, pl.DataFrame]:
        frame = pl.DataFrame({"value": [1]})
        return {
            "daily_ic": frame,
            "group_returns": frame,
            "fold_metrics": frame,
            "targets": frame,
            "portfolio_nav": frame,
        }

    def summarize(
        _metrics: pl.DataFrame,
        *,
        factors: tuple[str, ...],
        admission: object,
    ) -> pl.DataFrame:
        del admission
        return pl.DataFrame(
            {
                "factor": list(factors),
                "mean_test_rank_ic": [0.02] * len(factors),
                "positive_test_folds": [3] * len(factors),
                "direction_consistent": [True] * len(factors),
                "one_x_chained_return": [0.03] * len(factors),
                "two_x_chained_return": [0.01] * len(factors),
                "research_status": ["RESEARCH_ONLY"] * len(factors),
            }
        )

    def publish(
        *, artifact_root: Path, run: object, output_payloads: dict[str, bytes]
    ) -> tuple[Path, object, bool]:
        captured_runs.append(run)
        captured_output_payloads.append(output_payloads)
        return artifact_root, run, False

    def cost_binding(*_: object, **__: object) -> tuple[tuple[object, ...], str]:
        events.append("cost")
        return (), _COST_SEMANTIC_SHA256

    monkeypatch.setattr(classic_runner, "_cost_schedule_binding", cost_binding)
    monkeypatch.setattr(classic_runner, "verify_tushare_bulk_clean_snapshot", snapshot_verifier)
    monkeypatch.setattr(classic_runner, "read_tushare_bulk_clean_stock_bars", stock_reader)
    monkeypatch.setattr(
        classic_runner,
        "select_frozen_liquid_universe",
        lambda *_args, **_kwargs: ("000001.SZ",),
    )
    monkeypatch.setattr(
        classic_runner,
        "compute_classic_daily_factors",
        lambda *_args, **_kwargs: factor_frame(classic_runner.CLASSIC_FACTOR_NAMES),
    )
    monkeypatch.setattr(
        classic_runner,
        "compute_second_batch_daily_factors",
        lambda *_args, **_kwargs: factor_frame(classic_runner.SECOND_BATCH_FACTOR_NAMES),
    )
    monkeypatch.setattr(
        classic_runner,
        "compute_third_batch_daily_factors",
        lambda *_args, **_kwargs: factor_frame(classic_runner.THIRD_BATCH_FACTOR_NAMES),
    )
    monkeypatch.setattr(
        classic_runner,
        "compute_fourth_batch_daily_factors",
        lambda *_args, **_kwargs: factor_frame(classic_runner.FOURTH_BATCH_FACTOR_NAMES),
    )
    monkeypatch.setattr(
        classic_runner,
        "compute_fifth_batch_daily_factors",
        lambda *_args, **_kwargs: factor_frame(classic_runner.FIFTH_BATCH_FACTOR_NAMES),
    )
    monkeypatch.setattr(classic_runner, "compute_sixth_batch_daily_factors", sixth_compute)
    monkeypatch.setattr(classic_runner, "build_next_open_factor_labels", labels)
    monkeypatch.setattr(classic_runner, "evaluate_walk_forward", evaluate)
    monkeypatch.setattr(classic_runner, "summarize_factors", summarize)
    monkeypatch.setattr(
        classic_runner,
        "evaluate_factor_redundancy",
        lambda *_args, **_kwargs: (
            pl.DataFrame({"value": [1]}),
            pl.DataFrame(
                {
                    "factor_a": list(factor_names),
                    "factor_b": ["alpha158_std20"] * len(factor_names),
                    "median_abs_rank_corr": [0.79] * len(factor_names),
                }
            ),
        ),
    )
    monkeypatch.setattr(
        classic_runner,
        "evaluate_factor_coverage",
        lambda *_args, **_kwargs: (
            pl.DataFrame({"value": [1]}),
            pl.DataFrame(
                {"factor": list(factor_names), "coverage_passed": [True] * len(factor_names)}
            ),
        ),
    )
    monkeypatch.setattr(
        classic_runner,
        "evaluate_rebalance_schedule_alignment",
        lambda *_args, **_kwargs: pl.DataFrame(
            {
                "factor": list(factor_names),
                "fold": [1] * len(factor_names),
                "schedule_aligned": [True] * len(factor_names),
            }
        ),
    )
    monkeypatch.setattr(classic_runner, "compute_code_sha256", lambda **_kwargs: "b" * 64)
    monkeypatch.setattr(classic_runner, "publish_lightweight_research_run", publish)

    assert main(
        _classic_main_args(
            project_root,
            data_root,
            config_name="m2_classic_daily_factors_sixth_batch.toml",
        )
    ) == 0
    assert events[:2] == ["cost", "snapshot"]
    assert events.count("sixth-factor") == 1
    assert len(captured_runs) == 1
    assert len(captured_output_payloads) == 1
    assert list(captured_output_payloads[0]) == [
        "daily_ic.parquet",
        "factor_catalog.json",
        "factor_summary.parquet",
        "fold_metrics.parquet",
        "group_returns.parquet",
        "portfolio_nav.parquet",
        "report.json",
        "targets.parquet",
        "redundancy_daily.parquet",
        "redundancy_summary.parquet",
        "factor_coverage_daily.parquet",
        "factor_coverage_summary.parquet",
        "rebalance_schedule_alignment.parquet",
    ]
    run = captured_runs[0]
    assert run.config_sha256 == hashlib.sha256(config_path.read_bytes()).hexdigest()  # type: ignore[attr-defined]
    assert run.candidate_symbols == ("000001.SZ",)  # type: ignore[attr-defined]
    assert tuple(item.name for item in run.inputs) == (  # type: ignore[attr-defined]
        "a-share-cost-schedule",
        "tushare-stock-bars",
    )
    assert not (project_root / "artifacts-test").exists()


@pytest.mark.parametrize(
    ("needle", "replacement"),
    (
        (
            b"correlation_window_sessions = 10",
            b"correlation_window_sessions = 11",
        ),
        (
            b"trial_delta = 3",
            b"trial_delta = 2",
        ),
        (
            b'names = ["alpha101_006", "alpha101_012", "alpha101_041"]',
            b'names = ["alpha101_012", "alpha101_006", "alpha101_041"]',
        ),
        (
            b'names = ["alpha101_006", "alpha101_012", "alpha101_041"]',
            b'names = ["alpha101_006", "alpha101_012", "alpha101_999"]',
        ),
    ),
    ids=("window-drift", "trial-drift", "factor-order-drift", "factor-name-drift"),
)
def test_sixth_config_identity_rejects_before_cost_snapshot_or_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    needle: bytes,
    replacement: bytes,
) -> None:
    payload = (
        PROJECT_ROOT
        / "configs/research/m2_classic_daily_factors_sixth_batch.toml"
    ).read_bytes()
    assert needle in payload
    changed = payload.replace(needle, replacement, 1)
    project_root, _, _, data_root = _classic_project(
        tmp_path,
        config_payload=changed,
        config_name="m2_classic_daily_factors_sixth_batch.toml",
    )
    calls: list[str] = []

    def unexpected_cost(*_: object, **__: object) -> object:
        calls.append("cost")
        raise AssertionError("cost binding must not run")

    def unexpected_snapshot(**_: object) -> object:
        calls.append("snapshot")
        raise AssertionError("snapshot verifier must not run")

    monkeypatch.setattr(classic_runner, "_cost_schedule_binding", unexpected_cost)
    monkeypatch.setattr(
        classic_runner,
        "verify_tushare_bulk_clean_snapshot",
        unexpected_snapshot,
    )
    with pytest.raises(ValueError, match="invalid classic-factor config"):
        main(
            _classic_main_args(
                project_root,
                data_root,
                config_name="m2_classic_daily_factors_sixth_batch.toml",
            )
        )
    assert calls == []
    assert not (project_root / "artifacts-test").exists()


@pytest.mark.parametrize(
    ("mutation_name", "old", "new"),
    (
        (
            "snapshot",
            b'snapshot_id = "b79a7b5e66dee0ae439c030078414157ca6c1f3b6ce7fbe5e36ff3910c1089d2"',
            b'snapshot_id = "0000000000000000000000000000000000000000000000000000000000000000"',
        ),
        ("universe", b"top_n = 800", b"top_n = 801"),
        ("folds", b"test_end = 2026-08-13", b"test_end = 2026-08-12"),
        (
            "admission",
            b"minimum_mean_test_rank_ic = 0.01",
            b"minimum_mean_test_rank_ic = 0.02",
        ),
        (
            "comment",
            b"[research]\n",
            b"[research]\n# R15 payload identity drift\n",
        ),
    ),
    ids=("snapshot", "universe", "folds", "admission", "comment"),
)
def test_frozen_max_config_identity_rejects_before_cost_snapshot_or_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation_name: str,
    old: bytes,
    new: bytes,
) -> None:
    payload = _canonical_main_config_payload(_frozen_max_config_payload())
    assert mutation_name
    assert old in payload
    payload = payload.replace(old, new, 1)
    assert hashlib.sha256(payload).hexdigest() != _FROZEN_MAX_R15_CONFIG_SHA256
    project_root, _, _, data_root = _classic_project(tmp_path, config_payload=payload)
    cost_calls: list[str] = []
    verifier_calls: list[str] = []

    def unexpected_cost_binding(*_: object, **__: object) -> object:
        cost_calls.append("called")
        raise AssertionError("cost binding must not run")

    def unexpected_verifier(**_: object) -> object:
        verifier_calls.append("called")
        raise AssertionError("snapshot verifier must not run")

    monkeypatch.setattr(classic_runner, "_cost_schedule_binding", unexpected_cost_binding)
    monkeypatch.setattr(classic_runner, "verify_tushare_bulk_clean_snapshot", unexpected_verifier)
    with pytest.raises(ValueError, match="frozen MAX R15 config payload identity mismatch"):
        main(_classic_main_args(project_root, data_root))
    assert cost_calls == []
    assert verifier_calls == []
    assert not (project_root / "artifacts-test").exists()


def test_frozen_cost_semantic_mismatch_rejects_before_snapshot_or_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, _, cost_path, data_root = _classic_project(
        tmp_path, config_payload=_frozen_max_config_payload()
    )
    cost_path.write_bytes(
        cost_path.read_bytes().replace(
            b"commission_rate = 0.00025",
            b"commission_rate = 0.00026",
            1,
        )
    )
    verifier_calls: list[str] = []

    def unexpected_verifier(**_: object) -> object:
        verifier_calls.append("called")
        raise AssertionError("snapshot verifier must not run")

    monkeypatch.setattr(classic_runner, "verify_tushare_bulk_clean_snapshot", unexpected_verifier)
    with pytest.raises(ValueError, match="classic cost schedule semantic identity mismatch"):
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


def test_legacy_classic_keeps_cost_binding_after_snapshot_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_config = (
        PROJECT_ROOT / "configs/research/m2_classic_daily_factors.toml"
    ).read_bytes()
    project_root, _, _, data_root = _classic_project(
        tmp_path,
        config_payload=base_config,
        config_name="m2_classic_daily_factors.toml",
    )
    cost_calls: list[str] = []

    def unexpected_early_cost(*_: object, **__: object) -> object:
        cost_calls.append("early")
        raise AssertionError("legacy cost binding must remain after snapshot")

    def stop_at_snapshot_verifier(**_: object) -> object:
        raise RuntimeError("SNAPSHOT_SENTINEL")

    monkeypatch.setattr(classic_runner, "_cost_periods", unexpected_early_cost)
    monkeypatch.setattr(classic_runner, "_cost_schedule_binding", unexpected_early_cost)
    monkeypatch.setattr(
        classic_runner,
        "verify_tushare_bulk_clean_snapshot",
        stop_at_snapshot_verifier,
    )
    with pytest.raises(RuntimeError, match="SNAPSHOT_SENTINEL"):
        main(
            _classic_main_args(
                project_root,
                data_root,
                config_name="m2_classic_daily_factors.toml",
            )
        )
    assert cost_calls == []
    assert not (project_root / "artifacts-test").exists()


def test_legacy_main_ignores_extra_cost_identity_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_payload = _canonical_main_config_payload(
        (PROJECT_ROOT / "configs/research/m2_classic_daily_factors.toml").read_bytes()
    )
    newline = b"\n"
    extra_cost_field = (
        newline
        + f'cost_schedule_semantic_sha256 = "{_COST_SEMANTIC_SHA256}"'.encode()
        + newline
    )
    extra_payload = base_payload.replace(
        newline + b"[admission]", extra_cost_field + b"[admission]", 1
    )
    assert extra_payload != base_payload
    extra_payload = _with_eols(extra_payload, (b"\r\n",))

    base_project, _, _, base_data_root = _classic_project(
        tmp_path / "base",
        config_payload=base_payload,
        config_name="m2_classic_daily_factors.toml",
    )
    extra_project, _, _, extra_data_root = _classic_project(
        tmp_path / "extra",
        config_payload=extra_payload,
        config_name="m2_classic_daily_factors.toml",
    )
    periods, _ = _cost_schedule_binding_from_payload(_cost_payload())
    events: list[str] = []
    captured_runs: list[object] = []
    captured_reports: list[dict[str, object]] = []

    def snapshot_verifier(*, data_root: Path, snapshot_id: str) -> object:
        del data_root
        events.append("snapshot")
        return SimpleNamespace(
            snapshot_id=snapshot_id,
            manifest_sha256="a" * 64,
            stock_rows=1,
            fund_rows=0,
        )

    def stock_reader(*_: object, **__: object) -> pl.DataFrame:
        return pl.DataFrame({"trade_date": [dt.date(2019, 1, 1)]})

    def cost_periods(*_: object, **__: object) -> tuple[object, ...]:
        events.append("cost_periods")
        return periods

    def unexpected_cost_binding(*_: object, **__: object) -> object:
        events.append("cost_binding")
        raise AssertionError("legacy main must not call cost binding")

    def labels(**_: object) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "trade_date": [dt.date(2020, 1, 2)],
                "history_rows": [120],
                "liquidity_20": [20_000_000.0],
            }
        )

    def evaluate(**kwargs: object) -> dict[str, pl.DataFrame]:
        assert kwargs["costs"] == periods
        frame = pl.DataFrame({"value": [1]})
        return {
            "daily_ic": frame,
            "group_returns": frame,
            "fold_metrics": frame,
            "targets": frame,
            "portfolio_nav": frame,
        }

    def summarize(
        _metrics: pl.DataFrame,
        *,
        factors: tuple[str, ...],
        admission: object,
    ) -> pl.DataFrame:
        del admission
        return pl.DataFrame(
            {
                "factor": list(factors),
                "mean_test_rank_ic": [0.0] * len(factors),
                "research_status": ["REJECTED"] * len(factors),
            }
        )

    def publish(
        *, artifact_root: Path, run: object, output_payloads: dict[str, bytes]
    ) -> tuple[Path, object, bool]:
        captured_runs.append(run)
        captured_reports.append(json.loads(output_payloads["report.json"]))
        return artifact_root, run, False

    monkeypatch.setattr(classic_runner, "verify_tushare_bulk_clean_snapshot", snapshot_verifier)
    monkeypatch.setattr(classic_runner, "read_tushare_bulk_clean_stock_bars", stock_reader)
    monkeypatch.setattr(classic_runner, "select_frozen_liquid_universe", lambda *_args, **_kwargs: ("000001.SZ",))
    monkeypatch.setattr(classic_runner, "compute_classic_daily_factors", lambda *_args, **_kwargs: pl.DataFrame())
    monkeypatch.setattr(classic_runner, "build_next_open_factor_labels", labels)
    monkeypatch.setattr(classic_runner, "_cost_periods", cost_periods)
    monkeypatch.setattr(classic_runner, "_cost_schedule_binding", unexpected_cost_binding)
    monkeypatch.setattr(classic_runner, "evaluate_walk_forward", evaluate)
    monkeypatch.setattr(classic_runner, "summarize_factors", summarize)
    monkeypatch.setattr(classic_runner, "compute_code_sha256", lambda **_kwargs: "b" * 64)
    monkeypatch.setattr(classic_runner, "publish_lightweight_research_run", publish)

    for project_root, data_root in (
        (base_project, base_data_root),
        (extra_project, extra_data_root),
    ):
        event_start = len(events)
        assert main(
            _classic_main_args(
                project_root,
                data_root,
                config_name="m2_classic_daily_factors.toml",
            )
        ) == 0
        assert events[event_start:] == ["snapshot", "cost_periods"]

    assert len(captured_runs) == 2
    assert len(captured_reports) == 2
    base_run, extra_run = captured_runs
    assert base_run.config_sha256 == hashlib.sha256(base_payload).hexdigest()  # type: ignore[attr-defined]
    assert extra_run.config_sha256 == hashlib.sha256(extra_payload).hexdigest()  # type: ignore[attr-defined]
    assert base_run.config_sha256 != extra_run.config_sha256  # type: ignore[attr-defined]
    base_identity = dict(vars(base_run))
    extra_identity = dict(vars(extra_run))
    base_identity.pop("run_id")
    extra_identity.pop("run_id")
    base_identity.pop("config_sha256")
    extra_identity.pop("config_sha256")
    assert base_identity == extra_identity
    assert tuple(item.name for item in extra_run.inputs) == (  # type: ignore[attr-defined]
        "tushare-stock-bars",
    )
    assert captured_reports[0] == captured_reports[1]
    assert not (base_project / "artifacts-test").exists()
    assert not (extra_project / "artifacts-test").exists()


def test_legacy_main_binds_raw_sha_for_eol_only_variants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical_payload = _canonical_main_config_payload(
        (PROJECT_ROOT / "configs/research/m2_classic_daily_factors.toml").read_bytes()
    )
    lf_payload = _with_eols(canonical_payload, (b"\n",))
    crlf_payload = _with_eols(canonical_payload, (b"\r\n",))
    assert lf_payload != crlf_payload
    periods, _ = _cost_schedule_binding_from_payload(_cost_payload())
    captured_runs: list[object] = []

    def snapshot_verifier(*, data_root: Path, snapshot_id: str) -> object:
        del data_root
        return SimpleNamespace(
            snapshot_id=snapshot_id,
            manifest_sha256="a" * 64,
            stock_rows=1,
            fund_rows=0,
        )

    def stock_reader(*_: object, **__: object) -> pl.DataFrame:
        return pl.DataFrame({"trade_date": [dt.date(2019, 1, 1)]})

    def cost_periods(*_: object, **__: object) -> tuple[object, ...]:
        return periods

    def labels(**_: object) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "trade_date": [dt.date(2020, 1, 2)],
                "history_rows": [120],
                "liquidity_20": [20_000_000.0],
            }
        )

    def evaluate(**kwargs: object) -> dict[str, pl.DataFrame]:
        assert kwargs["costs"] == periods
        frame = pl.DataFrame({"value": [1]})
        return {
            "daily_ic": frame,
            "group_returns": frame,
            "fold_metrics": frame,
            "targets": frame,
            "portfolio_nav": frame,
        }

    def summarize(
        _metrics: pl.DataFrame,
        *,
        factors: tuple[str, ...],
        admission: object,
    ) -> pl.DataFrame:
        del admission
        return pl.DataFrame(
            {
                "factor": list(factors),
                "mean_test_rank_ic": [0.0] * len(factors),
                "research_status": ["REJECTED"] * len(factors),
            }
        )

    def publish(
        *, artifact_root: Path, run: object, output_payloads: dict[str, bytes]
    ) -> tuple[Path, object, bool]:
        del output_payloads
        captured_runs.append(run)
        return artifact_root, run, False

    monkeypatch.setattr(classic_runner, "verify_tushare_bulk_clean_snapshot", snapshot_verifier)
    monkeypatch.setattr(classic_runner, "read_tushare_bulk_clean_stock_bars", stock_reader)
    monkeypatch.setattr(
        classic_runner,
        "select_frozen_liquid_universe",
        lambda *_args, **_kwargs: ("000001.SZ",),
    )
    monkeypatch.setattr(classic_runner, "compute_classic_daily_factors", lambda *_args: pl.DataFrame())
    monkeypatch.setattr(classic_runner, "build_next_open_factor_labels", labels)
    monkeypatch.setattr(classic_runner, "_cost_periods", cost_periods)
    monkeypatch.setattr(
        classic_runner,
        "_cost_schedule_binding",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy main must not call cost binding")
        ),
    )
    monkeypatch.setattr(classic_runner, "evaluate_walk_forward", evaluate)
    monkeypatch.setattr(classic_runner, "summarize_factors", summarize)
    monkeypatch.setattr(classic_runner, "compute_code_sha256", lambda **_kwargs: "b" * 64)
    monkeypatch.setattr(classic_runner, "publish_lightweight_research_run", publish)

    for payload, name in ((lf_payload, "lf"), (crlf_payload, "crlf")):
        project_root, _, _, data_root = _classic_project(
            tmp_path / name,
            config_payload=payload,
            config_name="m2_classic_daily_factors.toml",
        )
        assert (
            main(
                _classic_main_args(
                    project_root,
                    data_root,
                    config_name="m2_classic_daily_factors.toml",
                )
            )
            == 0
        )

    assert len(captured_runs) == 2
    lf_run, crlf_run = captured_runs
    assert lf_run.config_sha256 == hashlib.sha256(lf_payload).hexdigest()  # type: ignore[attr-defined]
    assert crlf_run.config_sha256 == hashlib.sha256(crlf_payload).hexdigest()  # type: ignore[attr-defined]
    assert lf_run.config_sha256 != crlf_run.config_sha256  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("variant", "eols"),
    (
        ("full_lf", (b"\n",)),
        ("full_crlf", (b"\r\n",)),
        ("mixed_locations", (b"\n", b"\r\n", b"\r", b"\r\n")),
        ("repeated_bare_cr", (b"\r",)),
    ),
    ids=("full-lf", "full-crlf", "mixed-locations", "repeated-bare-cr"),
)
def test_frozen_max_eol_variants_publish_with_canonical_config_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
    eols: tuple[bytes, ...],
) -> None:
    payload = _with_eols(
        _canonical_main_config_payload(_frozen_max_config_payload()), eols
    )
    assert variant
    project_root, _, _, data_root = _classic_project(tmp_path, config_payload=payload)
    run = _run_fifth_main_to_publish(project_root, data_root, monkeypatch)
    assert run.config_sha256 == _FROZEN_MAX_R15_CONFIG_SHA256  # type: ignore[attr-defined]
    assert not (project_root / "artifacts-test").exists()


@pytest.mark.parametrize(
    ("mutation_name", "expected_error"),
    (
        ("leading_bom", "leading BOM"),
        ("nul", "contains NUL"),
        ("invalid_utf8", "not valid UTF-8"),
        ("interior_feff", "frozen MAX R15 config payload identity mismatch"),
    ),
    ids=("leading-bom", "nul", "invalid-utf8", "interior-feff"),
)
def test_frozen_max_payload_hygiene_rejects_before_cost_snapshot_or_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation_name: str,
    expected_error: str,
) -> None:
    payload = _canonical_main_config_payload(_frozen_max_config_payload())
    if mutation_name == "leading_bom":
        payload = b"\xef\xbb\xbf" + payload
    elif mutation_name == "nul":
        payload = payload.replace(
            b"[research]\n", b"[research]\n# invalid\x00\n", 1
        )
    elif mutation_name == "invalid_utf8":
        payload = payload.replace(
            b"[research]\n", b"[research]\n# invalid\xff\n", 1
        )
    else:
        payload = payload.replace(
            b"[research]\n",
            b"[research]\n# interior \xef\xbb\xbf remains part of identity\n",
            1,
        )
    project_root, _, _, data_root = _classic_project(tmp_path, config_payload=payload)
    calls: list[str] = []

    def unexpected_cost(*_: object, **__: object) -> object:
        calls.append("cost")
        raise AssertionError("cost binding must not run")

    def unexpected_snapshot(**_: object) -> object:
        calls.append("snapshot")
        raise AssertionError("snapshot verifier must not run")

    def unexpected_publish(*_: object, **__: object) -> object:
        calls.append("artifact")
        raise AssertionError("artifact publisher must not run")

    monkeypatch.setattr(classic_runner, "_cost_schedule_binding", unexpected_cost)
    monkeypatch.setattr(classic_runner, "verify_tushare_bulk_clean_snapshot", unexpected_snapshot)
    monkeypatch.setattr(classic_runner, "publish_lightweight_research_run", unexpected_publish)
    with pytest.raises(ValueError, match=expected_error):
        main(_classic_main_args(project_root, data_root))
    assert calls == []
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
        PROJECT_ROOT / "configs/research/m2_classic_daily_factors_sixth_batch.toml",
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

    for section, key, value in (
        ("alpha101_sixth_batch", "correlation_window_sessions", 11),
        ("alpha101_sixth_batch", "delta_lag_sessions", 2),
        ("alpha101_sixth_batch", "alpha041_price_basis", "adjusted"),
        ("alpha101_sixth_batch", "trial_delta", 2),
        ("factors", "maximum_median_absolute_rank_correlation", 0.81),
        ("coverage", "minimum_rebalance_symbols", 99),
    ):
        changed = deepcopy(configs[6])
        changed[section][key] = value
        with pytest.raises(ValueError, match="invalid classic-factor config"):
            _validate_config(changed, threads=2)

    changed = deepcopy(configs[6])
    changed["factors"]["redundancy_reference_names"].reverse()
    with pytest.raises(ValueError, match="invalid classic-factor config"):
        _validate_config(changed, threads=2)
    changed = deepcopy(configs[6])
    changed["alpha101_sixth_batch"]["trial_budget"] = True
    with pytest.raises(ValueError, match="invalid classic-factor config"):
        _validate_config(changed, threads=2)
    changed = deepcopy(configs[6])
    changed["alpha101_sixth_batch"]["unexpected"] = 1
    with pytest.raises(ValueError, match="invalid classic-factor config"):
        _validate_config(changed, threads=2)
    changed = deepcopy(configs[6])
    del changed["alpha101_sixth_batch"]["attempt_ordinal"]
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
            "factor_a": ["control"],
            "factor_b": ["downside_beta"],
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
            "factor_a": ["alpha158_beta20"],
            "factor_b": ["alpha158_resi20"],
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
        (1.0, 2.0, 3.0, 4.0, 5.0),
        (0.0, 1.0, 2.0, 3.0, 4.0),
        (5.0, 4.0, 3.0, 4.0, 5.0),
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
    ).row(0) == (2.0, 7.0 / 3.0, 8.0 / 3.0, 11.0 / 3.0, 14.0 / 3.0)
    assert result.filter(pl.col("fold") == 0).select(
        "group_1_le_group_2",
        "group_2_le_group_3",
        "group_3_le_group_4",
        "group_4_le_group_5",
    ).row(0) == (True, True, True, True)

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
            "factor_a": ["alpha158_std20"],
            "factor_b": [factor],
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
