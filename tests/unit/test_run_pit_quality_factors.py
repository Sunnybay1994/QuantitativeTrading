from __future__ import annotations

import datetime as dt
import tomllib
from copy import deepcopy
from pathlib import Path

import polars as pl
import pytest

import quant.research.run_pit_quality_factors as pit_runner
from quant.factors import PIT_QUALITY_FACTOR_NAMES
from quant.research.classic_factor_evaluation import build_diagnostic_factor_targets
from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchFoldV1,
    ResearchInputDigestV1,
    publish_lightweight_research_run,
    verify_lightweight_research_run,
)
from quant.research.run_classic_factors import _cost_schedule_binding_from_payload
from quant.research.run_pit_quality_factors import (
    _cost_schedule_input_digest,
    apply_pit_quality_coverage_gate,
    apply_redundancy_signal_coverage_gate,
    attach_redundancy_signal_coverage,
    _validate_config,
    build_pit_quality_coverage,
    build_pit_quality_panel,
    main,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_COST_SEMANTIC_SHA256 = "b2041d8495aa408de0bd264d6c03eb7e4d174e03f120289bc8471cbb5ea0a959"


def _frozen_config_payload() -> bytes:
    payload = (
        PROJECT_ROOT / "configs/research/m2_pit_quality_factors.toml"
    ).read_bytes().replace(b"\r\n", b"\n")
    return payload.replace(
        b'report_type_freeze_status = "UNFROZEN"',
        b'report_type_freeze_status = "FROZEN"',
    ).replace(b"allowed_report_types = []", b'allowed_report_types = ["1"]')


def _pit_project(tmp_path: Path, *, config_payload: bytes) -> tuple[Path, Path, Path, Path]:
    project_root = tmp_path / "project"
    config_path = project_root / "configs/research/m2_pit_quality_factors.toml"
    cost_path = project_root / "configs/research/m3_qlib_example.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes(config_payload)
    cost_path.write_bytes(
        (PROJECT_ROOT / "configs/research/m3_qlib_example.toml").read_bytes()
    )
    data_root = project_root / "data"
    data_root.mkdir()
    return project_root, config_path, cost_path, data_root


def _main_args(project_root: Path, data_root: Path) -> list[str]:
    return [
        "--config",
        "configs/research/m2_pit_quality_factors.toml",
        "--daily-basic-snapshot-id",
        "a" * 64,
        "--financial-snapshot-id",
        "b" * 64,
        "--data-root",
        str(data_root),
        "--artifact-root",
        "artifacts-test",
        "--project-root",
        str(project_root),
    ]


def _replace_expected_cost_sha(payload: bytes, replacement: str | None) -> bytes:
    line = f'cost_schedule_semantic_sha256 = "{_COST_SEMANTIC_SHA256}"\n'.encode()
    if replacement is None:
        return payload.replace(line, b"")
    return payload.replace(
        line,
        f'cost_schedule_semantic_sha256 = "{replacement}"\n'.encode(),
    )


def _bars() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = dt.date(2025, 1, 1)
    for symbol_index, symbol in enumerate(("600001.SH", "000001.SZ")):
        for index in range(50):
            close = 10.0 + symbol_index + index
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": start + dt.timedelta(days=index),
                    "open": close,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close + 0.5,
                    "volume": 1_000.0 + index,
                    "amount": (1_000.0 + index) * close,
                    "adj_factor": 1.0,
                    "source": "fixture",
                }
            )
    return pl.DataFrame(rows)


def _daily_basic(signal_dates: tuple[dt.date, ...]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol_index, symbol in enumerate(("600001.SH", "000001.SZ")):
        for date in signal_dates:
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": date,
                    "close": 100.0,
                    "turnover_rate": 1.0,
                    "turnover_rate_free": 1.2,
                    "volume_ratio": None,
                    "pe": 10.0,
                    "pe_ttm": 10.0 + symbol_index,
                    "pb": 2.0 + symbol_index,
                    "ps": 5.0,
                    "ps_ttm": 4.0 + symbol_index,
                    "dividend_yield": 1.0,
                    "dividend_yield_ttm": 2.0,
                    "total_shares": 10_000_000.0,
                    "float_shares": 8_000_000.0,
                    "free_float_shares": 7_000_000.0,
                    "total_market_value": 100_000_000.0 + symbol_index,
                    "circulating_market_value": 80_000_000.0,
                    "source": "tushare",
                }
            )
    return pl.DataFrame(rows)


