"""Compare Python source modules with the available runtime-import evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
_RELEASE_DATE = date(2026, 11, 23)
_MIN_SPAN_DAYS = 14
_MODULE_RE = re.compile(r"^quant(?:\.[A-Za-z_][A-Za-z0-9_]*)+$", re.ASCII)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$", re.ASCII)


class CoverageError(RuntimeError):
    """A fail-closed report prerequisite was not met."""


@dataclass(frozen=True)
class RuntimeLog:
    day: date
    path: Path
    sha256: str
    byte_count: int
    modules: frozenset[str]
    invalid_lines: tuple[int, ...]


def _today_shanghai() -> date:
    return datetime.now(timezone.utc).astimezone(_SHANGHAI).date()


def _read_stable(path: Path) -> bytes:
    """Read append-only evidence without waiting on the logger's exit lock."""
    for attempt in range(3):
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns) and len(data) == after.st_size:
            return data
        if attempt < 2:
            time.sleep(0.01)
    raise CoverageError(f"输入持续变化，停止读取：{path}")


def _parse_log(path: Path, day: date, data: bytes) -> RuntimeLog:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CoverageError(f"日志不是有效 UTF-8：{path}") from exc
    modules: set[str] = set()
    invalid: list[int] = []
    for number, raw_line in enumerate(text.splitlines(), 1):
        value = raw_line.strip()
        if value and _MODULE_RE.fullmatch(value):
            modules.add(value)
        elif value:
            invalid.append(number)
    return RuntimeLog(day, path, hashlib.sha256(data).hexdigest(), len(data), frozenset(modules), tuple(invalid))


def _load_log(path: Path, day: date) -> RuntimeLog:
    try:
        return _parse_log(path, day, _read_stable(path))
    except FileNotFoundError as exc:
        raise CoverageError(f"日志在读取时消失：{path}") from exc
    except OSError as exc:
        raise CoverageError(f"无法读取日志：{path} ({exc.__class__.__name__})") from exc


def _dated_logs(logs_root: Path, through: date) -> list[RuntimeLog]:
    if not logs_root.is_dir():
        raise CoverageError(f"运行日志目录缺失：{logs_root}")
    result: list[RuntimeLog] = []
    for path in logs_root.iterdir():
        if not path.is_file() or path.suffix.lower() != ".txt" or not _DATE_RE.fullmatch(path.stem):
            continue
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if day <= through:
            result.append(_load_log(path, day))
    return sorted(result, key=lambda item: item.day)


def _source_inventory(project_root: Path) -> list[dict[str, object]]:
    source_root = project_root / "src" / "quant"
    if not source_root.is_dir():
        raise CoverageError(f"源码目录缺失：{source_root}")
    rows: list[dict[str, object]] = []
    for path in sorted(source_root.rglob("*.py"), key=lambda item: item.as_posix()):
        try:
            source_bytes = _read_stable(path)
            text = source_bytes.decode("utf-8-sig")
        except (OSError, UnicodeDecodeError, CoverageError) as exc:
            relative = path.relative_to(project_root).as_posix()
            raise CoverageError(f"无法稳定读取源码：{relative}") from exc
        relative = path.relative_to(source_root).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        module = "quant" if not parts else "quant." + ".".join(parts)
        rows.append(
            {
                "module": module,
                "path": path.relative_to(project_root).as_posix(),
                "line_count": len(text.splitlines()),
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            }
        )
    if len({row["module"] for row in rows}) != len(rows):
        raise CoverageError("源码路径映射出重复模块名，停止生成。")
    return rows


