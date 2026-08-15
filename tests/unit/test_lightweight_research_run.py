import datetime as dt
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

import quant.research.lightweight_run as lightweight_module
from quant.research import (
    LightweightResearchRunV1,
    ResearchFoldV1,
    ResearchInputDigestV1,
    compute_code_sha256,
    dataframe_input_digest,
    publish_lightweight_research_run,
)
from quant.research.lightweight_run import (
    LightweightResearchRunError,
    verify_lightweight_research_run,
)


def _run(
    input_digest: ResearchInputDigestV1, code_sha256: str
) -> LightweightResearchRunV1:
    return LightweightResearchRunV1(
        schema_version="lightweight-research-run-v1",
        run_id="",
        hypothesis_id="s2-example-v1",
        hypothesis="One frozen change should improve cost-robust out-of-sample stability.",
        strategy_name="etf_trend",
        strategy_version="1.0.0",
        conclusion="RESEARCH_ONLY",
        random_seed=0,
        config_relative_path="configs/research/example.toml",
        config_sha256=hashlib.sha256(b"config").hexdigest(),
        code_sha256=code_sha256,
        universe_name="ETF_POOL_M2_V1",
        universe_frozen_as_of=dt.date(2026, 7, 12),
        candidate_symbols=("159919.SZ", "510300.SH"),
        data_start=dt.date(2023, 1, 1),
        data_end=dt.date(2026, 7, 10),
        signal_timing="close",
        execution_timing="next_session_open",
        valuation_timing="close",
        folds=(
            ResearchFoldV1(
                1,
                dt.date(2023, 1, 1),
                dt.date(2024, 12, 31),
                dt.date(2025, 1, 1),
                dt.date(2025, 6, 30),
                dt.date(2025, 7, 1),
                dt.date(2025, 12, 31),
            ),
        ),
        cost_multipliers=(0.5, 1.0, 2.0),
        selection_metric="net_sharpe",
        inputs=(input_digest,),
        outputs=(),
        aggregate_metrics=(("fold_count", 1), ("test_return", 0.03)),
        caveats=("Research-only fixture.",),
    )


def test_dataframe_digest_is_independent_of_input_row_order() -> None:
    frame = pl.DataFrame({
        "symbol": ["510300.SH", "159919.SZ"],
        "trade_date": [dt.date(2026, 7, 10), dt.date(2026, 7, 9)],
        "close": [4.1, 1.2],
    })
    direct = dataframe_input_digest(
        name="prices",
        frame=frame,
        sort_by=("trade_date", "symbol"),
        date_column="trade_date",
    )
    reversed_digest = dataframe_input_digest(
        name="prices",
        frame=frame.reverse(),
        sort_by=("trade_date", "symbol"),
        date_column="trade_date",
    )
    assert direct == reversed_digest


def test_lightweight_run_publishes_no_clobber_and_reuses_exact_bytes(tmp_path) -> None:
    source = tmp_path / "src" / "strategy.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    code_sha256 = compute_code_sha256(
        project_root=tmp_path, relative_paths=("src/strategy.py",)
    )
    frame = pl.DataFrame({
        "symbol": ["510300.SH"],
        "trade_date": [dt.date(2026, 7, 10)],
        "close": [4.1],
    })
    input_digest = dataframe_input_digest(
        name="prices",
        frame=frame,
        sort_by=("trade_date", "symbol"),
        date_column="trade_date",
    )
    run = _run(input_digest, code_sha256)
    payloads = {"report.json": b"{}", "test_nav.parquet": b"parquet"}

    root, published, reused = publish_lightweight_research_run(
        artifact_root=tmp_path / "artifacts", run=run, output_payloads=payloads
    )
    assert not reused
    assert root.name == published.run_id
    assert set(path.name for path in root.iterdir()) == {
        "report.json",
        "run.json",
        "test_nav.parquet",
    }

    same_root, same_run, reused = publish_lightweight_research_run(
        artifact_root=tmp_path / "artifacts", run=run, output_payloads=payloads
    )
    assert reused
    assert same_root == root
    assert same_run == published

    (root / "report.json").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="does not match"):
        publish_lightweight_research_run(
            artifact_root=tmp_path / "artifacts", run=run, output_payloads=payloads
        )