def _signals(signal_dates: tuple[dt.date, ...]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for date_index, date in enumerate(signal_dates):
        for symbol_index, symbol in enumerate(("600001.SH", "000001.SZ")):
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": date,
                    "financial_period_end": dt.date(2024, 12, 31),
                    "pit_roe_ttm": 0.1 + symbol_index + date_index,
                    "pit_roa_ttm": 0.05 + symbol_index,
                    "pit_cash_profit_quality_ttm": (
                        None if date_index == 1 and symbol_index == 1 else 1.2
                    ),
                    "pit_total_accruals_ttm": -0.01 + symbol_index,
                }
            )
    return pl.DataFrame(rows)


def test_sparse_panel_uses_next_monthly_execution_as_portfolio_exit() -> None:
    bars = _bars()
    sessions = tuple(sorted(set(bars.get_column("trade_date").to_list())))
    signal_dates = (sessions[20], sessions[39])
    panel = build_pit_quality_panel(
        signal_values=_signals(signal_dates),
        daily_basic=_daily_basic(signal_dates),
        bars=bars,
        sessions=sessions,
    )

    first = panel.filter(pl.col("trade_date") == signal_dates[0])
    assert first.get_column("execution_date_rebalance").unique().to_list() == [sessions[21]]
    assert first.get_column("exit_date_rebalance").unique().to_list() == [sessions[40]]
    assert first.get_column("exit_date_20").unique().to_list() == [sessions[41]]

    targets, periods = build_diagnostic_factor_targets(
        panel,
        factor="pit_roe_ttm",
        direction=1,
        fold=1,
        test_start=signal_dates[0],
        test_end=sessions[40],
        top_k=1,
        rebalance_every_sessions=1,
        minimum_symbols=2,
        strategy_name="pit_quality",
        strategy_version="v1",
        return_column="label_rebalance",
        execution_date_column="execution_date_rebalance",
        exit_date_column="exit_date_rebalance",
    )
    assert targets.get_column("execution_date").unique().to_list() == [sessions[21]]
    assert periods.get_column("exit_date").to_list() == [sessions[40]]
    expected = (10.0 + 1 + 40) / (10.0 + 1 + 21) - 1.0
    assert periods.get_column("gross_return").item() == pytest.approx(expected)


def test_panel_is_row_order_invariant_and_daily_basic_close_is_not_label_authority() -> None:
    bars = _bars()
    sessions = tuple(sorted(set(bars.get_column("trade_date").to_list())))
    dates = (sessions[20], sessions[39])
    first = build_pit_quality_panel(
        signal_values=_signals(dates),
        daily_basic=_daily_basic(dates),
        bars=bars,
        sessions=sessions,
    )
    second = build_pit_quality_panel(
        signal_values=_signals(dates).reverse(),
        daily_basic=_daily_basic(dates)
        .with_columns((pl.col("close") * 999.0).alias("close"))
        .reverse(),
        bars=bars.reverse(),
        sessions=sessions,
    )
    compared = [
        *PIT_QUALITY_FACTOR_NAMES,
        "log_total_market_value",
        "entry_open_20",
        "exit_open_20",
        "label_20",
        "entry_open_rebalance",
        "exit_open_rebalance",
        "label_rebalance",
    ]
    assert first.select(compared).equals(second.select(compared), null_equal=True)


def test_coverage_preserves_factor_nulls_and_financial_period_range() -> None:
    date = dt.date(2025, 2, 28)
    eligibility = pl.DataFrame(
        {
            "as_of": [date] * 5,
            "symbol": [f"00000{index}.SZ" for index in range(1, 6)],
            "factor": ["pit_cash_profit_quality_ttm"] * 5,
            "financial_period_end": [dt.date(2024, 12, 31), None, None, None, None],
            "status": [
                "VALID",
                "MISSING_CHAIN",
                "NON_INDUSTRIAL",
                "INVALID_DENOMINATOR",
                "QUARANTINED",
            ],
        },
        schema={
            "as_of": pl.Date(),
            "symbol": pl.String(),
            "factor": pl.String(),
            "financial_period_end": pl.Date(),
            "status": pl.String(),
        },
    )
    coverage = build_pit_quality_coverage(eligibility)
    cash = coverage.filter(
        (pl.col("factor") == "pit_cash_profit_quality_ttm") & (pl.col("trade_date") == date)
    )
    assert cash.select(
        "eligible_rows",
        "valid_rows",
        "missing_chain_rows",
        "non_industrial_rows",
        "invalid_denominator_rows",
        "quarantined_rows",
        "coverage",
    ).row(0) == (
        5,
        1,
        1,
        1,
        1,
        1,
        0.2,
    )
    assert cash.get_column("min_period_end").item() == dt.date(2024, 12, 31)


