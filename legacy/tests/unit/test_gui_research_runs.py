import datetime as dt
import hashlib
import io
import json
from pathlib import Path
from typing import Literal, Sequence, cast

import polars as pl
import pytest

from quant.gui.research_runs import (
    ResearchRunSummary,
    diagnose_research_run_comparison,
    discover_research_runs,
    filter_research_runs,
    load_comparison_nav_projection,
    load_nav_projection,
    verify_research_run,
    verify_research_run_comparison,
)
from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchFoldV1,
    ResearchInputDigestV1,
    publish_lightweight_research_run,
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _nav_payload(*, include_fold: bool = True) -> bytes:
    values: dict[str, list[object]] = {
        "strategy": ["s1", "s1", "s1"],
        "date": [
            dt.date(2026, 7, 8),
            dt.date(2026, 7, 9),
            dt.date(2026, 7, 9),
        ],
        "unit_nav": [1.0, 1.01, 1.005],
        "cost_multiplier": [1.0, 1.0, 2.0],
    }
    if include_fold:
        values["fold"] = [1, 1, 1]
    buffer = io.BytesIO()
    pl.DataFrame(values).write_parquet(buffer)
    return buffer.getvalue()


def _publish_run(
    tmp_path: Path,
    *,
    artifact_root: Path | None = None,
    case: str = "base",
    strategy_name: str = "fixture_strategy",
    universe_name: str = "GUI_G0_FIXTURE",
    data_end: dt.date = dt.date(2026, 7, 9),
    input_digest: str | None = None,
    aggregate_metrics: tuple[tuple[str, int | float], ...] = (
        ("fold_count", 1),
        ("net_sharpe", 0.75),
    ),
    caveats: tuple[str, ...] = ("Research-only fixture.",),
    nav_payload: bytes | None = None,
    include_nav: bool = True,
) -> tuple[Path, Path]:
    target_root = artifact_root if artifact_root is not None else tmp_path / "artifacts"
    run = LightweightResearchRunV1(
        schema_version="lightweight-research-run-v1",
        run_id="",
        hypothesis_id=f"gui-g1-{case}",
        hypothesis="A read-only GUI should project verified immutable evidence.",
        strategy_name=strategy_name,
        strategy_version="1.0.0",
        conclusion="RESEARCH_ONLY",
        random_seed=0,
        config_relative_path=f"configs/research/gui_{case}.toml",
        config_sha256=_sha(f"config-{case}".encode()),
        code_sha256=_sha(f"code-{case}".encode()),
        universe_name=universe_name,
        universe_frozen_as_of=dt.date(2026, 7, 7),
        candidate_symbols=("510300.SH",),
        data_start=dt.date(2025, 1, 1),
        data_end=data_end,
        signal_timing="close",
        execution_timing="next_session_open",
        valuation_timing="close",
        folds=(
            ResearchFoldV1(
                1,
                dt.date(2025, 1, 1),
                dt.date(2025, 6, 30),
                dt.date(2025, 7, 1),
                dt.date(2025, 9, 30),
                dt.date(2025, 10, 1),
                data_end,
            ),
        ),
        cost_multipliers=(0.5, 1.0, 2.0),
        selection_metric="net_sharpe",
        inputs=(
            ResearchInputDigestV1(
                name="prices",
                rows=2,
                min_date=dt.date(2026, 7, 8),
                max_date=dt.date(2026, 7, 9),
                content_sha256=input_digest or _sha(b"prices"),
            ),
        ),
        outputs=(),
        aggregate_metrics=aggregate_metrics,
        caveats=caveats,
    )
    outputs = {"report.json": b"{}"}
    if include_nav:
        outputs["test_nav.parquet"] = (
            nav_payload if nav_payload is not None else _nav_payload()
        )
    run_root, _, _ = publish_lightweight_research_run(
        artifact_root=target_root,
        run=run,
        output_payloads=outputs,
    )
    return target_root, run_root


def _only_run(artifact_root: Path):  # type: ignore[no-untyped-def]
    catalog = discover_research_runs(artifact_root)
    assert catalog.issues == ()
    assert len(catalog.runs) == 1
    return catalog.runs[0]


