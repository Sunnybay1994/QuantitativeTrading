"""Fast-suite receipts use temporary roots and never launch the real suite."""

import json
import subprocess

import pytest

from quant.reporting import doctor


@pytest.mark.parametrize("timeout", [False, True])
def test_fast_suite_keeps_output_and_enforces_ten_minutes(tmp_path, monkeypatch, timeout):
    def run(command, **kwargs):
        assert kwargs["cwd"] == tmp_path.resolve()
        assert kwargs["timeout"] == 600
        assert command[-1] == "--tb=no"
        if timeout:
            raise subprocess.TimeoutExpired(command, 600, output=b"partial output", stderr=b"error detail")
        return subprocess.CompletedProcess(command, 1, "2 passed, 1 failed in 0.1s", "failure detail")

    monkeypatch.setattr(doctor.subprocess, "run", run)
    code = doctor.record_fast_tests(tmp_path)
    receipt = json.loads((tmp_path / "artifacts/tests/latest.json").read_text())
    log = tmp_path / receipt["log"]
    assert log.is_file()
    assert receipt["timeout_seconds"] == 600
    assert receipt["exit_code"] == code == (124 if timeout else 1)
    text = log.read_text(encoding="utf-8")
    if timeout:
        assert "partial output" in text and "error detail" in text
        assert "timeout after 600s" in text
    else:
        assert receipt["passed"] == 2 and receipt["failed"] == 1
        assert "failure detail" in text