def test_pit_quality_config_is_frozen_without_unpublished_snapshot_ids() -> None:
    path = PROJECT_ROOT / "configs/research/m2_pit_quality_factors.toml"
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    with pytest.raises(ValueError, match="invalid PIT-quality-factor config"):
        _validate_config(config, threads=2)
    assert "financial_snapshot_id" not in config["data"]
    assert "daily_basic_snapshot_id" not in config["data"]
    assert config["portfolio"]["rebalance_every_signals"] == 1
    assert config["portfolio"]["cost_schedule_semantic_sha256"] == _COST_SEMANTIC_SHA256
    assert config["factors"]["report_type_freeze_status"] == "UNFROZEN"
    assert config["factors"]["allowed_report_types"] == []

    frozen = deepcopy(config)
    frozen["factors"]["report_type_freeze_status"] = "FROZEN"
    frozen["factors"]["allowed_report_types"] = ["1"]
    _validate_config(frozen, threads=2)

    changed = deepcopy(frozen)
    changed["factors"]["redundancy_reference_names"].reverse()
    with pytest.raises(ValueError, match="invalid PIT-quality-factor config"):
        _validate_config(changed, threads=2)

    with pytest.raises(ValueError, match="invalid PIT-quality-factor config"):
        _validate_config(frozen, threads=3)


@pytest.mark.parametrize(
    ("replacement", "message"),
    (
        (None, "invalid PIT-quality-factor config"),
        ("f" * 63, "invalid PIT-quality-factor config"),
        (_COST_SEMANTIC_SHA256.upper(), "invalid PIT-quality-factor config"),
        ("0" * 64, "PIT cost schedule semantic identity mismatch"),
    ),
)
def test_cost_identity_rejects_before_data_or_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str | None,
    message: str,
) -> None:
    payload = _replace_expected_cost_sha(_frozen_config_payload(), replacement)
    project_root, _, _, data_root = _pit_project(tmp_path, config_payload=payload)
    verifier_calls: list[str] = []

    def unexpected_verifier(**_: object) -> object:
        verifier_calls.append("called")
        raise AssertionError("data verifier must not run")

    monkeypatch.setattr(pit_runner, "verify_tushare_bulk_clean_snapshot", unexpected_verifier)
    monkeypatch.setattr(pit_runner, "verify_tushare_daily_basic_snapshot", unexpected_verifier)
    monkeypatch.setattr(pit_runner, "verify_tushare_financial_snapshot", unexpected_verifier)
    with pytest.raises(ValueError, match=message):
        main(_main_args(project_root, data_root))
    assert verifier_calls == []
    assert not (project_root / "artifacts-test").exists()


