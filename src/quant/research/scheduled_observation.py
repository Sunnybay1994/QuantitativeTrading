"""Run the existing daily observation CLI from Windows Task Scheduler."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import tomllib
from pathlib import Path

from quant.data.refresh import SHANGHAI, latest_session

DEFAULT_CONFIG = Path("configs/research/daily_observation_q2_sue_v2_20260912.toml")
DEFAULT_ROOT = Path("artifacts/daily/sue_v2")


def completed_record(root: Path, date: str) -> Path | None:
    """Only actual same-day forward records count as already done."""
    for path in sorted(root.glob("*/summary.json"), reverse=True):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            execution = path.parent / "scheduler.json"
            if (
                execution.exists()
                and json.loads(execution.read_text(encoding="utf-8")).get("exit_code") != 0
            ):
                continue
        except (OSError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        if (
            value.get("as_of") == date
            and value.get("status") == "complete"
            and value.get("rehearsal") is False
            and value.get("saved_data") is False
        ):
            return path
    return None


def run(
    *,
    config: Path = DEFAULT_CONFIG,
    root: Path = DEFAULT_ROOT,
    check_only: bool = False,
    now: dt.datetime | None = None,
) -> dict:
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    if settings.get("auto_trade") is not False:
        raise ValueError("Scheduled observation requires auto_trade=false")
    for path in (settings["refresh_config"], settings["model"]["selection"]):
        if not Path(path).exists():
            raise FileNotFoundError(path)
    if check_only:
        return {"status": "checked", "python": sys.executable, "config": str(config.resolve())}
    clock = (now or dt.datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    if clock.date() < dt.date(2026, 9, 14) or clock.hour < 17:
        return {"status": "skipped", "reason": "Before forward start or daily close cutoff"}
    end = latest_session(data_root=Path(settings["data_root"]), through=clock.date())
    if end != clock.date():
        return {"status": "skipped", "reason": "No completed exchange session today"}
    date = str(end)
    if settings.get('q10'):
        from quant.execution.q10_paper import EXECUTION_READY_HOUR
        if clock.hour < EXECUTION_READY_HOUR:
            from quant.data.realtime_store import atomic_json
            result = dict(status='deferred', as_of=date,
                          reason='Q10 requires completed same-session execution inputs; full observation waits for the evening trigger',
                          not_before=clock.replace(hour=EXECUTION_READY_HOUR,minute=0,second=0,microsecond=0).isoformat(),
                          next_scheduled_run='21:30 Asia/Shanghai', auto_trade=False)
            atomic_json(root / f'{date}_waiting_inputs.json', result)
            return result
    record = completed_record(root, date)
    observation_code = 0
    if record is None:
        output = root / clock.strftime("%Y-%m-%d_%H%M%S_%f")
        # Keep process logs beside the new CLI-owned directory.
        root.mkdir(parents=True, exist_ok=True)
        with (root / (output.name + ".log")).open("w", encoding="utf-8") as log:
            observation_code = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "quant.research.run_daily_observation",
                    "--config",
                    str(config),
                    "--to",
                    date,
                    "--output",
                    str(output),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            ).returncode
        if output.exists():
            (output / "scheduler.json").write_text(
                json.dumps({"exit_code": observation_code}), encoding="utf-8"
            )
        record = output / "summary.json"
    value = json.loads(record.read_text(encoding="utf-8"))
    if value.get("as_of") != date or value.get("rehearsal") is not False:
        raise ValueError("Observation output does not match scheduled forward session")
    s0_code = None
    s0_status = root / f"{date}_s0.json"
    if value.get("stages", {}).get("refresh", {}).get("status") == "complete":
        # The S0 CLI owns same-day no-op, halt/sell-only and its forward start.
        try:
            previous = json.loads(s0_status.read_text(encoding="utf-8")) if s0_status.exists() else {}
        except ValueError:
            # This is only the scheduler's completion hint. The S0 ledger remains
            # authoritative and its own no-op makes recovery safe after interruption.
            previous = {}
        if not isinstance(previous, dict):
            previous = {}
        if previous.get("exit_code") == 0:
            s0_code = 0
        else:
            with (root / f"{date}_s0.log").open("a", encoding="utf-8") as log:
                s0_code = subprocess.run(
                    [sys.executable, "-m", "quant.execution.paper_ledger", "--to", date],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                ).returncode
            s0_status.write_text(json.dumps({"date": date, "exit_code": s0_code}), encoding="utf-8")
    complete = observation_code == 0 and value.get("status") == "complete" and s0_code == 0
    market_context = {"status": "skipped", "reason": "Daily observation not complete"}
    if complete:
        try:
            from quant.research.daily_market_context import run as market_context_run
            market_context = market_context_run(data_root=Path(settings['data_root']), now=clock)
        except Exception as exc:
            # Context failure is visible but must not invalidate existing account output.
            market_context = {"status": "failed", "error": type(exc).__name__+": "+str(exc)}
    return {
        "status": "complete" if complete else "incomplete",
        "as_of": date,
        "record": str(record),
        "observation_exit_code": observation_code,
        "s0_exit_code": s0_code,
        "requires_review": value.get("requires_review", True),
        "market_context": market_context,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--check-only", action="store_true")
    result = run(**vars(parser.parse_args()))
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] == "incomplete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
