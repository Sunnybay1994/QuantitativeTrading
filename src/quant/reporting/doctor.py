"""Read-only daily acceptance page. Does not repair red items."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from quant.core.paths import project_paths

SHANGHAI = ZoneInfo("Asia/Shanghai")
_STEPS = ("N1", "N2", "N3", "N4", "N5")
_TASK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
# Disabled tasks are retired from the acceptance page; never-run codes on them are not red.
$tasks = @(Get-ScheduledTask | Where-Object { $_.TaskName -like 'Quant*' -and $_.State -ne 'Disabled' })
$rows = foreach ($t in $tasks) {
  $i = Get-ScheduledTaskInfo -InputObject $t
  [pscustomobject]@{
    name = $t.TaskName
    state = [string]$t.State
    last_run_time = $i.LastRunTime.ToString('o')
    next_run_time = if ($i.NextRunTime) { $i.NextRunTime.ToString('o') } else { $null }
    result = [long]$i.LastTaskResult
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
        errors="replace",
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
    from quant.llm.ledger import priced_rows

    raw, errors = [], []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            try:
                raw.append(json.loads(line))
            except json.JSONDecodeError:
                errors.append('invalid JSON ledger line')
    calls = [r for r in raw if r.get('kind') != 'pricing_adjustment']
    try:
        priced = priced_rows(path)
    except (ValueError, TypeError) as exc:
        errors.append(str(exc))
        priced = calls
    def zero(rows):
        return sum(not r.get('usd') and _token_count(r.get('tokens')) > 0 for r in rows)
    return {'rows': len(priced), 'raw_rows': len(raw), 'zero_usd_with_tokens': zero(priced),
            'raw_zero_usd_with_tokens': zero(calls),
            'pricing_adjustments': len(raw)-len(calls), 'pricing_errors': errors,
            'spend_usd': round(sum(float(r.get('usd') or 0) for r in priced), 4), 'missing': False}


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
    duration = payload.get('duration_seconds')
    count, passed, skipped = (payload.get(name) for name in ('selected_count', 'passed', 'skipped'))
    verified = (payload.get('complete') is True and payload.get('accepted_fast') is True
        and payload.get('failed') == 0 and payload.get('errors') == 0
        and all(type(value) is int and value >= 0 for value in (count, passed, skipped))
        and count > 0 and passed + skipped == count
        and type(duration) in (int, float) and 0 <= duration <= 900
        and age is not None and 0 <= age <= 2)
    return {
        "missing": False,
        "exit_code": payload.get("exit_code"),
        "passed": payload.get("passed"),
        "failed": payload.get("failed"),
        "duration_seconds": payload.get("duration_seconds"),
        "age_days": age,
        "verified_fast_receipt": verified,
    }


def _coverage(path: Path) -> dict:
    payload = _read_json(path)
    if not payload:
        return {"missing": True, "rows": []}
    return {"missing": False, "rows": list(payload.get("rows") or [])}


def _post_close_scheduler(path: Path, clock: dt.datetime) -> dict:
    """Flag silent post-close yields: deferred* with exit 0 used to hide missed US sessions."""
    payload = _read_json(path) or {}
    status = payload.get("status")
    result = {"path": str(path), "status": status, "updated_at": payload.get("updated_at"),
              "markets": payload.get("markets"), "red": None}
    if status not in ("deferred", "deferred_timeout", "deferred_waiting"):
        return result
    updated = payload.get("updated_at")
    try:
        when = dt.datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=SHANGHAI)
        age_hours = (clock - when.astimezone(SHANGHAI)).total_seconds() / 3600
    except (TypeError, ValueError):
        age_hours = None
    # Active wait is informational; terminal defer within 36h is a red item.
    if status == "deferred_waiting":
        return result
    if age_hours is None or age_hours <= 36:
        markets = payload.get("markets") or "?"
        result["red"] = f"post_close: scheduler {status} markets={markets}"
    return result


def collect(
    *,
    root: Path | None = None,
    now: dt.datetime | None = None,
    tasks: list[dict] | None = None,
    history: dict | None = None,
) -> dict:
    """Build the doctor page. ``tasks`` injects scheduler rows in tests."""
    paths = project_paths()
    root = (root or paths.root).resolve()
    artifacts = root / "artifacts"
    clock = _now(now)
    today = clock.date()
    from quant.data.refresh import completed_date

    session = _latest_open(root / "data", completed_date('today', clock))
    daily_dir = None
    daily_status = None
    daily_error = None
    if session is not None:
        matches = []
        for path in sorted((artifacts / "daily" / "sue_v2").glob('*')):
            if not path.is_dir():
                continue
            summary = _read_json(path / 'summary.json') or {}
            # Catch-up directories use the actual recording date. Keep same-day
            # unfinished directories too, so a new attempt cannot inherit green.
            if summary.get('as_of') == session.isoformat() or path.name.startswith(f'{session.isoformat()}_'):
                matches.append((path, summary))
        if matches:
            daily_dir, summary = matches[-1]
            daily_status = summary.get("status")
            if not summary:
                daily_error = 'summary missing or invalid'
            elif summary.get('as_of') != session.isoformat():
                daily_error = 'summary session mismatch'
            elif any(summary.get(key) is not False for key in ('rehearsal','saved_data','auto_trade')):
                daily_error = 'live-data observation mode not verified'
            elif (daily_dir/'summary.json').stat().st_mtime > clock.timestamp():
                daily_error = 'summary not yet available at acceptance time'
            elif (daily_dir/'scheduler.json').exists():
                execution = _read_json(daily_dir/'scheduler.json') or {}
                if execution.get('exit_code') != 0:
                    daily_error = 'observation process did not finish successfully'
            pair = (summary.get('stages') or {}).get('q10_pair_month')
            if not daily_error and pair is not None:
                pair_result = pair.get('result') or {}
                if pair.get('status') != 'complete':
                    daily_error = 'pair month stage did not complete'
                elif pair_result.get('status') == 'waiting':
                    if pair_result.get('reason_code') != 'insufficient_monthly_sample':
                        daily_error = 'pair month waiting reason is not verified'
                elif pair_result.get('status') != 'complete':
                    daily_error = 'pair month result did not complete'
            if daily_error and summary:
                daily_status = 'invalid_record'
    q10_state = None
    if session is not None:
        candidate = artifacts / "paper" / "q10_sue_v2" / session.isoformat() / "state.json"
        q10_state = candidate.exists()
    live_scheduler = tasks is None
    if tasks is None:
        try:
            tasks = windows_scheduled_tasks()
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, RuntimeError) as exc:
            tasks = [{"name": "query", "last_run_time": None, "result": None, "error": str(exc)[:300]}]
    if history is None:
        if live_scheduler:
            from quant.reporting.doctor_scheduler import read_history

            history = read_history()
        else:
            history = {'enabled': None, 'instances': [], 'events': [], 'error': None,
                       'artifact_validation': 'not_evaluated', 'injected_scheduler': True}
    scheduled = []
    for row in tasks:
        result = row.get("result")
        state = row.get("state")
        # A live run is not a failed completion; ContinuousMining often shows
        # ERROR_INVALID_STATE / SCHED_S_TASK_RUNNING while the worker holds the slot.
        running = isinstance(state, str) and state.lower() == "running"
        pending = False
        if result == 267011 and row.get('next_run_time'):
            try:
                next_run = dt.datetime.fromisoformat(row['next_run_time'])
                pending = next_run.replace(tzinfo=next_run.tzinfo or SHANGHAI) > clock
            except (ValueError, TypeError):
                pass
        scheduled.append({
            "name": row.get("name"),
            "state": state,
            "last_run_time": row.get("last_run_time"),
            "result": result,
            "ok": result == 0 or running or pending,
            "pending_first_run": pending,
            "next_run_time": row.get('next_run_time'),
            "error": row.get("error"),
        })
    mining = _mining(artifacts / "research" / "continuous", today)
    registry = _registry(artifacts / "registry" / "experiments.parquet", root)
    month = clock.strftime("%Y-%m")
    ledger = _ledger(artifacts / "research" / "llm_ledger" / f"{month}.jsonl")
    git_facts = _git_facts(root)
    tests = _tests(artifacts / "tests" / "latest.json", today)
    red: list[str] = []
    if history.get('error') or history.get('enabled') is False or history.get('truncated'):
        red.append('scheduled_history: native event evidence unavailable or truncated')
    if not scheduled:
        red.append("scheduled_tasks: none")
    for row in scheduled:
        if not row["ok"]:
            detail = f": {row['error']}" if row.get("error") else ""
            red.append(f"scheduled_tasks: {row['name']} result={row['result']}{detail}")
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
    if ledger.get('pricing_errors'):
        red.append('llm: invalid pricing adjustments or ledger lines')
    if not git_facts["git_ok"] or git_facts["dirty"] > 20:
        red.append(f"git: dirty={git_facts['dirty']}")
    if git_facts["days_since_commit"] is None or git_facts["days_since_commit"] > 2:
        red.append(f"git: days_since_commit={git_facts['days_since_commit']}")
    if git_facts["root_scratch_py"] > 0:
        red.append(f"git: root _*.py={git_facts['root_scratch_py']}")
    if tests.get("missing") or tests.get("exit_code") not in (0, "0"):
        red.append(f"tests: latest={tests.get('exit_code')}")
    elif not tests.get('verified_fast_receipt'):
        red.append('tests: incomplete or invalid fast-test receipt')
    elif (tests.get("age_days") or 0) > 2:
        red.append(f"tests: age_days={tests['age_days']}")
    if tests.get("duration_seconds") is not None and tests["duration_seconds"] > 900:
        red.append(f"tests: duration_seconds={tests['duration_seconds']} exceeds 900")
    coverage = _coverage(artifacts / "post_close_k1m" / "coverage.json")
    from quant.reporting.doctor_intraday_acceptance import evaluate

    coverage['five_sessions'] = evaluate(root, coverage['rows'], clock)
    from quant.reporting.doctor_events_acceptance import evaluate as evaluate_events

    events = evaluate_events(root, today)
    red.extend('events: '+error for error in events['errors'])
    if coverage['five_sessions']['calendar_gate_met'] and not coverage['five_sessions']['coverage_passed']:
        red.append('coverage: D1 requires five verified consecutive sessions per market')
    latest: dict[str, dict] = {}
    for row in coverage["rows"]:
        latest[row["market"]] = row
    for market, floor in (("cn", 0.95), ("hk", 0.90), ("us", 0.90)):
        row = latest.get(market)
        if row and not row.get("denominator_verified"):
            red.append(f"coverage: {market} {row['date']} full universe unverified")
        if row and row.get("expected") and float(row.get("complete_rate") or 0) < floor:
            red.append(f"coverage: {market} {row['date']} {float(row['complete_rate']):.1%}")
    from quant.data.post_close_k1m import paused_pool_names
    paused_pools = paused_pool_names(root, today)
    for name in paused_pools:
        red.append(f"pool: {name} paused, no consumer for 60 days")
    post_close_scheduler = _post_close_scheduler(
        artifacts / "post_close_k1m" / "scheduler" / "scheduler.json", clock)
    if post_close_scheduler.get("red"):
        red.append(post_close_scheduler["red"])
    from quant.execution.paper_order_status import collect as order_status
    try:
        orders = order_status(root=root, today=today)
    except (OSError, ValueError, KeyError, pl.exceptions.PolarsError) as exc:
        orders = {'next_rebalance': None, 'ready': False, 'error': str(exc)}
    return {
        "orders": orders,
        "generated_at": clock.isoformat(),
        "date": today.isoformat(),
        "session_date": None if session is None else session.isoformat(),
        "red": red,
        "scheduled_tasks": scheduled,
        "scheduled_history": history,
        "daily": {"status": daily_status, "run": None if daily_dir is None else str(daily_dir),
                  "q10_state": bool(q10_state), "receipt_error": daily_error},
        "mining": mining,
        "registry": registry,
        "llm": ledger,
        "git": git_facts,
        "tests": tests,
        "coverage": coverage,
        "events": events,
        "paused_pools": paused_pools,
        "post_close_scheduler": post_close_scheduler,
    }


def render_markdown(report: dict) -> str:
    orders = report.get('orders') or {}
    lines = [
        f"下一调仓日：{orders.get('next_rebalance') or '日历待核对'} / 订单就绪：{'是' if orders.get('ready') else '否'}",
        "",
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
    history = report.get('scheduled_history') or {}
    lines.extend(['', '## scheduled_instances', '',
                  f"Native log enabled={history.get('enabled')}; truncated={history.get('truncated', False)}.",
                  'Exit codes require matching dated products and calendar gates for acceptance.', '',
                  '| task | trigger | started | status | result |', '|---|---|---|---|---:|'])
    for row in history.get('instances', [])[-12:]:
        lines.append(f"| {row['task']} | {row['trigger']} | {row['start_time']} | "
                     f"{row['status']} | {row['result']} |")
    lines.extend([
        "",
        "## 其他",
        "",
        f"- daily: session={report['session_date']} status={report['daily']['status']} q10_state={report['daily']['q10_state']}"
        + (f" error={report['daily']['receipt_error']}" if report['daily'].get('receipt_error') else ''),
        f"- mining: batch={report['mining']['last_completed_batch']} on={report['mining']['last_completed_on']} age={report['mining']['days_since_completed']} failures={report['mining']['consecutive_failures']} kind={report['mining']['failure_kind']}",
        f"- registry: rows={report['registry']['rows']} outside={report['registry']['outside']} duplicate_keys={report['registry']['duplicate_keys']}",
        f"- llm: spend_usd={report['llm']['spend_usd']} zero_usd_with_tokens={report['llm']['zero_usd_with_tokens']}",
        f"- llm pricing: historical_raw_zero={report['llm'].get('raw_zero_usd_with_tokens', 0)} estimated_adjustments={report['llm'].get('pricing_adjustments', 0)}",
        f"- git: dirty={report['git']['dirty']} days_since_commit={report['git']['days_since_commit']} root_scratch_py={report['git']['root_scratch_py']}",
        f"- tests: exit={report['tests'].get('exit_code')} passed={report['tests'].get('passed')} age_days={report['tests'].get('age_days')}",
        "",
    ])
    coverage = report.get("coverage") or {}
    lines.extend(["", "## post_close_coverage", ""])
    rows = coverage.get("rows") or []
    if not rows:
        lines.append("无覆盖回执。")
    else:
        lines.append("| date | market | expected | complete | partial | missing | rate | denominator |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---|")
        for row in rows[-12:]:
            lines.append(
                f"| {row['date']} | {row['market']} | {row['expected']} | {row['complete']} | "
                f"{row['partial']} | {row['missing']} | {float(row['complete_rate']):.1%} | "
                f"{row.get('denominator_basis', 'unverified')} |")
    if coverage.get('five_sessions'):
        from quant.reporting.doctor_intraday_acceptance import markdown

        lines.extend(markdown(coverage['five_sessions']))
    from quant.reporting.doctor_events_acceptance import markdown as events_markdown

    lines.extend(events_markdown(report.get('events') or {}))
    return "\n".join(lines)


def write_report(report: dict, artifacts: Path) -> tuple[Path, Path]:
    folder = artifacts / "doctor"
    folder.mkdir(parents=True, exist_ok=True)
    stem = folder / report["date"]
    json_path = stem.with_suffix(".json")
    md_path = stem.with_suffix(".md")
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    archive = folder / 'runs' / report['date']
    archive.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.fromisoformat(report['generated_at']).strftime('%H%M%S_%f')
    with (archive / f'{stamp}_{uuid.uuid4().hex}.json').open('x', encoding='utf-8') as stream:
        stream.write(payload)
    json_path.write_text(payload, encoding="utf-8")
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
    from quant.reporting.fast_tests import run

    return run((root or project_paths().root).resolve())


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