def test_main_and_cost_config_each_use_one_stable_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, config_path, cost_path, data_root = _pit_project(
        tmp_path, config_payload=_frozen_config_payload()
    )
    original_read_bytes = Path.read_bytes
    reads = {config_path.resolve(): 0, cost_path.resolve(): 0}

    def read_then_drift(path: Path) -> bytes:
        payload = original_read_bytes(path)
        resolved = path.resolve()
        if resolved == config_path.resolve():
            reads[resolved] += 1
            config_path.write_bytes(
                _replace_expected_cost_sha(payload, "0" * 64)
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

    def stop_at_first_verifier(**_: object) -> object:
        raise RuntimeError("SNAPSHOT_SENTINEL")

    def unexpected_verifier(**_: object) -> object:
        raise AssertionError("later verifier must not run")

    monkeypatch.setattr(Path, "read_bytes", read_then_drift)
    monkeypatch.setattr(
        pit_runner, "verify_tushare_bulk_clean_snapshot", stop_at_first_verifier
    )
    monkeypatch.setattr(pit_runner, "verify_tushare_daily_basic_snapshot", unexpected_verifier)
    monkeypatch.setattr(pit_runner, "verify_tushare_financial_snapshot", unexpected_verifier)
    with pytest.raises(RuntimeError, match="SNAPSHOT_SENTINEL"):
        main(_main_args(project_root, data_root))
    assert reads == {config_path.resolve(): 1, cost_path.resolve(): 1}
    assert not (project_root / "artifacts-test").exists()


def test_cost_input_is_canonical_and_freshly_verifiable(tmp_path: Path) -> None:
    periods, semantic_sha256 = _cost_schedule_binding_from_payload(
        (PROJECT_ROOT / "configs/research/m3_qlib_example.toml").read_bytes()
    )
    cost_input = _cost_schedule_input_digest(periods, semantic_sha256)
    inputs = (
        cost_input,
        ResearchInputDigestV1("tushare-daily-basic", 1, None, None, "1" * 64),
        ResearchInputDigestV1("tushare-financials", 1, None, None, "2" * 64),
        ResearchInputDigestV1("tushare-stock-bars", 1, None, None, "3" * 64),
    )
    assert cost_input == ResearchInputDigestV1(
        name="a-share-cost-schedule",
        rows=3,
        min_date=None,
        max_date=None,
        content_sha256=_COST_SEMANTIC_SHA256,
    )
    run = LightweightResearchRunV1(
        schema_version="lightweight-research-run-v1",
        run_id="",
        hypothesis_id="cost-semantic-test",
        hypothesis="Cost semantics are explicitly bound.",
        strategy_name="pit_quality_test",
        strategy_version="v1",
        conclusion="RESEARCH_ONLY",
        random_seed=1,
        config_relative_path="configs/research/test.toml",
        config_sha256="a" * 64,
        code_sha256="b" * 64,
        universe_name="test-universe",
        universe_frozen_as_of=dt.date(2019, 12, 31),
        candidate_symbols=("000001.SZ",),
        data_start=dt.date(2020, 1, 1),
        data_end=dt.date(2022, 12, 31),
        signal_timing="close",
        execution_timing="next_session_open",
        valuation_timing="close",
        folds=(
            ResearchFoldV1(
                fold=1,
                train_start=dt.date(2020, 1, 1),
                train_end=dt.date(2020, 6, 30),
                validation_start=dt.date(2020, 7, 1),
                validation_end=dt.date(2020, 12, 31),
                test_start=dt.date(2021, 1, 1),
                test_end=dt.date(2021, 12, 31),
            ),
        ),
        cost_multipliers=(0.5, 1.0, 2.0),
        selection_metric="cost-semantic-test",
        inputs=inputs,
        outputs=(),
        aggregate_metrics=(("factor_count", 1),),
        caveats=("test fixture",),
    )
    root, published, reused = publish_lightweight_research_run(
        artifact_root=tmp_path,
        run=run,
        output_payloads={"report.json": b"{}"},
    )
    assert reused is False
    verified = verify_lightweight_research_run(run_root=root)
    assert verified == published
    assert tuple(item.name for item in verified.inputs) == (
        "a-share-cost-schedule",
        "tushare-daily-basic",
        "tushare-financials",
        "tushare-stock-bars",
    )


def test_redundancy_calendar_coverage_fails_closed_for_one_missing_month() -> None:
    redundancy = pl.DataFrame(
        {
            "factor_a": ["pit_roe_ttm", "pit_roe_ttm"],
            "factor_b": ["control_a", "control_b"],
            "dates": [12, 11],
            "median_rank_corr": [0.1, 0.2],
            "median_abs_rank_corr": [0.1, 0.2],
        }
    )
    covered = attach_redundancy_signal_coverage(
        redundancy,
        expected_signal_dates=12,
        minimum_coverage=1.0,
    )
    assert covered.get_column("signal_date_coverage_passed").to_list() == [
        True,
        False,
    ]
    factor_summary = pl.DataFrame(
        {
            "factor": ["pit_roe_ttm"],
            "research_status": ["RESEARCH_ONLY"],
        }
    )
    gated = apply_redundancy_signal_coverage_gate(
        factor_summary,
        redundancy_summary=covered,
    )
    assert gated.get_column("research_status").item() == "REJECTED"


def _redundancy_coverage_rows(
    rows: tuple[tuple[str, str, bool], ...],
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "factor_a": [factor_a for factor_a, _, _ in rows],
            "factor_b": [factor_b for _, factor_b, _ in rows],
            "signal_date_coverage_passed": [coverage for _, _, coverage in rows],
        },
        schema={
            "factor_a": pl.String,
            "factor_b": pl.String,
            "signal_date_coverage_passed": pl.Boolean,
        },
    )


