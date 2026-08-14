"""R3 scheduler wrapper probes; valid dates run only against a fake command."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

_RUNNER = Path(__file__).parents[2] / "scripts" / "run_m1_daily_streak_20260810_20260814.sh"
_CONDA = "/home/mabw/miniforge3/bin/conda"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fixture_runner(tmp_path: Path, *, timeout: str = "20m") -> Path:
    project = tmp_path / "project"
    runner = project / "scripts" / _RUNNER.name
    runner.parent.mkdir(parents=True)
    fake = tmp_path / "fake-conda"
    _write_executable(
        fake,
        """#!/usr/bin/env bash
set -eu
date='missing'
for ((i=1; i<=$#; i++)); do
  if [ "${!i}" = '--date' ]; then j=$((i+1)); date="${!j}"; fi
done
printf 'start %s\\n' "$date" >> "$TRACE_PATH"
sleep "${FAKE_SLEEP:-0.2}"
printf 'end %s\\n' "$date" >> "$TRACE_PATH"
printf '{"status":"SUCCESS"}\\n'
""",
    )
    source = _RUNNER.read_text(encoding="utf-8")
    source = source.replace(_CONDA, str(fake)).replace("20m", timeout)
    _write_executable(runner, source)
    return runner


@pytest.mark.skipif(os.name == "nt", reason="requires Linux bash/flock/timeout")
def test_missed_fixed_date_jobs_serialize_without_duplicate_crossing(
    tmp_path: Path,
) -> None:
    runner = _fixture_runner(tmp_path)
    trace = tmp_path / "trace"
    env = {**os.environ, "TRACE_PATH": str(trace), "FAKE_SLEEP": "0.3"}
    first = subprocess.Popen(
        ["bash", str(runner), "2026-08-10"], env=env
    )
    second = subprocess.Popen(
        ["bash", str(runner), "2026-08-11"], env=env
    )
    assert first.wait(timeout=10) == 0
    assert second.wait(timeout=10) == 0
    lines = trace.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert lines[0].startswith("start ") and lines[1].startswith("end ")
    assert lines[2].startswith("start ") and lines[3].startswith("end ")
    assert {line.removeprefix("start ") for line in (lines[0], lines[2])} == {
        "2026-08-10",
        "2026-08-11",
    }


@pytest.mark.skipif(os.name == "nt", reason="requires Linux bash/flock/timeout")
def test_inner_timeout_writes_stable_nonempty_failure(tmp_path: Path) -> None:
    runner = _fixture_runner(tmp_path, timeout="0.1s")
    trace = tmp_path / "trace"
    result = subprocess.run(
        ["bash", str(runner), "2026-08-12"],
        env={**os.environ, "TRACE_PATH": str(trace), "FAKE_SLEEP": "1"},
        check=False,
        timeout=10,
    )
    assert result.returncode == 2
    log = (
        runner.parents[1]
        / "artifacts/data_quality/m1_daily_streak/20260810_20260814/2026-08-12.json"
    )
    assert log.read_text(encoding="utf-8") == (
        '{"status":"FAILED","code":"M1_SCHEDULE_PROCESS_FAILED"}\n'
    )


@pytest.mark.skipif(os.name == "nt", reason="requires Linux bash")
def test_invalid_date_exits_before_any_artifact_write(tmp_path: Path) -> None:
    runner = _fixture_runner(tmp_path)
    result = subprocess.run(
        ["bash", str(runner), "2026-08-15"], check=False, timeout=10
    )
    assert result.returncode == 65
    assert not (runner.parents[1] / "artifacts").exists()