def _log_root(project_root: Path, artifacts_root: Path) -> Path:
    override = os.environ.get("QUANT_RUNTIME_IMPORTS_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    configured = os.environ.get("QUANT_ARTIFACTS_ROOT")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = project_root / path
        return path.resolve() / "runtime_imports"
    return artifacts_root / "runtime_imports"


def _current_modules(injected: Iterable[str] | None) -> set[str]:
    names = injected if injected is not None else tuple(sys.modules)
    observed = {name for name in names if name.startswith("quant.")}
    # -m/runpy can execute this module as __main__ without its dotted key.
    if injected is None:
        executing = getattr(__spec__, "name", None)
        if isinstance(executing, str) and executing.startswith("quant."):
            observed.add(executing)
    return observed


def _classification(module: str, window: set[str], current: set[str]) -> str:
    if module == "quant" or module.endswith(".__main__"):
        return "entrypoint_visibility_indeterminate"
    if module in window:
        return "observed_in_observation_window"
    if module in current:
        return "observed_in_current_report_process_only"
    return "not_observed_in_window_or_current_process"


def _csv(rows: list[dict[str, object]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=["module", "path", "line_count", "classification", "observed_in_window", "observed_in_current_process", "source_sha256"],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _markdown(report: dict[str, object], rows: list[dict[str, object]]) -> str:
    window = report["observation_window"]
    totals = report["totals"]
    today_log = report["current_date_log"]
    assert isinstance(window, dict) and isinstance(totals, dict) and isinstance(today_log, dict)
    lines = [
        "# Runtime import coverage",
        "",
        f"- Status: `{report['status']}`; context: `{report['evidence_context']}`",
        f"- Report date (Asia/Shanghai): `{report['report_date']}`",
        f"- Observation window: `{window['first_log_date']}` through `{window['through_date']}` "
        f"({window['elapsed_calendar_days']} elapsed days)",
        f"- Actual log dates: {', '.join(window['observed_log_dates']) or 'none'}",
        f"- Missing past log dates: {', '.join(window['missing_past_log_dates']) or 'none'}",
        f"- Current-date log present at snapshot: `{today_log['exists']}`; "
        f"SHA-256: `{today_log['sha256'] or 'not available yet'}`",
        "",
        "Daily files are unions of `quant.*` names appended when CLI processes exit; they do not "
        "separate individual invocations. The report unions the dated logs in the observation "
        "window and the modules loaded by this active report process. Other long-lived processes "
        "that have not exited are outside the evidence. Root `quant` is not logged, and Python "
        "`__main__` files may run under an alias, so those entrypoints are marked indeterminate. "
        "An unobserved row is not a claim that the module is unused.",
        "",
        "## Totals",
        "",
        f"- Source modules / lines: **{totals['source_modules']} / {totals['source_lines']}**",
        f"- Seen in dated logs: **{totals['observed_in_window']} modules / {totals['observed_lines']} lines**",
        f"- Seen only in this report process: **{totals['current_process_only']} modules**",
        f"- Not seen in either source: **{totals['not_observed']} modules / {totals['not_observed_lines']} lines**",
        f"- Entrypoints with indeterminate visibility: **{totals['entrypoints']} modules / {totals['entrypoint_lines']} lines**",
        "",
        "## Source inventory preview",
        "",
        "Complete inventory: [CSV](runtime_import_coverage.csv), [JSON](runtime_import_coverage.json). "
        "The table below shows at most 50 modules.",
        "",
        "| Module | Source path | Lines | Classification |",
        "|---|---|---:|---|",
    ]
    lines.extend(
        f"| `{row['module']}` | `{row['path']}` | {row['line_count']} | `{row['classification']}` |"
        for row in rows[:50]
    )
    lines.append("")
    return "\n".join(lines)


def _write_exclusive(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def _generate_report(
    *,
    project_root: Path,
    logs_root: Path,
    output_root: Path,
    today: date | None = None,
    current_modules: Iterable[str] | None = None,
    fixture_mode: bool = False,
) -> Path:
    """Internal injection points support isolated fixtures; the CLI exposes none."""
    report_date = today or _today_shanghai()
    if report_date < _RELEASE_DATE:
        raise CoverageError(
            f"仅允许在 {_RELEASE_DATE.isoformat()} 或之后生成；Asia/Shanghai 当前日期为 {report_date}."
        )

    logs = _dated_logs(logs_root, report_date)
    observed_logs = [item for item in logs if item.modules]
    if not observed_logs:
        raise CoverageError("没有有效的真实运行日志记录。")
    first_day = observed_logs[0].day
    elapsed = (report_date - first_day).days
    if elapsed < _MIN_SPAN_DAYS:
        raise CoverageError(f"真实观察窗口跨度为 {elapsed} 天，至少需要 {_MIN_SPAN_DAYS} 天。")

    current_date_log = next((item for item in logs if item.day == report_date), None)
    window_logs = [item for item in observed_logs if first_day <= item.day <= report_date]
    window_modules = set().union(*(item.modules for item in window_logs))
    current_modules = _current_modules(current_modules)
    rows = _source_inventory(project_root)
    for row in rows:
        module = str(row["module"])
        classification = _classification(module, window_modules, current_modules)
        row.update(
            classification=classification,
            observed_in_window=module in window_modules,
            observed_in_current_process=module in current_modules,
        )

    missing_past_dates = [
        (first_day + timedelta(days=offset)).isoformat()
        for offset in range(elapsed)
        if first_day + timedelta(days=offset) not in {item.day for item in observed_logs}
    ]
    anomalies = [
        {
            "date": item.day.isoformat(),
            "invalid_line_count": len(item.invalid_lines),
            "invalid_line_numbers": list(item.invalid_lines),
        }
        for item in logs
        if item.invalid_lines
    ]
    invalid_dates = [item.day.isoformat() for item in logs if not item.modules]
    categories = {name: [row for row in rows if row["classification"] == name] for name in {
        "observed_in_observation_window",
        "observed_in_current_report_process_only",
        "not_observed_in_window_or_current_process",
        "entrypoint_visibility_indeterminate",
    }}
    totals = {
        "source_modules": len(rows),
        "source_lines": sum(int(row["line_count"]) for row in rows),
        "observed_in_window": len(categories["observed_in_observation_window"]),
        "observed_lines": sum(int(row["line_count"]) for row in categories["observed_in_observation_window"]),
        "current_process_only": len(categories["observed_in_current_report_process_only"]),
        "not_observed": len(categories["not_observed_in_window_or_current_process"]),
        "not_observed_lines": sum(int(row["line_count"]) for row in categories["not_observed_in_window_or_current_process"]),
        "entrypoints": len(categories["entrypoint_visibility_indeterminate"]),
        "entrypoint_lines": sum(int(row["line_count"]) for row in categories["entrypoint_visibility_indeterminate"]),
    }
    observed_dates = [item.day.isoformat() for item in observed_logs]
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "PARTIAL_OBSERVATION" if missing_past_dates or anomalies or invalid_dates else "OBSERVATIONAL_SNAPSHOT",
        "evidence_context": "fixture" if fixture_mode else "production_observation",
        "report_date": report_date.isoformat(),
        "release_not_before": _RELEASE_DATE.isoformat(),
        "minimum_elapsed_observation_days": _MIN_SPAN_DAYS,
        "current_date_log": {
            "date": report_date.isoformat(),
            "exists": current_date_log is not None,
            "sha256": current_date_log.sha256 if current_date_log else None,
            "byte_count": current_date_log.byte_count if current_date_log else None,
            "note": "May be absent because this CLI process appends its own module set at exit.",
        },
        "observation_window": {
            "first_log_date": first_day.isoformat(),
            "through_date": report_date.isoformat(),
            "elapsed_calendar_days": elapsed,
            "observed_log_dates": observed_dates,
            "observed_log_day_count": len(observed_dates),
            "missing_past_log_dates": missing_past_dates,
            "fourteen_distinct_log_days_required": False,
        },
        "runtime_log_manifest": [
            {
                "date": item.day.isoformat(),
                "path": item.path.relative_to(project_root).as_posix()
                if item.path.is_relative_to(project_root)
                else str(item.path),
                "sha256": item.sha256,
                "byte_count": item.byte_count,
                "valid_module_count": len(item.modules),
                "invalid_line_count": len(item.invalid_lines),
            }
            for item in logs
        ],
        "log_anomalies": anomalies,
        "invalid_log_dates": invalid_dates,
        "runtime_log_semantics": {
            "dated_log_union_not_per_invocation": True,
            "records_dotted_quant_modules_on_normal_process_exit": True,
            "other_unexited_long_lived_processes_not_fully_observed": True,
            "root_quant_and_main_entrypoints_indeterminate": True,
        },
        "totals": totals,
        "modules": rows,
    }
    output_dir = output_root / report_date.isoformat()
    if output_dir.exists():
        raise CoverageError(f"报告目录已存在，拒绝覆盖：{output_dir}")

    json_text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    csv_text = _csv(rows)
    markdown_text = _markdown(report, rows)
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise CoverageError(f"报告目录已存在，拒绝覆盖：{output_dir}") from exc
    for name, content in (
        ("runtime_import_coverage.csv", csv_text),
        ("runtime_import_coverage.json", json_text),
        ("runtime_import_coverage.md", markdown_text),
    ):
        try:
            _write_exclusive(output_dir / name, content)
        except OSError as exc:
            raise CoverageError(f"报告输出不完整，请人工检查目录：{output_dir}") from exc
    return output_dir


def _locations() -> tuple[Path, Path, Path]:
    from quant.core.paths import project_paths

    paths = project_paths()
    return paths.root, _log_root(paths.root, paths.artifacts), paths.artifacts / "runtime_import_coverage"


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="quant report runtime-import-coverage",
        description="Inventory source modules against the real runtime-import log window.",
    ).parse_args(argv)
    try:
        project_root, logs_root, output_root = _locations()
        output = _generate_report(project_root=project_root, logs_root=logs_root, output_root=output_root)
    except CoverageError as exc:
        print(f"runtime-import-coverage blocked: {exc}", file=sys.stderr)
        return 2
    print(f"runtime-import-coverage written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