def _redundancy_factor_summary(
    factors: tuple[str, ...], *, rejected: tuple[str, ...] = ()
) -> pl.DataFrame:
    rejected_set = set(rejected)
    return pl.DataFrame(
        {
            "factor": list(factors),
            "research_status": [
                "REJECTED" if factor in rejected_set else "RESEARCH_ONLY"
                for factor in factors
            ],
        },
        schema={"factor": pl.String, "research_status": pl.String},
    )


def test_redundancy_coverage_is_symmetric_and_preserves_summary_order() -> None:
    summary = _redundancy_factor_summary(
        ("candidate_b", "candidate_a", "already_rejected"),
        rejected=("already_rejected",),
    )
    redundancy = _redundancy_coverage_rows(
        (
            ("control_a", "candidate_a", True),
            ("candidate_b", "control_b", False),
            ("control_c", "candidate_b", True),
            ("already_rejected", "control_d", True),
        )
    )

    gated = apply_redundancy_signal_coverage_gate(
        summary,
        redundancy_summary=redundancy,
    )

    assert gated.get_column("factor").to_list() == [
        "candidate_b",
        "candidate_a",
        "already_rejected",
    ]
    assert gated.get_column("redundancy_signal_coverage_passed").to_list() == [
        False,
        True,
        True,
    ]
    assert gated.get_column("research_status").to_list() == [
        "REJECTED",
        "RESEARCH_ONLY",
        "REJECTED",
    ]

    swapped = apply_redundancy_signal_coverage_gate(
        summary,
        redundancy_summary=redundancy.select(
            pl.col("factor_b").alias("factor_a"),
            pl.col("factor_a").alias("factor_b"),
            "signal_date_coverage_passed",
        ).reverse(),
    )
    assert swapped.select(
        "factor", "redundancy_signal_coverage_passed", "research_status"
    ).equals(
        gated.select("factor", "redundancy_signal_coverage_passed", "research_status")
    )


def test_redundancy_coverage_does_not_add_absent_reference_rows() -> None:
    summary = _redundancy_factor_summary(("candidate",))
    gated = apply_redundancy_signal_coverage_gate(
        summary,
        redundancy_summary=_redundancy_coverage_rows(
            (("candidate", "reference_not_in_summary", True),)
        ),
    )

    assert gated.get_column("factor").to_list() == ["candidate"]
    assert gated.get_column("research_status").to_list() == ["RESEARCH_ONLY"]


def test_redundancy_coverage_rejects_no_incident() -> None:
    gated = apply_redundancy_signal_coverage_gate(
        _redundancy_factor_summary(("candidate",)),
        redundancy_summary=_redundancy_coverage_rows(()),
    )

    assert gated.select(
        "redundancy_signal_coverage_passed", "research_status"
    ).row(0) == (False, "REJECTED")


def test_redundancy_duplicate_and_reverse_duplicate_pairs_use_all_incidents() -> None:
    summary = _redundancy_factor_summary(("candidate_a", "candidate_b"))
    gated = apply_redundancy_signal_coverage_gate(
        summary,
        redundancy_summary=_redundancy_coverage_rows(
            (
                ("candidate_a", "control", True),
                ("control", "candidate_a", False),
                ("candidate_b", "control", True),
                ("candidate_b", "control", True),
            )
        ),
    )

    assert gated.height == summary.height
    assert gated.get_column("factor").to_list() == ["candidate_a", "candidate_b"]
    assert gated.get_column("redundancy_signal_coverage_passed").to_list() == [
        False,
        True,
    ]


