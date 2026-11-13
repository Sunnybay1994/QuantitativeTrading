from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from quant.reporting.runtime_import_coverage import (
    CoverageError,
    _generate_report,
    _parse_log,
)
from quant.cli import main as quant_main


def test_current_invocation_survives_runpy_main_alias(monkeypatch):
    from quant.reporting import runtime_import_coverage as coverage

    name = coverage.__spec__.name
    monkeypatch.delitem(coverage.sys.modules, name)
    assert name in coverage._current_modules(None)
    assert coverage._current_modules(()) == set()


def _fixture_tree(tmp_path: Path, *, today_log: str = "quant.cli\n") -> tuple[Path, Path, Path]:
    project_root = tmp_path / "project"
    source_root = project_root / "src" / "quant"
    logs_root = project_root / "artifacts" / "runtime_imports"
    output_root = project_root / "artifacts" / "runtime_import_coverage"
    (source_root / "pkg").mkdir(parents=True)
    logs_root.mkdir(parents=True)
    (source_root / "__init__.py").write_text('"""root"""\n', encoding="utf-8")
    (source_root / "__main__.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (source_root / "pkg" / "__init__.py").write_text("value = 1\n\n", encoding="utf-8")
    (source_root / "pkg" / "worker.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (source_root / "reporting").mkdir()
    (source_root / "reporting" / "runtime_import_coverage.py").write_text(
        "def report():\n    return None\n", encoding="utf-8"
    )
    (logs_root / "2026-11-09.txt").write_text("quant.cli\n", encoding="utf-8")
    (logs_root / "2026-11-23.txt").write_text(today_log, encoding="utf-8")
    return project_root, logs_root, output_root


def test_before_release_date_refuses_before_creating_output(tmp_path: Path) -> None:
    project_root, logs_root, output_root = _fixture_tree(tmp_path)
    with pytest.raises(CoverageError, match="2026-11-23"):
        _generate_report(
            project_root=project_root,
            logs_root=logs_root,
            output_root=output_root,
            today=date(2026, 11, 22),
            fixture_mode=True,
        )
    assert not output_root.exists()


def test_fourteen_day_window_does_not_require_fourteen_active_log_dates(tmp_path: Path) -> None:
    project_root, logs_root, output_root = _fixture_tree(tmp_path)
    (logs_root / "2026-11-09.txt").write_text("quant.cli\n", encoding="utf-8")
    output = _generate_report(
        project_root=project_root,
        logs_root=logs_root,
        output_root=output_root,
        today=date(2026, 11, 23),
        fixture_mode=True,
    )
    report = json.loads((output / "runtime_import_coverage.json").read_text(encoding="utf-8"))
    assert report["observation_window"]["elapsed_calendar_days"] == 14
    assert report["observation_window"]["observed_log_day_count"] == 2


def test_generates_fixture_report_with_init_mapping_gaps_and_current_modules(tmp_path: Path) -> None:
    project_root, logs_root, output_root = _fixture_tree(tmp_path)
    # Make the observed window exactly 14 elapsed days; only two actual log days.
    first = logs_root / "2026-11-09.txt"
    first.write_text("quant.cli\nquant.pkg\n", encoding="utf-8")
    (logs_root / "2026-11-23.txt").write_text("quant.reporting.runtime_import_coverage\n", encoding="utf-8")

    output = _generate_report(
        project_root=project_root,
        logs_root=logs_root,
        output_root=output_root,
        today=date(2026, 11, 23),
        current_modules={"quant.reporting.runtime_import_coverage", "quant.cli"},
        fixture_mode=True,
    )
    report = json.loads((output / "runtime_import_coverage.json").read_text(encoding="utf-8"))
    rows = {row["module"]: row for row in report["modules"]}

    assert report["evidence_context"] == "fixture"
    assert report["status"] == "PARTIAL_OBSERVATION"
    assert report["observation_window"]["observed_log_day_count"] == 2
    assert report["observation_window"]["elapsed_calendar_days"] == 14
    assert len(report["observation_window"]["missing_past_log_dates"]) == 13
    assert rows["quant.pkg"]["path"] == "src/quant/pkg/__init__.py"
    assert rows["quant.pkg"]["line_count"] == 2
    assert rows["quant.pkg"]["classification"] == "observed_in_observation_window"
    assert rows["quant.reporting.runtime_import_coverage"]["classification"] == "observed_in_observation_window"
    assert rows["quant.reporting.runtime_import_coverage"]["observed_in_current_process"] is True
    assert rows["quant"]["classification"] == "entrypoint_visibility_indeterminate"
    assert rows["quant.__main__"]["classification"] == "entrypoint_visibility_indeterminate"
    assert report["current_date_log"]["sha256"] == hashlib.sha256(
        (logs_root / "2026-11-23.txt").read_bytes()
    ).hexdigest()
    assert report["runtime_log_semantics"]["other_unexited_long_lived_processes_not_fully_observed"] is True
    assert rows["quant.pkg"]["source_sha256"] == hashlib.sha256(
        (project_root / "src/quant/pkg/__init__.py").read_bytes()).hexdigest()


def test_current_log_can_be_missing_and_active_report_modules_are_counted(tmp_path: Path) -> None:
    project_root, logs_root, output_root = _fixture_tree(tmp_path)
    current_path = logs_root / "2026-11-23.txt"
    current_path.unlink()
    output = _generate_report(
        project_root=project_root,
        logs_root=logs_root,
        output_root=output_root,
        today=date(2026, 11, 23),
        current_modules={"quant.reporting.runtime_import_coverage"},
        fixture_mode=True,
    )
    report = json.loads((output / "runtime_import_coverage.json").read_text(encoding="utf-8"))
    row = next(item for item in report["modules"] if item["module"] == "quant.reporting.runtime_import_coverage")
    assert report["current_date_log"]["exists"] is False
    assert report["current_date_log"]["sha256"] is None
    assert "2026-11-23" not in report["observation_window"]["missing_past_log_dates"]
    assert row["classification"] == "observed_in_current_report_process_only"


def test_bad_current_date_log_is_reported_as_partial_not_silently_accepted(tmp_path: Path) -> None:
    project_root, logs_root, output_root = _fixture_tree(tmp_path)
    current_path = logs_root / "2026-11-23.txt"
    current_path.write_text("quant.cli\nnot-a-module\n", encoding="utf-8")
    output = _generate_report(
        project_root=project_root,
        logs_root=logs_root,
        output_root=output_root,
        today=date(2026, 11, 23),
        fixture_mode=True,
    )
    report = json.loads((output / "runtime_import_coverage.json").read_text(encoding="utf-8"))
    assert report["status"] == "PARTIAL_OBSERVATION"
    assert report["log_anomalies"] == [
        {"date": "2026-11-23", "invalid_line_count": 1, "invalid_line_numbers": [2]}
    ]
    assert "not-a-module" not in (output / "runtime_import_coverage.md").read_text(encoding="utf-8")


def test_parser_deduplicates_modules_and_reports_bad_rows_without_echoing_them(tmp_path: Path) -> None:
    path = tmp_path / "2026-11-23.txt"
    data = b"quant.cli\n\nquant.cli\nBAD_SECRET_SENTINEL\n"
    parsed = _parse_log(path, date(2026, 11, 23), data)
    assert parsed.modules == frozenset({"quant.cli"})
    assert parsed.invalid_lines == (4,)
    assert parsed.sha256 == hashlib.sha256(data).hexdigest()


def test_historical_bad_rows_are_retained_as_partial_input_status(tmp_path: Path) -> None:
    project_root, logs_root, output_root = _fixture_tree(tmp_path)
    (logs_root / "2026-11-09.txt").write_text("quant.cli\nBAD_HISTORICAL_ROW\n", encoding="utf-8")
    output = _generate_report(
        project_root=project_root,
        logs_root=logs_root,
        output_root=output_root,
        today=date(2026, 11, 23),
        fixture_mode=True,
    )
    report = json.loads((output / "runtime_import_coverage.json").read_text(encoding="utf-8"))
    assert report["status"] == "PARTIAL_OBSERVATION"
    assert report["log_anomalies"] == [
        {
            "date": "2026-11-09",
            "invalid_line_count": 1,
            "invalid_line_numbers": [2],
        }
    ]
    assert "BAD_HISTORICAL_ROW" not in (output / "runtime_import_coverage.md").read_text(encoding="utf-8")


def test_unified_cli_dispatches_report_command(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str] | None] = []
    monkeypatch.setattr(
        "quant.reporting.runtime_import_coverage.main",
        lambda argv=None: seen.append(argv) or 23,
    )
    assert quant_main(["report", "runtime-import-coverage", "--fixture-flag"]) == 23
    assert seen == [["--fixture-flag"]]


def test_existing_dated_report_is_never_overwritten(tmp_path: Path) -> None:
    project_root, logs_root, output_root = _fixture_tree(tmp_path)
    target = output_root / "2026-11-23"
    target.mkdir(parents=True)
    sentinel = target / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(CoverageError, match="拒绝覆盖"):
        _generate_report(
            project_root=project_root,
            logs_root=logs_root,
            output_root=output_root,
            today=date(2026, 11, 23),
            fixture_mode=True,
        )
    assert sentinel.read_text(encoding="utf-8") == "preserve"
