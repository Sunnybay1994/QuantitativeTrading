from __future__ import annotations

from pathlib import Path

from quant.data import backfill_hk_history
from quant.data.hk_history_backfill import HKHistoryExecutionResult


def test_cli_reports_stable_plan_error(tmp_path: Path, capsys: object) -> None:
    exit_code = backfill_hk_history.main(["--plan", str(tmp_path / "missing.json")])
    assert exit_code == 1
    # capsys is deliberately typed opaquely so the CLI test has no pytest-only API contract.
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err.strip() == "HK_HISTORY_PLAN_CONFLICT"


def test_cli_recover_existing_only_never_constructs_connector(
    tmp_path: Path, capsys: object, monkeypatch: object
) -> None:
    sentinel = object()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        backfill_hk_history, "load_hk_history_plan", lambda path: sentinel
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        backfill_hk_history.TushareConnector,
        "__init__",
        lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("constructed")),
    )
    calls: list[object] = []

    def recover(**kwargs: object) -> HKHistoryExecutionResult:
        calls.append(kwargs["plan"])
        return HKHistoryExecutionResult(None, 0, 3, 8, False)

    monkeypatch.setattr(  # type: ignore[attr-defined]
        backfill_hk_history, "recover_existing_hk_history_requests", recover
    )
    code = backfill_hk_history.main(
        [
            "--plan",
            str(tmp_path / "plan.json"),
            "--data-root",
            str(tmp_path / "data"),
            "--journal-root",
            str(tmp_path / "journal"),
            "--recover-existing-only",
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert calls == [sentinel]
    assert '"network_requests":0' in captured.out