@pytest.mark.parametrize(
    "invalid_redundancy",
    [
        pl.DataFrame(
            {
                "factor_a": ["candidate"],
                "factor_b": ["control"],
                "signal_date_coverage_passed": pl.Series(
                    [None], dtype=pl.Boolean
                ),
            }
        ),
        pl.DataFrame(
            {
                "factor_a": ["candidate"],
                "factor_b": ["control"],
                "signal_date_coverage_passed": [1],
            }
        ),
        pl.DataFrame({"factor_a": ["candidate"], "factor_b": ["control"]}),
        pl.DataFrame(
            {
                "factor_a": ["candidate"],
                "signal_date_coverage_passed": [True],
            }
        ),
        pl.DataFrame(
            {
                "factor_b": ["control"],
                "signal_date_coverage_passed": [True],
            }
        ),
    ],
    ids=["null", "non_bool", "missing_coverage", "missing_factor_b", "missing_factor_a"],
)
def test_redundancy_coverage_rejects_invalid_incident_inputs(
    invalid_redundancy: pl.DataFrame,
) -> None:
    with pytest.raises(ValueError, match="invalid redundancy signal coverage gate"):
        apply_redundancy_signal_coverage_gate(
            _redundancy_factor_summary(("candidate",)),
            redundancy_summary=invalid_redundancy,
        )


def test_redundancy_coverage_rejects_duplicate_summary_factors() -> None:
    duplicate_summary = pl.DataFrame(
        {
            "factor": ["candidate", "candidate"],
            "research_status": ["RESEARCH_ONLY", "RESEARCH_ONLY"],
        }
    )
    with pytest.raises(ValueError, match="invalid redundancy signal coverage gate"):
        apply_redundancy_signal_coverage_gate(
            duplicate_summary,
            redundancy_summary=_redundancy_coverage_rows(
                (("candidate", "control", True),)
            ),
        )


@pytest.mark.parametrize(
    "invalid_summary",
    [
        pl.DataFrame(
            {"factor": ["candidate"], "research_status": ["HOLD"]},
            schema={"factor": pl.String, "research_status": pl.String},
        ),
        pl.DataFrame(
            {
                "factor": ["candidate"],
                "research_status": pl.Series([None], dtype=pl.String),
            }
        ),
        pl.DataFrame({"factor": ["candidate"], "research_status": [1]}),
        pl.DataFrame(
            {
                "factor": ["candidate"],
                "research_status": pl.Series(
                    ["RESEARCH_ONLY"], dtype=pl.Categorical
                ),
            }
        ),
        pl.DataFrame(
            {
                "factor": ["candidate"],
                "research_status": pl.Series(
                    ["RESEARCH_ONLY"],
                    dtype=pl.Enum(["RESEARCH_ONLY", "REJECTED"]),
                ),
            }
        ),
    ],
    ids=["unexpected", "null", "non_string", "categorical", "enum"],
)
def test_redundancy_coverage_rejects_invalid_research_status(
    invalid_summary: pl.DataFrame,
) -> None:
    with pytest.raises(ValueError, match="invalid redundancy signal coverage gate"):
        apply_redundancy_signal_coverage_gate(
            invalid_summary,
            redundancy_summary=_redundancy_coverage_rows(
                (("candidate", "control", True),)
            ),
        )


@pytest.mark.parametrize(
    "invalid_summary, invalid_redundancy",
    [
        (
            _redundancy_factor_summary(("",)),
            _redundancy_coverage_rows((("candidate", "control", True),)),
        ),
        (
            _redundancy_factor_summary(("candidate",)),
            _redundancy_coverage_rows((("", "control", True),)),
        ),
        (
            _redundancy_factor_summary(("candidate",)),
            _redundancy_coverage_rows((("candidate", "", True),)),
        ),
    ],
    ids=["empty_summary_factor", "empty_factor_a", "empty_factor_b"],
)
def test_redundancy_coverage_rejects_empty_identifiers(
    invalid_summary: pl.DataFrame,
    invalid_redundancy: pl.DataFrame,
) -> None:
    with pytest.raises(ValueError, match="invalid redundancy signal coverage gate"):
        apply_redundancy_signal_coverage_gate(
            invalid_summary,
            redundancy_summary=invalid_redundancy,
        )