def test_filter_default_is_stable_and_preserves_order_and_identity(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    _publish_run(
        tmp_path,
        artifact_root=artifact_root,
        case="filter-order-a",
        strategy_name="filter_strategy_a",
    )
    _publish_run(
        tmp_path,
        artifact_root=artifact_root,
        case="filter-order-b",
        strategy_name="filter_strategy_b",
    )
    catalog = discover_research_runs(artifact_root)
    all_conclusions = ("REJECTED", "RESEARCH_ONLY", "PAPER_CANDIDATE")
    all_strategies = tuple(
        run.manifest.strategy_name for run in catalog.runs
    )

    filtered = filter_research_runs(
        catalog.runs,
        conclusions=all_conclusions,
        strategies=all_strategies,
        query=" \t\n",
        caveat_presence="ALL",
    )

    assert filtered == catalog.runs
    assert all(
        filtered_run is catalog_run
        for filtered_run, catalog_run in zip(filtered, catalog.runs, strict=True)
    )


def test_filter_literal_query_matches_only_allowed_manifest_labels(
    tmp_path: Path,
) -> None:
    artifact_root, _ = _publish_run(tmp_path)
    run = _only_run(artifact_root)
    choices = {
        "conclusions": (run.manifest.conclusion,),
        "strategies": (run.manifest.strategy_name,),
        "caveat_presence": "ALL",
    }
    queries = (
        run.manifest.run_id[:12].upper(),
        run.manifest.hypothesis_id.upper(),
        run.manifest.strategy_name.upper(),
        run.manifest.strategy_version,
        f"{run.manifest.strategy_name} {run.manifest.strategy_version}".upper(),
    )

    for query in queries:
        filtered = filter_research_runs((run,), query=query, **choices)
        assert filtered == (run,)
        assert filtered[0] is run


def test_filter_query_does_not_search_non_label_manifest_fields(
    tmp_path: Path,
) -> None:
    artifact_root, _ = _publish_run(tmp_path)
    run = _only_run(artifact_root)
    choices = {
        "conclusions": (run.manifest.conclusion,),
        "strategies": (run.manifest.strategy_name,),
        "caveat_presence": "ALL",
    }

    for query in (
        "verified immutable evidence",
        "research-only fixture",
        run.manifest.config_relative_path,
        run.manifest.config_sha256,
        "net_sharpe",
    ):
        assert filter_research_runs((run,), query=query, **choices) == ()


def test_filter_caveat_presence_is_exact_and_composable(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    _publish_run(
        tmp_path,
        artifact_root=artifact_root,
        case="filter-present",
        strategy_name="filter_strategy_present",
        caveats=("present",),
    )
    _publish_run(
        tmp_path,
        artifact_root=artifact_root,
        case="filter-absent",
        strategy_name="filter_strategy_absent",
        caveats=(),
    )
    catalog = discover_research_runs(artifact_root)
    all_strategies = tuple(run.manifest.strategy_name for run in catalog.runs)

    all_runs = filter_research_runs(
        catalog.runs,
        conclusions=("RESEARCH_ONLY",),
        strategies=all_strategies,
        caveat_presence="ALL",
    )
    present = filter_research_runs(
        catalog.runs,
        conclusions=("RESEARCH_ONLY",),
        strategies=all_strategies,
        caveat_presence="PRESENT",
    )
    absent = filter_research_runs(
        catalog.runs,
        conclusions=("RESEARCH_ONLY",),
        strategies=all_strategies,
        caveat_presence="ABSENT",
    )

    assert all_runs == catalog.runs
    assert tuple(run.manifest.strategy_name for run in present) == (
        "filter_strategy_present",
    )
    assert tuple(run.manifest.strategy_name for run in absent) == (
        "filter_strategy_absent",
    )
    assert filter_research_runs(
        catalog.runs,
        conclusions=(),
        strategies=all_strategies,
    ) == ()
    assert filter_research_runs(
        catalog.runs,
        conclusions=("RESEARCH_ONLY",),
        strategies=(),
    ) == ()
    assert filter_research_runs(
        catalog.runs,
        conclusions=("RESEARCH_ONLY",),
        strategies=("filter_strategy_present",),
        query="filter_strategy_absent",
        caveat_presence="PRESENT",
    ) == ()


def test_filter_preserves_duplicate_inputs_order_and_identity(tmp_path: Path) -> None:
    _, selected, _ = _publish_comparison_runs(tmp_path)
    repeated = (selected[1], selected[0], selected[1])

    filtered = filter_research_runs(
        repeated,
        conclusions=("RESEARCH_ONLY",),
        strategies=(
            selected[0].manifest.strategy_name,
            selected[1].manifest.strategy_name,
        ),
    )

    assert len(filtered) == 3
    assert filtered == repeated
    assert all(
        filtered_run is expected_run
        for filtered_run, expected_run in zip(filtered, repeated, strict=True)
    )


def test_filter_rejects_invalid_caveat_mode_before_iterating() -> None:
    class ExplodingRuns:
        def __iter__(self):  # type: ignore[no-untyped-def]
            raise AssertionError("invalid mode must fail before iterating runs")

    with pytest.raises(ValueError, match="caveat_presence"):
        filter_research_runs(
            cast(Sequence[ResearchRunSummary], ExplodingRuns()),
            conclusions=(),
            strategies=(),
            caveat_presence=cast(Literal["ALL", "PRESENT", "ABSENT"], "INVALID"),
        )


def test_filter_is_manifest_only_and_does_not_verify_or_access_run_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root, _ = _publish_run(tmp_path)
    run = _only_run(artifact_root)

    def fail_on_call(*_: object, **__: object) -> None:
        raise AssertionError("overview filtering must not verify output or NAV")

    for name in (
        "verify_research_run",
        "verify_research_run_comparison",
        "load_nav_projection",
        "load_comparison_nav_projection",
        "_read_regular_bytes",
    ):
        monkeypatch.setattr(f"quant.gui.research_runs.{name}", fail_on_call)

    class ForbiddenRunRoot:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"filter accessed run_root.{name}")

    isolated = ResearchRunSummary(
        run_root=cast(Path, ForbiddenRunRoot()),
        manifest=run.manifest,
    )
    filtered = filter_research_runs(
        (isolated,),
        conclusions=(run.manifest.conclusion,),
        strategies=(run.manifest.strategy_name,),
    )

    assert filtered == (isolated,)
    assert filtered[0] is isolated


def _publish_comparison_runs(
    tmp_path: Path,
    *,
    second_data_end: dt.date = dt.date(2026, 7, 9),
    second_universe_name: str = "GUI_G0_FIXTURE",
    second_input_digest: str | None = None,
    second_metrics: tuple[tuple[str, int | float], ...] = (
        ("fold_count", 1),
        ("net_sharpe", 0.5),
    ),
    second_include_nav: bool = True,
) -> tuple[Path, tuple[ResearchRunSummary, ...], tuple[Path, Path]]:
    artifact_root = tmp_path / "artifacts"
    _, first_root = _publish_run(
        tmp_path,
        artifact_root=artifact_root,
        case="comparison-a",
        strategy_name="fixture_strategy_a",
    )
    _, second_root = _publish_run(
        tmp_path,
        artifact_root=artifact_root,
        case="comparison-b",
        strategy_name="fixture_strategy_b",
        universe_name=second_universe_name,
        data_end=second_data_end,
        input_digest=second_input_digest,
        aggregate_metrics=second_metrics,
        include_nav=second_include_nav,
    )
    catalog = discover_research_runs(artifact_root)
    assert catalog.issues == ()
    by_id = {run.manifest.run_id: run for run in catalog.runs}
    selected = (by_id[first_root.name], by_id[second_root.name])
    return artifact_root, selected, (first_root, second_root)


def test_missing_runs_root_is_a_visible_nonfatal_issue(tmp_path: Path) -> None:
    catalog = discover_research_runs(tmp_path / "missing")

    assert catalog.runs == ()
    assert [issue.code for issue in catalog.issues] == ["RUNS_ROOT_MISSING"]


def test_valid_run_requires_integrity_before_bounded_nav_projection(tmp_path: Path) -> None:
    artifact_root, _ = _publish_run(tmp_path)
    run = _only_run(artifact_root)

    blocked = load_nav_projection(run)
    assert blocked.status == "BLOCKED"
    assert blocked.issue is not None
    assert blocked.issue.code == "NAV_NOT_AVAILABLE"

    integrity = verify_research_run(run)
    assert integrity.status == "VERIFIED"
    assert integrity.checked_files == 2

    nav = load_nav_projection(integrity)
    assert nav.status == "AVAILABLE"
    assert nav.issue is None
    assert nav.frame is not None
    assert nav.frame.height == 2
    assert nav.frame.get_column("cost_multiplier").to_list() == [1.0, 1.0]
    assert nav.frame.get_column("series").to_list() == ["s1 / fold 1", "s1 / fold 1"]


def test_noncanonical_manifest_is_rejected_without_breaking_catalog(tmp_path: Path) -> None:
    artifact_root, run_root = _publish_run(tmp_path)
    manifest_path = run_root / "run.json"
    parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")

    catalog = discover_research_runs(artifact_root)

    assert catalog.runs == ()
    assert [issue.code for issue in catalog.issues] == ["RUN_MANIFEST_NONCANONICAL"]


def test_directory_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    artifact_root, run_root = _publish_run(tmp_path)
    other_id = "f" * 64 if run_root.name != "f" * 64 else "e" * 64
    run_root.rename(run_root.with_name(other_id))

    catalog = discover_research_runs(artifact_root)

    assert catalog.runs == ()
    assert [issue.code for issue in catalog.issues] == ["RUN_ID_MISMATCH"]


def test_tampered_output_blocks_integrity_and_nav(tmp_path: Path) -> None:
    artifact_root, run_root = _publish_run(tmp_path)
    run = _only_run(artifact_root)
    (run_root / "report.json").write_bytes(b"tampered")

    integrity = verify_research_run(run)

    assert integrity.status == "BLOCKED"
    assert integrity.issue is not None
    assert integrity.issue.code == "RUN_OUTPUT_DIGEST_MISMATCH"
    nav = load_nav_projection(integrity)
    assert nav.status == "BLOCKED"


def test_extra_file_blocks_exact_output_tree(tmp_path: Path) -> None:
    artifact_root, run_root = _publish_run(tmp_path)
    run = _only_run(artifact_root)
    (run_root / "unexpected.tmp").write_bytes(b"unexpected")

    integrity = verify_research_run(run)

    assert integrity.status == "BLOCKED"
    assert integrity.issue is not None
    assert integrity.issue.code == "RUN_TREE_MISMATCH"


def test_linked_output_is_blocked_even_when_target_bytes_match(tmp_path: Path) -> None:
    artifact_root, run_root = _publish_run(tmp_path)
    run = _only_run(artifact_root)
    output_path = run_root / "report.json"
    target = tmp_path / "matching-report.json"
    target.write_bytes(output_path.read_bytes())
    output_path.unlink()
    try:
        output_path.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is not available: {exc}")

    integrity = verify_research_run(run)

    assert integrity.status == "BLOCKED"
    assert integrity.issue is not None
    assert integrity.issue.code == "RUN_OUTPUT_INVALID"


def test_invalid_nav_schema_is_not_projected(tmp_path: Path) -> None:
    artifact_root, _ = _publish_run(tmp_path, nav_payload=_nav_payload(include_fold=False))
    run = _only_run(artifact_root)
    integrity = verify_research_run(run)
    assert integrity.status == "VERIFIED"

    nav = load_nav_projection(integrity)

    assert nav.status == "BLOCKED"
    assert nav.frame is None
    assert nav.issue is not None
    assert nav.issue.code == "NAV_SCHEMA_INVALID"


def test_comparison_requires_two_to_four_unique_runs(tmp_path: Path) -> None:
    artifact_root, _ = _publish_run(tmp_path)
    run = _only_run(artifact_root)

    invalid_selections = ((), (run,), (run, run), (run, run, run, run, run))
    for selected in invalid_selections:
        diagnosis = diagnose_research_run_comparison(selected)
        comparison = verify_research_run_comparison(selected)

        assert diagnosis.selection_valid is False
        assert diagnosis.contract_compatible is False
        assert diagnosis.fields == ()
        assert diagnosis.issue is not None
        assert diagnosis.issue.code == "COMPARISON_SELECTION_INVALID"
        assert comparison.status == "BLOCKED"
        assert comparison.integrities == ()
        assert comparison.issue == diagnosis.issue


def test_verified_comparison_preserves_selection_and_nav_rows(tmp_path: Path) -> None:
    _, runs, _ = _publish_comparison_runs(tmp_path)
    selected = (runs[1], runs[0])

    diagnosis = diagnose_research_run_comparison(selected)
    comparison = verify_research_run_comparison(selected)

    assert diagnosis.runs == selected
    assert diagnosis.selection_valid is True
    assert diagnosis.contract_compatible is True
    assert diagnosis.issue is None
    assert len(diagnosis.fields) == 14
    assert diagnosis.fields[0].field == "schema_version"
    assert diagnosis.fields[-1].field == "inputs"
    assert all(item.relations == ("REFERENCE", "SAME") for item in diagnosis.fields)
    assert comparison.status == "VERIFIED"
    assert comparison.issue is None
    assert comparison.runs == selected
    assert tuple(item.run for item in comparison.integrities) == selected
    assert selected[0].manifest.strategy_name != selected[1].manifest.strategy_name
    assert [dict(run.manifest.aggregate_metrics)["net_sharpe"] for run in selected] == [
        0.5,
        0.75,
    ]

    nav = load_comparison_nav_projection(comparison)

    assert nav.status == "AVAILABLE"
    assert nav.issue is None
    assert nav.frame is not None
    assert nav.frame.height == 4
    assert nav.frame.get_column("selection_order").to_list() == [1, 1, 2, 2]
    assert list(dict.fromkeys(nav.frame.get_column("run_id").to_list())) == [
        selected[0].manifest.run_id,
        selected[1].manifest.run_id,
    ]
    assert nav.frame.get_column("unit_nav").to_list() == [1.0, 1.01, 1.0, 1.01]
    assert "rank" not in nav.frame.columns
    assert "delta" not in nav.frame.columns


@pytest.mark.parametrize(
    (
        "second_data_end",
        "second_universe_name",
        "second_input_digest",
        "second_metrics",
        "mismatched_field",
    ),
    [
        (
            dt.date(2026, 7, 10),
            "GUI_G0_FIXTURE",
            None,
            (("fold_count", 1), ("net_sharpe", 0.5)),
            "data_end",
        ),
        (
            dt.date(2026, 7, 9),
            "OTHER_UNIVERSE",
            None,
            (("fold_count", 1), ("net_sharpe", 0.5)),
            "universe_name",
        ),
        (
            dt.date(2026, 7, 9),
            "GUI_G0_FIXTURE",
            _sha(b"revised-prices"),
            (("fold_count", 1), ("net_sharpe", 0.5)),
            "inputs",
        ),
        (
            dt.date(2026, 7, 9),
            "GUI_G0_FIXTURE",
            None,
            (("fold_count", 1), ("sortino", 0.5)),
            "aggregate_metric_names",
        ),
    ],
)
def test_comparison_contract_mismatch_fails_closed(
    tmp_path: Path,
    second_data_end: dt.date,
    second_universe_name: str,
    second_input_digest: str | None,
    second_metrics: tuple[tuple[str, int | float], ...],
    mismatched_field: str,
) -> None:
    _, runs, _ = _publish_comparison_runs(
        tmp_path,
        second_data_end=second_data_end,
        second_universe_name=second_universe_name,
        second_input_digest=second_input_digest,
        second_metrics=second_metrics,
    )

    diagnosis = diagnose_research_run_comparison(runs)
    comparison = verify_research_run_comparison(runs)

    assert diagnosis.selection_valid is True
    assert diagnosis.contract_compatible is False
    assert diagnosis.issue is not None
    assert diagnosis.issue.code == "COMPARISON_CONTRACT_MISMATCH"
    relation_by_field = {item.field: item.relations for item in diagnosis.fields}
    assert relation_by_field[mismatched_field] == ("REFERENCE", "DIFFERENT")
    assert comparison.status == "BLOCKED"
    assert comparison.integrities == ()
    assert comparison.issue == diagnosis.issue
    assert comparison.issue is not None
    assert mismatched_field in comparison.issue.detail


def test_three_run_diagnosis_preserves_field_and_selection_order(tmp_path: Path) -> None:
    artifact_root, runs, _ = _publish_comparison_runs(tmp_path)
    _, third_root = _publish_run(
        tmp_path,
        artifact_root=artifact_root,
        case="comparison-c",
        strategy_name="fixture_strategy_c",
        universe_name="OTHER_UNIVERSE",
        input_digest=_sha(b"third-prices"),
    )
    catalog = discover_research_runs(artifact_root)
    assert catalog.issues == ()
    by_id = {run.manifest.run_id: run for run in catalog.runs}
    selected = (runs[1], runs[0], by_id[third_root.name])

    diagnosis = diagnose_research_run_comparison(selected)

    assert diagnosis.runs == selected
    assert diagnosis.selection_valid is True
    assert diagnosis.contract_compatible is False
    assert diagnosis.issue is not None
    assert diagnosis.issue.detail == (
        "Selected runs have incompatible comparison fields: inputs, universe_name."
    )
    assert tuple(
        item.field for item in diagnosis.fields if "DIFFERENT" in item.relations
    ) == ("universe_name", "inputs")
    relation_by_field = {item.field: item.relations for item in diagnosis.fields}
    assert relation_by_field["universe_name"] == (
        "REFERENCE",
        "SAME",
        "DIFFERENT",
    )
    assert relation_by_field["inputs"] == ("REFERENCE", "SAME", "DIFFERENT")
    assert all(
        relation_by_field[field] == ("REFERENCE", "SAME", "SAME")
        for field in relation_by_field.keys() - {"universe_name", "inputs"}
    )


def test_contract_mismatch_stops_before_output_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, runs, _ = _publish_comparison_runs(
        tmp_path,
        second_universe_name="OTHER_UNIVERSE",
    )

    def fail_on_call(_: ResearchRunSummary) -> None:
        raise AssertionError(
            "output verification must not run for a contract mismatch"
        )

    monkeypatch.setattr("quant.gui.research_runs.verify_research_run", fail_on_call)

    comparison = verify_research_run_comparison(runs)

    assert comparison.status == "BLOCKED"
    assert comparison.integrities == ()
    assert comparison.issue is not None
    assert comparison.issue.code == "COMPARISON_CONTRACT_MISMATCH"


def test_one_tampered_run_blocks_all_comparison_evidence(tmp_path: Path) -> None:
    _, runs, (_, second_root) = _publish_comparison_runs(tmp_path)
    (second_root / "report.json").write_bytes(b"tampered")

    diagnosis = diagnose_research_run_comparison(runs)
    comparison = verify_research_run_comparison(runs)

    assert diagnosis.selection_valid is True
    assert diagnosis.contract_compatible is True
    assert diagnosis.issue is None
    assert all(item.relations == ("REFERENCE", "SAME") for item in diagnosis.fields)
    assert comparison.status == "BLOCKED"
    assert comparison.integrities == ()
    assert comparison.issue is not None
    assert comparison.issue.code == "COMPARISON_RUN_UNVERIFIED"
    assert "RUN_OUTPUT_DIGEST_MISMATCH" in comparison.issue.detail
    nav = load_comparison_nav_projection(comparison)
    assert nav.status == "BLOCKED"
    assert nav.frame is None


def test_comparison_declared_output_total_is_bounded_before_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, runs, _ = _publish_comparison_runs(tmp_path)
    monkeypatch.setattr("quant.gui.research_runs._MAX_INTEGRITY_BYTES", 1)

    comparison = verify_research_run_comparison(runs)

    assert comparison.status == "BLOCKED"
    assert comparison.integrities == ()
    assert comparison.issue is not None
    assert comparison.issue.code == "COMPARISON_OUTPUT_LIMIT"


def test_one_missing_nav_blocks_the_combined_nav_only(tmp_path: Path) -> None:
    _, runs, _ = _publish_comparison_runs(tmp_path, second_include_nav=False)
    comparison = verify_research_run_comparison(runs)
    assert comparison.status == "VERIFIED"

    nav = load_comparison_nav_projection(comparison)

    assert nav.status == "BLOCKED"
    assert nav.frame is None
    assert nav.issue is not None
    assert nav.issue.code == "COMPARISON_NAV_UNAVAILABLE"
    assert "NAV_NOT_AVAILABLE" in nav.issue.detail


def test_combined_nav_row_limit_fails_closed(tmp_path: Path) -> None:
    _, runs, _ = _publish_comparison_runs(tmp_path)
    comparison = verify_research_run_comparison(runs)
    assert comparison.status == "VERIFIED"

    nav = load_comparison_nav_projection(comparison, max_rows=3)

    assert nav.status == "BLOCKED"
    assert nav.frame is None
    assert nav.issue is not None
    assert nav.issue.code == "COMPARISON_NAV_LIMIT"
