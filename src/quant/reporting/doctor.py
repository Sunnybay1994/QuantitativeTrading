"""Read-only daily acceptance page. Does not repair red items."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from quant.core.paths import project_paths

SHANGHAI = ZoneInfo("Asia/Shanghai")
_STEPS = ("N1", "N2", "N3", "N4", "N5")
_TASK_SCRIPT = r"""
$tasks = @(Get-ScheduledTask | Where-Object { $_.TaskName -like 'Quant*' })
$rows = foreach ($t in $tasks) {
  $i = Get-ScheduledTaskInfo -InputObject $t
  [pscustomobject]@{
    name = $t.TaskName
    last_run_time = $i.LastRunTime.ToString('o')
    result = [int]$i.LastTaskResult
  }
}
if ($rows) { $rows | ConvertTo-Json -Compress } else { '[]' }
"""


def _now(now: dt.datetime | None) -> dt.datetime:
    clock = now or dt.datetime.now(SHANGHAI)
    return clock.astimezone(SHANGHAI)


def _read_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _token_count(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        if isinstance(value.get("total_tokens"), (int, float)):
            return float(value["total_tokens"])
        return float(sum(v for v in value.values() if isinstance(v, (int, float)) and not isinstance(v, bool)))
    return 0


def windows_scheduled_tasks() -> list[dict]:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", _TASK_SCRIPT],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "scheduled task query failed")[:400])
    payload = json.loads(completed.stdout or "[]")
    if isinstance(payload, dict):
        payload = [payload]
    return list(payload)


def _latest_open(data: Path, day: dt.date) -> dt.date | None:
    path = data / "clean" / "trade_calendar" / "market=SH" / "data.parquet"
    if not path.exists():
        return None
    frame = pl.read_parquet(path, columns=["date", "is_open"])
    dates = frame.filter(pl.col("is_open")).get_column("date").to_list()
    open_days = []
    for value in dates:
        current = value.date() if isinstance(value, dt.datetime) else value
        if current <= day:
            open_days.append(current)
    return max(open_days) if open_days else None


def _outside_repo(run_path: str, root: Path) -> bool:
    path = Path(run_path)
    if not path.is_absolute():
        path = root / path
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    return False


def _git_facts(root: Path) -> dict:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    dirty = 0 if status.returncode != 0 else len([line for line in status.stdout.splitlines() if line.strip()])
    stamp = subprocess.run(
        ["git", "log", "-1", "--format=%ct"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    days = None
    if stamp.returncode == 0 and stamp.stdout.strip().isdigit():
        committed = dt.datetime.fromtimestamp(int(stamp.stdout.strip()), SHANGHAI)
        days = (_now(None) - committed).days
    scratch = len(list(root.glob("_*.py")))
    return {"dirty": dirty, "days_since_commit": days, "root_scratch_py": scratch, "git_ok": status.returncode == 0}


def _mining(continuous: Path, today: dt.date) -> dict:
    status = _read_json(continuous / "status.json") or {}
    latest: dt.date | None = None
    batch = None
    if continuous.exists():
        for summary_path in continuous.glob("batch_*/*/summary.json"):
            payload = _read_json(summary_path)
            if not payload:
                continue
            steps = payload.get("steps") or {}
            if not all((steps.get(step) or {}).get("ok") for step in _STEPS):
                continue
            try:
                day = dt.date.fromisoformat(summary_path.parent.name[:10])
            except ValueError:
                continue
            if latest is None or day > latest:
                latest, batch = day, summary_path.parent.parent.name
    age = None if latest is None else (today - latest).days
    return {
        "failure_kind": status.get("failure_kind"),
        "consecutive_failures": status.get("consecutive_failures"),
        "state": status.get("state"),
        "last_completed_batch": batch,
        "last_completed_on": None if latest is None else latest.isoformat(),
        "days_since_completed": age,
    }


def _registry(path: Path, root: Path) -> dict:
    if not path.exists():
        return {"rows": 0, "outside": None, "duplicate_keys": None, "missing": True}
    frame = pl.read_parquet(path, columns=["run_path", "experiment_id", "variant"])
    outside = 0
    for value in frame.get_column("run_path").to_list():
        if _outside_repo(str(value), root):
            outside += 1
    grouped = frame.group_by(["experiment_id", "variant"]).len()
    duplicates = grouped.filter(pl.col("len") > 1).height
    return {"rows": frame.height, "outside": outside, "duplicate_keys": duplicates, "missing": False}


def _ledger(path: Path) -> dict:
    if not path.exists():
        return {"rows": 0, "zero_usd_with_tokens": 0, "spend_usd": 0.0, "missing": True}
    zero = 0
    spend = 0.0
    rows = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows += 1
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        usd = float(item.get("usd") or 0)
        spend += usd
        if usd == 0 and _token_count(item.get("tokens")) > 0:
            zero += 1
    return {"rows": rows, "zero_usd_with_tokens": zero, "spend_usd": round(spend, 4), "missing": False}


def _tests(path: Path, today: dt.date) -> dict:
    payload = _read_json(path)
    if not payload:
        return {"missing": True}
    ran = str(payload.get("ran_at") or "")
    try:
        ran_day = dt.datetime.fromisoformat(ran).astimezone(SHANGHAI).date()
        age = (today - ran_day).days
    except ValueError:
        age = None
    return {
        "missing": False,
        "exit_code": payload.get("exit_code"),
        "passed": payload.get("passed"),
        "failed": payload.get("failed"),
        "duration_seconds": payload.get("duration_seconds"),
        "age_days": age,
    }


def collect(
    *,
    root: Path | None = None,
    now: dt.datetime | None = None,
    tasks: list[dict] | None = None,
) -> dict:
    """Build the doctor page. ``tasks`` injects scheduler rows in tests."""
    paths = project_paths()
    root = (root or paths.root).resolve()
    artifacts = root / "artifacts"
    clock = _now(now)
    today = clock.date()
    session = _latest_open(root / "data", today)
    daily_dir = None
    daily_status = None
    if session is not None:
        matches = sorted((artifacts / "daily" / "sue_v2").glob(f"{session.isoformat()}_*"))
        if matches:
            daily_dir = matches[-1]
            summary = _read_json(daily_dir / "summary.json") or {}
            daily_status = summary.get("status")
    q10_state = None
    if session is not None:
        candidate = artifacts / "paper" / "q10_sue_v2" / session.isoformat() / "state.json"
        q10_state = candidate.exists()
    if tasks is None:
        try:
            tasks = windows_scheduled_tasks()
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, RuntimeError) as exc:
            tasks = [{"name": "query", "last_run_time": None, "result": None, "error": str(exc)[:300]}]
    scheduled = []
    for row in tasks:
        result = row.get("result")
        scheduled.append({
            "name": row.get("name"),
            "last_run_time": row.get("last_run_time"),
            "result": result,
            "ok": result == 0,
            "error": row.get("error"),
        })
    mining = _mining(artifacts / "research" / "continuous", today)
    registry = _registry(artifacts / "registry" / "experiments.parquet", root)
    month = clock.strftime("%Y-%m")
    ledger = _ledger(artifacts / "research" / "llm_ledger" / f"{month}.jsonl")
    git_facts = _git_facts(root)
    tests = _tests(artifacts / "tests" / "latest.json", today)
    red: list[str] = []
    if not scheduled:
        red.append("scheduled_tasks: none")
    for row in scheduled:
        if not row["ok"]:
            red.append(f"scheduled_tasks: {row['name']} result={row['result']}")
    if session is None:
        red.append("daily: no SH calendar")
    elif daily_status != "complete":
        red.append(f"daily: {session.isoformat()} status={daily_status}")
    if not q10_state:
        red.append(f"daily: q10 state.json missing for {session}")
    age = mining["days_since_completed"]
    if age is None or age > 5:
        red.append(f"mining: last completed {mining['last_completed_on']} age={age}")
    if registry["missing"] or (registry["outside"] or 0) > 0:
        red.append(f"registry: outside={registry['outside']}")
    if (registry["duplicate_keys"] or 0) > 0:
        red.append(f"registry: duplicate experiment_id+variant={registry['duplicate_keys']}")
    if ledger["zero_usd_with_tokens"] > 0:
        red.append(f"llm: usd=0 and tokens>0 rows={ledger['zero_usd_with_tokens']}")
    if not git_facts["git_ok"] or git_facts["dirty"] > 20:
        red.append(f"git: dirty={git_facts['dirty']}")
    if git_facts["days_since_commit"] is None or git_facts["days_since_commit"] > 2:
        red.append(f"git: days_since_commit={git_facts['days_since_commit']}")
    if git_facts["root_scratch_py"] > 0:
        red.append(f"git: root _*.py={git_facts['root_scratch_py']}")
    if tests.get("missing") or tests.get("exit_code") not in (0, "0"):
        red.append(f"tests: latest={tests.get('exit_code')}")
    elif (tests.get("age_days") or 0) > 2:
        red.append(f"tests: age_days={tests['age_days']}")
    return {
        "generated_at": clock.isoformat(),
        "date": today.isoformat(),
        "session_date": None if session is None else session.isoformat(),
        "red": red,
        "scheduled_tasks": scheduled,
        "daily": {"status": daily_status, "run": None if daily_dir is None else str(daily_dir), "q10_state": bool(q10_state)},
        "mining": mining,
        "registry": registry,
        "llm": ledger,
        "git": git_facts,
        "tests": tests,
    }


def render_markdown(report: dict) -> str:
    lines = [
        f"# quant doctor {report['date']}",
        "",
        f"红项 {len(report['red'])}。本页只读，不修复。",
        "",
    ]
    for item in report["red"]:
        lines.append(f"- {item}")
    lines.extend(["", "## scheduled_tasks", "", "| name | result | last_run |", "|---|---:|---|"])
    for row in report["scheduled_tasks"]:
        lines.append(f"| {row['name']} | {row['result']} | {row['last_run_time']} |")
    lines.extend([
        "",
        "## 其他",
        "",
        f"- daily: session={report['session_date']} status={report['daily']['status']} q10_state={report['daily']['q10_state']}",
        f"- mining: batch={report['mining']['last_completed_batch']} on={report['mining']['last_completed_on']} age={report['mining']['days_since_completed']} failures={report['mining']['consecutive_failures']} kind={report['mining']['failure_kind']}",
        f"- registry: rows={report['registry']['rows']} outside={report['registry']['outside']} duplicate_keys={report['registry']['duplicate_keys']}",
        f"- llm: spend_usd={report['llm']['spend_usd']} zero_usd_with_tokens={report['llm']['zero_usd_with_tokens']}",
        f"- git: dirty={report['git']['dirty']} days_since_commit={report['git']['days_since_commit']} root_scratch_py={report['git']['root_scratch_py']}",
        f"- tests: exit={report['tests'].get('exit_code')} passed={report['tests'].get('passed')} age_days={report['tests'].get('age_days')}",
        "",
    ])
    return "\n".join(lines)


def write_report(report: dict, artifacts: Path) -> tuple[Path, Path]:
    folder = artifacts / "doctor"
    folder.mkdir(parents=True, exist_ok=True)
    stem = folder / report["date"]
    json_path = stem.with_suffix(".json")
    md_path = stem.with_suffix(".md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def notify_red(report: dict) -> None:
    if not report["red"]:
        return
    from quant.notify import send

    body = "\n".join(report["red"])[:3500]
    send(f"quant doctor {report['date']} 红项 {len(report['red'])}", body)


def record_fast_tests(root: Path | None = None) -> int:
    """Run the fast suite and store the receipt the doctor reads. Does not gate trading."""
    root = (root or project_paths().root).resolve()
    destination = root / "artifacts" / "tests"
    destination.mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(SHANGHAI)
    clock = dt.datetime.now()
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "-m", "not slow", "--tb=no"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = (completed.stdout or "") + "\n" + (completed.stderr or "")
    passed = failed = 0
    for line in text.splitlines():
        if " passed" in line or " failed" in line:
            parts = line.replace(",", " ").split()
            for index, token in enumerate(parts):
                if token == "passed" and index:
                    passed = int(parts[index - 1])
                if token == "failed" and index:
                    failed = int(parts[index - 1])
    payload = {
        "ran_at": started.isoformat(),
        "command": "pytest -m \"not slow\"",
        "exit_code": completed.returncode,
        "passed": passed,
        "failed": failed,
        "duration_seconds": round((dt.datetime.now() - clock).total_seconds(), 1),
    }
    (destination / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quant doctor")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--record-tests", action="store_true")
    args = parser.parse_args(argv)
    if args.record_tests:
        return record_fast_tests()
    report = collect()
    json_path, md_path = write_report(report, project_paths().artifacts)
    if not args.no_notify:
        notify_red(report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report))
        print(f"json={json_path}")
        print(f"md={md_path}")
    return 0