def test_lightweight_run_identity_rejects_single_field_drift(tmp_path) -> None:
    source = tmp_path / "source.py"
    source.write_text("pass\n", encoding="utf-8")
    code_sha256 = compute_code_sha256(
        project_root=tmp_path, relative_paths=("source.py",)
    )
    frame = pl.DataFrame({
        "symbol": ["510300.SH"],
        "trade_date": [dt.date(2026, 7, 10)],
        "close": [4.1],
    })
    digest = dataframe_input_digest(
        name="prices", frame=frame, sort_by=("trade_date", "symbol"),
        date_column="trade_date",
    )
    run = _run(digest, code_sha256)
    _, published, _ = publish_lightweight_research_run(
        artifact_root=tmp_path / "artifacts",
        run=run,
        output_payloads={"report.json": b"{}"},
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        replace(published, random_seed=1)


def _published_bundle(
    tmp_path: Path, *, payloads: dict[str, bytes] | None = None
) -> tuple[Path, LightweightResearchRunV1]:
    source = tmp_path / "source.py"
    source.write_text("pass\n", encoding="utf-8")
    code_sha256 = compute_code_sha256(
        project_root=tmp_path, relative_paths=("source.py",)
    )
    frame = pl.DataFrame({
        "symbol": ["510300.SH"],
        "trade_date": [dt.date(2026, 7, 10)],
        "close": [4.1],
    })
    digest = dataframe_input_digest(
        name="prices",
        frame=frame,
        sort_by=("trade_date", "symbol"),
        date_column="trade_date",
    )
    root, run, _ = publish_lightweight_research_run(
        artifact_root=tmp_path / "artifacts",
        run=_run(digest, code_sha256),
        output_payloads=payloads or {"nested/report.json": b"{}"},
    )
    return root, run


def _assert_invalid(root: Path) -> None:
    with pytest.raises(
        LightweightResearchRunError, match="^LIGHTWEIGHT_RESEARCH_RUN_INVALID$"
    ) as caught:
        verify_lightweight_research_run(run_root=root)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_public_verifier_reconstructs_and_freshly_hashes_exact_tree(tmp_path) -> None:
    root, published = _published_bundle(tmp_path)
    assert verify_lightweight_research_run(run_root=root) == published

    (root / "nested" / "report.json").write_bytes(b"tampered")
    _assert_invalid(root)


@pytest.mark.parametrize("mutation", ["missing", "extra", "noncanonical", "root_name"])
def test_public_verifier_rejects_tree_manifest_and_root_drift(
    tmp_path, mutation: str
) -> None:
    root, _ = _published_bundle(tmp_path)
    if mutation == "missing":
        (root / "nested" / "report.json").unlink()
    elif mutation == "extra":
        (root / "extra.bin").write_bytes(b"extra")
    elif mutation == "noncanonical":
        manifest = json.loads((root / "run.json").read_text(encoding="utf-8"))
        (root / "run.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        moved = root.with_name("0" * 64)
        root.rename(moved)
        root = moved
    _assert_invalid(root)


def test_public_verifier_rejects_output_hardlink_alias(tmp_path) -> None:
    root, _ = _published_bundle(
        tmp_path, payloads={"left.bin": b"same", "right.bin": b"same"}
    )
    (root / "right.bin").unlink()
    os.link(root / "left.bin", root / "right.bin")
    _assert_invalid(root)


def test_public_verifier_rejects_link_or_reparse_output(tmp_path) -> None:
    root, _ = _published_bundle(tmp_path, payloads={"report.json": b"{}"})
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"{}")
    (root / "report.json").unlink()
    try:
        (root / "report.json").symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links are unavailable on this host")
    _assert_invalid(root)


def test_public_verifier_rejects_entity_replacement_during_read(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _published_bundle(tmp_path, payloads={"report.json": b"{}"})
    original = lightweight_module._read_stable_file
    replaced = False

    def replacing_read(path: Path, *, expected: os.stat_result):
        nonlocal replaced
        result = original(path, expected=expected)
        if path.name == "report.json" and not replaced:
            replaced = True
            payload = path.read_bytes()
            path.unlink()
            path.write_bytes(payload)
        return result

    monkeypatch.setattr(lightweight_module, "_read_stable_file", replacing_read)
    _assert_invalid(root)


def test_public_verifier_detaches_hostile_exception_graph(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _published_bundle(tmp_path)

    class HostileError(Exception):
        pass

    hostile = HostileError(str(root / "secret-token"))
    hostile.__cause__ = hostile
    hostile.__context__ = hostile

    def fail(_: Path) -> LightweightResearchRunV1:
        raise hostile

    monkeypatch.setattr(lightweight_module, "_verify_lightweight_research_run", fail)
    _assert_invalid(root)