def test_redundancy_coverage_preserves_diagnostics_and_rejects_output_collision() -> None:
    summary = _redundancy_factor_summary(("candidate",)).with_columns(
        pl.lit(0.125).alias("median_test_rank_ic")
    )
    gated = apply_redundancy_signal_coverage_gate(
        summary,
        redundancy_summary=_redundancy_coverage_rows(
            (("candidate", "control", True),)
        ),
    )
    assert gated.get_column("median_test_rank_ic").item() == 0.125
    assert gated.get_column("research_status").item() == "RESEARCH_ONLY"

    collision = summary.with_columns(
        pl.lit(True).alias("redundancy_signal_coverage_passed")
    )
    with pytest.raises(ValueError, match="invalid redundancy signal coverage gate"):
        apply_redundancy_signal_coverage_gate(
            collision,
            redundancy_summary=_redundancy_coverage_rows(
                (("candidate", "control", True),)
            ),
        )


def _coverage_rows(
    dates: tuple[dt.date, ...], *, valid_rows: int, eligible_rows: int
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "factor": ["pit_roe_ttm"] * len(dates),
            "trade_date": list(dates),
            "eligible_rows": [eligible_rows] * len(dates),
            "valid_rows": [valid_rows] * len(dates),
            "missing_chain_rows": [eligible_rows - valid_rows] * len(dates),
            "non_industrial_rows": [0] * len(dates),
            "invalid_denominator_rows": [0] * len(dates),
            "quarantined_rows": [0] * len(dates),
            "coverage": [valid_rows / eligible_rows] * len(dates),
            "min_period_end": [dt.date(2024, 12, 31)] * len(dates),
            "max_period_end": [dt.date(2024, 12, 31)] * len(dates),
        }
    )


def test_signal_coverage_gate_accepts_exactly_eighty_percent() -> None:
    dates = tuple(dt.date(2025, month, 28) for month in range(1, 6))
    summary = pl.DataFrame(
        {"factor": ["pit_roe_ttm"], "research_status": ["RESEARCH_ONLY"]}
    )
    gated, completed = apply_pit_quality_coverage_gate(
        summary,
        coverage=_coverage_rows(dates, valid_rows=100, eligible_rows=125),
        signal_dates=dates,
        minimum_signal_symbols=100,
        minimum_median_signal_coverage=0.80,
    )
    assert gated.select(
        "median_signal_coverage", "pit_signal_coverage_passed", "research_status"
    ).row(0) == (0.8, True, "RESEARCH_ONLY")
    assert completed.get_column("daily_minimum_signal_symbols_passed").all()


def test_signal_coverage_gate_rejects_799_percent_and_missing_schedule_date() -> None:
    dates = tuple(dt.date(2025, month, 28) for month in range(1, 6))
    summary = pl.DataFrame(
        {"factor": ["pit_roe_ttm"], "research_status": ["RESEARCH_ONLY"]}
    )
    low, _ = apply_pit_quality_coverage_gate(
        summary,
        coverage=_coverage_rows(dates, valid_rows=799, eligible_rows=1000),
        signal_dates=dates,
        minimum_signal_symbols=100,
        minimum_median_signal_coverage=0.80,
    )
    assert low.get_column("research_status").item() == "REJECTED"

    missing, completed = apply_pit_quality_coverage_gate(
        summary,
        coverage=_coverage_rows(dates[:-1], valid_rows=800, eligible_rows=1000),
        signal_dates=dates,
        minimum_signal_symbols=100,
        minimum_median_signal_coverage=0.80,
    )
    assert missing.get_column("research_status").item() == "REJECTED"
    absent = completed.filter(pl.col("trade_date") == dates[-1])
    assert absent.select("valid_rows", "coverage").row(0) == (0, 0.0)


def test_signal_coverage_gate_rejects_shifted_schedule_date() -> None:
    dates = (dt.date(2025, 1, 31), dt.date(2025, 2, 28))
    shifted = (dates[0], dt.date(2025, 3, 3))
    summary = pl.DataFrame(
        {"factor": ["pit_roe_ttm"], "research_status": ["RESEARCH_ONLY"]}
    )
    with pytest.raises(ValueError, match="outside the pre-registered calendar"):
        apply_pit_quality_coverage_gate(
            summary,
            coverage=_coverage_rows(shifted, valid_rows=100, eligible_rows=100),
            signal_dates=dates,
            minimum_signal_symbols=100,
            minimum_median_signal_coverage=0.80,
        )
