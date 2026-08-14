from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

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


@pytest.mark.parametrize("mode", [[], ["--recover-existing-only"]])
def test_cli_hkex_raw_is_finalize_only_and_is_not_read(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
    mode: list[str],
) -> None:
    sentinel = object()
    monkeypatch.setattr(backfill_hk_history, "load_hk_history_plan", lambda path: sentinel)
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda self: (_ for _ in ()).throw(AssertionError("raw file was read")),
    )
    raw_path = tmp_path / "retained.html"
    code = backfill_hk_history.main(
        [
            "--plan",
            str(tmp_path / "plan.json"),
            "--data-root",
            str(tmp_path / "data"),
            "--journal-root",
            str(tmp_path / "journal"),
            "--hkex-retained-raw",
            str(raw_path),
            *mode,
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 1
    assert captured.err.strip() == "HK_HISTORY_PLAN_CONFLICT"


def test_cli_finalize_reads_and_passes_explicit_hkex_raw(
    tmp_path: Path, capsys: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = object()
    retained_raw = b"SYNTHETIC RETAINED HKEX DAILY QUOTATIONS"
    raw_path = tmp_path / "retained.html"
    raw_path.write_bytes(retained_raw)
    monkeypatch.setattr(backfill_hk_history, "load_hk_history_plan", lambda path: sentinel)
    calls: list[dict[str, object]] = []

    def finalize(**kwargs: object) -> int:
        calls.append(kwargs)
        return 3

    monkeypatch.setattr(backfill_hk_history, "finalize_hk_history", finalize)
    code = backfill_hk_history.main(
        [
            "--plan",
            str(tmp_path / "plan.json"),
            "--data-root",
            str(tmp_path / "data"),
            "--journal-root",
            str(tmp_path / "journal"),
            "--finalize",
            "--hkex-retained-raw",
            str(raw_path),
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert calls[0]["plan"] is sentinel
    assert calls[0]["hkex_retained_raw"] == retained_raw
    assert '"published_rows":3' in captured.out


def test_cli_finalize_missing_hkex_raw_reports_stable_error(
    tmp_path: Path, capsys: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backfill_hk_history, "load_hk_history_plan", lambda path: object())
    code = backfill_hk_history.main(
        [
            "--plan",
            str(tmp_path / "plan.json"),
            "--data-root",
            str(tmp_path / "data"),
            "--journal-root",
            str(tmp_path / "journal"),
            "--finalize",
            "--hkex-retained-raw",
            str(tmp_path / "missing.html"),
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 1
    assert captured.err.strip() == "HK_HISTORY_REFERENCE_INVALID"


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--hkex-retained-raw", "raw"],
        ["--hkex-retained-metadata", "metadata"],
        ["--finalize", "--hkex-retained-raw", "raw", "--hkex-retained-metadata", "metadata"],
        ["--recover-existing-only", "--hkex-retained-raw", "raw", "--hkex-retained-metadata", "metadata"],
        ["--confirm-uncertain-retry", "--hkex-retained-raw", "raw", "--hkex-retained-metadata", "metadata"],
    ],
)
def test_cli_finalize_v3_rejects_missing_or_mixed_modes_before_reads(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
    extra: list[str],
) -> None:
    monkeypatch.setattr(
        backfill_hk_history,
        "load_hk_history_plan",
        lambda _path: (_ for _ in ()).throw(AssertionError("plan read")),
    )
    code = backfill_hk_history.main(
        ["--plan", str(tmp_path / "plan.json"), "--finalize-v3", *extra]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 1
    assert captured.err.strip() == "HK_HISTORY_PLAN_CONFLICT"


@pytest.mark.parametrize("mode", [[], ["--finalize"], ["--recover-existing-only"]])
def test_cli_retained_metadata_is_v3_only(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
    mode: list[str],
) -> None:
    monkeypatch.setattr(
        backfill_hk_history,
        "load_hk_history_plan",
        lambda _path: (_ for _ in ()).throw(AssertionError("plan read")),
    )
    code = backfill_hk_history.main(
        [
            "--plan",
            str(tmp_path / "plan.json"),
            "--hkex-retained-metadata",
            str(tmp_path / "metadata.json"),
            *mode,
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 1
    assert captured.err.strip() == "HK_HISTORY_PLAN_CONFLICT"


def test_cli_finalize_v3_passes_exact_bundle_and_reports_distinct_identity(
    tmp_path: Path, capsys: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = object()
    bundle = SimpleNamespace(
        bundle_id="b" * 64,
        metadata=SimpleNamespace(metadata_identity="m" * 64),
    )
    raw_path = tmp_path / "inputs" / "raw"
    metadata_path = tmp_path / "inputs" / "metadata.json"
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(backfill_hk_history, "load_hk_history_plan", lambda _path: plan)
    monkeypatch.setattr(
        backfill_hk_history,
        "load_verified_hkex_retained_bundle_for_finalize",
        lambda raw, metadata: bundle
        if (raw, metadata) == (raw_path, metadata_path)
        else (_ for _ in ()).throw(AssertionError("wrong pair")),
    )
    monkeypatch.setattr(
        backfill_hk_history.TushareConnector,
        "__init__",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("connector")),
    )

    def finalize(**kwargs: object) -> int:
        calls.append(kwargs)
        return 7

    monkeypatch.setattr(backfill_hk_history, "finalize_hk_history", finalize)
    code = backfill_hk_history.main(
        [
            "--plan",
            str(tmp_path / "plan.json"),
            "--data-root",
            str(tmp_path / "data"),
            "--journal-root",
            str(tmp_path / "journal"),
            "--finalize-v3",
            "--hkex-retained-raw",
            str(raw_path),
            "--hkex-retained-metadata",
            str(metadata_path),
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert calls[0]["plan"] is plan
    assert calls[0]["hkex_retained_bundle"] is bundle
    assert "hkex_retained_raw" not in calls[0]
    assert '"finalize_schema_version":"hk-history-finalize-v3"' in captured.out
    assert '"published_rows":7' in captured.out
    assert f'"retained_bundle_id":"{bundle.bundle_id}"' in captured.out


def test_cli_finalize_v3_only_consumes_bundle_after_out_of_contract_writer(
    tmp_path: Path, capsys: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = object()
    raw_path = tmp_path / "inputs" / "raw"
    metadata_path = tmp_path / "inputs" / "metadata.json"
    raw_path.parent.mkdir()
    raw_path.write_bytes(b"initial-raw")
    metadata_path.write_bytes(b"initial-metadata")
    bundle = SimpleNamespace(
        bundle_id="b" * 64,
        metadata=SimpleNamespace(metadata_identity="m" * 64),
        retained_raw=b"initial-raw",
        retained_metadata=b"initial-metadata",
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(backfill_hk_history, "load_hk_history_plan", lambda _path: plan)

    def load_bundle(raw: Path, metadata: Path) -> object:
        assert (raw, metadata) == (raw_path, metadata_path)
        # Model a retained-root writer that violates the caller's quiescence
        # premise after verification.  The CLI must still pass only the cached
        # bundle downstream; acceptance here is not a tamper-resistance claim.
        raw_path.write_bytes(b"writer-violated-quiescence")
        return bundle

    def finalize(**kwargs: object) -> int:
        calls.append(kwargs)
        return 7

    monkeypatch.setattr(
        backfill_hk_history,
        "load_verified_hkex_retained_bundle_for_finalize",
        load_bundle,
    )
    monkeypatch.setattr(backfill_hk_history, "finalize_hk_history", finalize)
    monkeypatch.setattr(
        backfill_hk_history.TushareConnector,
        "__init__",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("connector")),
    )

    code = backfill_hk_history.main(
        [
            "--plan",
            str(tmp_path / "plan.json"),
            "--data-root",
            str(tmp_path / "data"),
            "--journal-root",
            str(tmp_path / "journal"),
            "--finalize-v3",
            "--hkex-retained-raw",
            str(raw_path),
            "--hkex-retained-metadata",
            str(metadata_path),
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert len(calls) == 1
    assert calls[0]["hkex_retained_bundle"] is bundle
    assert "hkex_retained_raw" not in calls[0]
    assert "hkex_retained_metadata" not in calls[0]
    assert raw_path.read_bytes() == b"writer-violated-quiescence"
    assert bundle.retained_raw == b"initial-raw"
    assert '"finalize_schema_version":"hk-history-finalize-v3"' in captured.out


@pytest.mark.parametrize("role", ["journal", "raw", "clean"])
def test_cli_finalize_v3_rejects_plan_inside_writable_role(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    data = tmp_path / "data"
    roles = {
        "journal": tmp_path / "journal",
        "raw": data / "raw",
        "clean": data / "clean" / "bar_1d",
    }
    plan_path = roles[role] / "plan.json"
    monkeypatch.setattr(backfill_hk_history, "load_hk_history_plan", lambda _path: object())
    monkeypatch.setattr(
        backfill_hk_history,
        "load_verified_hkex_retained_bundle_for_finalize",
        lambda *_args: (_ for _ in ()).throw(AssertionError("loader")),
    )
    code = backfill_hk_history.main(
        [
            "--plan",
            str(plan_path),
            "--data-root",
            str(data),
            "--journal-root",
            str(roles["journal"]),
            "--finalize-v3",
            "--hkex-retained-raw",
            str(tmp_path / "raw.input"),
            "--hkex-retained-metadata",
            str(tmp_path / "metadata.input"),
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 1
    assert captured.err.strip() == "HK_HISTORY_PLAN_CONFLICT"


@pytest.mark.parametrize("journal_suffix", ["data", "data/raw", "data/clean", "data/clean/bar_1d/nested"])
def test_cli_finalize_v3_rejects_overlapping_role_roots(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
    journal_suffix: str,
) -> None:
    monkeypatch.setattr(
        backfill_hk_history,
        "load_hk_history_plan",
        lambda _path: (_ for _ in ()).throw(AssertionError("plan read")),
    )
    code = backfill_hk_history.main(
        [
            "--plan",
            str(tmp_path / "plan.json"),
            "--data-root",
            str(tmp_path / "data"),
            "--journal-root",
            str(tmp_path / journal_suffix),
            "--finalize-v3",
            "--hkex-retained-raw",
            str(tmp_path / "raw.input"),
            "--hkex-retained-metadata",
            str(tmp_path / "metadata.input"),
        ]
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 1
    assert captured.err.strip() == "HK_HISTORY_PLAN_CONFLICT"


@pytest.mark.parametrize(
    "failure_type", [RuntimeError, backfill_hk_history.HKHistoryBackfillError]
)
def test_cli_finalize_v3_sanitizes_hostile_loader_and_finalize(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[Exception],
) -> None:
    marker = "SECRET_PATH_TOKEN"
    finalize_calls = 0

    def finalize(**_kwargs: object) -> int:
        nonlocal finalize_calls
        finalize_calls += 1
        return 0

    monkeypatch.setattr(backfill_hk_history, "load_hk_history_plan", lambda _path: object())
    monkeypatch.setattr(backfill_hk_history, "finalize_hk_history", finalize)
    monkeypatch.setattr(
        backfill_hk_history.TushareConnector,
        "__init__",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("connector")),
    )
    monkeypatch.setattr(
        backfill_hk_history,
        "load_verified_hkex_retained_bundle_for_finalize",
        lambda *_args: (_ for _ in ()).throw(failure_type(marker)),
    )
    argv = [
        "--plan",
        str(tmp_path / "plan.json"),
        "--data-root",
        str(tmp_path / "data"),
        "--journal-root",
        str(tmp_path / "journal"),
        "--finalize-v3",
        "--hkex-retained-raw",
        str(tmp_path / "raw"),
        "--hkex-retained-metadata",
        str(tmp_path / "metadata"),
    ]
    assert backfill_hk_history.main(argv) == 1
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err.strip() == "HK_HISTORY_REFERENCE_INVALID"
    assert marker not in captured.err
    assert finalize_calls == 0
