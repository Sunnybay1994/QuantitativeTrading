from __future__ import annotations

from pathlib import Path

from quant.data import backfill_hk_history


def test_cli_reports_stable_plan_error(tmp_path: Path, capsys: object) -> None:
    exit_code = backfill_hk_history.main(["--plan", str(tmp_path / "missing.json")])
    assert exit_code == 1
    # capsys is deliberately typed opaquely so the CLI test has no pytest-only API contract.
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err.strip() == "HK_HISTORY_PLAN_CONFLICT"
