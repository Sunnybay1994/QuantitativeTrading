"""Focused formal G7D-F0 market-facts capability tests."""

from __future__ import annotations

import datetime as dt
import inspect
import pickle
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import polars as pl
import pytest

import quant.backtest.a_share_execution as facts_module
from quant.data.m3_release import G1ManifestV5, G1Release, VerifiedG1Release
from quant.research.m3.contracts import BacktestWindow, VerifiedBacktestPlanArtifact
from quant.research.m3.development_example import _fixture_frames


def _bare(cls: type[Any], **values: object) -> Any:
    value = object.__new__(cls)
    for name, item in values.items():
        object.__setattr__(value, name, item)
    return value


def _assert_public_invalid(callback: Any) -> None:
    with pytest.raises(ValueError) as caught:
        callback()
    assert str(caught.value) == "M3_A_SHARE_MARKET_FACTS_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def _reachable_closure_callables(*roots: Any) -> tuple[Any, ...]:
    pending = list(roots)
    seen: set[int] = set()
    found: list[Any] = []
    while pending:
        value = pending.pop()
        marker = id(value)
        if marker in seen:
            continue
        seen.add(marker)
        if callable(value):
            found.append(value)
        closure = getattr(value, "__closure__", None)
        if closure is None:
            continue
        for cell in closure:
            try:
                nested = cell.cell_contents
            except ValueError:
                continue
            if callable(nested):
                pending.append(nested)
    return tuple(found)


def _frames_and_plan() -> tuple[dict[str, pl.DataFrame], Any]:
    frames = _fixture_frames()
    sessions = tuple(
        frames["trade_calendar.parquet"]
        .filter(pl.col("market") == "SH")
        .get_column("date")
        .to_list()
    )
    frames["instrument.parquet"] = frames["instrument.parquet"].with_columns(
        pl.lit(None, dtype=pl.Date).alias("delist_date"),
        pl.lit("LISTED").alias("status"),
    )
    frames["benchmark_bar_1d.parquet"] = frames[
        "benchmark_bar_1d.parquet"
    ].with_columns(pl.lit("510300.SH").alias("benchmark"))
    event_id = "a" * 64
    frames["corporate_action_ledger.parquet"] = frames[
        "corporate_action_ledger.parquet"
    ].with_columns(pl.lit(event_id).alias("event_id"))
    event_json = f'["{event_id}"]'
    event_hash = facts_module._event_set_sha256((event_id,))
    frames["corporate_action_reconciliation.parquet"] = frames[
        "corporate_action_reconciliation.parquet"
    ].with_columns(
        pl.lit(event_json).alias("event_ids_json"),
        pl.lit(event_hash).alias("event_ids_sha256"),
    )
    symbols = tuple(frames["instrument.parquet"].get_column("symbol").to_list())
    scheduled = pl.DataFrame(
        [
            {"symbol": symbol, "weight": 0.2, "execution_date": day}
            for day in sessions
            for symbol in symbols
        ],
        schema={"symbol": pl.Utf8, "weight": pl.Float64, "execution_date": pl.Date},
    ).sort("execution_date", "symbol")
    window = BacktestWindow(
        signal_dates=tuple(day - dt.timedelta(days=1) for day in sessions),
        execution_dates=sessions,
        first_execution_date=sessions[0],
        terminal_valuation_date=sessions[-1],
        force_liquidation=False,
    )
    return frames, SimpleNamespace(
        scheduled_targets=scheduled,
        manifest=SimpleNamespace(window=window),
    )


def _issued_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prepare_calls: list[str] | None = None,
) -> Any:
    frames, plan = _frames_and_plan()
    selected = facts_module._select_and_validate_formal_facts(
        frames, plan, benchmark="510300.SH"
    )
    digests = tuple(
        facts_module.FormalAShareMarketFactArtifactDigestV1(
            root_alias="formal", relative_path=f"release/{index:02d}.parquet",
            size_bytes=100 + index, sha256="12345678"[index] * 64,
            table_name=spec[0], row_count=selected[name].height,
            content_sha256="89abcdef"[index] * 64,
        )
        for index, (name, spec) in enumerate(
            facts_module._FORMAL_FACT_SPECS.items()
        )
    )
    identity = facts_module.FormalAShareMarketFactsIdentityV1(
        schema_version="m3-formal-a-share-market-facts-v1",
        g1_release_id="a" * 64,
        g1_release_manifest_sha256="b" * 64,
        backtest_plan_manifest_sha256="c" * 64,
        backtest_plan_receipt_sha256="d" * 64,
        window_sha256="e" * 64,
        artifact_digests=digests,
        input_market_facts_sha256="f" * 64,
    )
    release_entity = facts_module._PathEntity(
        tmp_path / "release", 1, 1, 1, 1, 1, 1
    )
    plan_entity = facts_module._PathEntity(
        tmp_path / "plan", 1, 2, 1, 1, 1, 1
    )
    file_entities = tuple(
        facts_module._PathEntity(
            tmp_path / f"fact-{index}", 1, index + 3, 1, 1, 1, 1
        )
        for index in range(8)
    )
    def prepared(**kwargs: object) -> Any:
        if prepare_calls is not None:
            prepare_calls.append("prepare")
        return identity, selected, (release_entity, plan_entity, file_entities)

    monkeypatch.setattr(
        facts_module, "_prepare_verified_a_share_market_facts", prepared
    )
    return facts_module.load_verified_a_share_market_facts(
        release=cast(Any, object()), plan=cast(Any, object()),
        fresh_context=cast(Any, object()), artifact_roots={"formal": tmp_path},
    )


def test_formal_window_selection_and_bidirectional_event_closure() -> None:
    frames, plan = _frames_and_plan()
    selected = facts_module._select_and_validate_formal_facts(
        frames, plan, benchmark="510300.SH"
    )
    assert set(selected) == set(facts_module._FORMAL_FACT_SPECS)
    assert set(selected["instrument.parquet"].get_column("symbol")) == {
        "000001.SZ", "000002.SZ", "600000.SH"
    }
    assert set(selected["benchmark_bar_1d.parquet"].get_column("benchmark")) == {
        "510300.SH"
    }

    old_benchmark = frames["benchmark_bar_1d.parquet"].with_columns(
        pl.lit("H00300.CSI").alias("benchmark")
    )
    mixed = dict(frames)
    mixed["benchmark_bar_1d.parquet"] = pl.concat(
        [old_benchmark, frames["benchmark_bar_1d.parquet"]]
    ).sort("benchmark", "trade_date", "source")
    mixed_selected = facts_module._select_and_validate_formal_facts(
        mixed, plan, benchmark="510300.SH"
    )
    assert mixed_selected["benchmark_bar_1d.parquet"].equals(
        selected["benchmark_bar_1d.parquet"]
    )
    assert facts_module.clean_table_content_sha256(
        table_name="benchmark_bar_1d",
        frame=mixed_selected["benchmark_bar_1d.parquet"],
    ) != facts_module.clean_table_content_sha256(
        table_name="benchmark_bar_1d", frame=old_benchmark
    )

    # Whole-day corporate-action transition is legal only with the exact ledger set.
    event_day = selected["corporate_action_ledger.parquet"].row(
        0, named=True
    )["ex_date"]
    attacked = dict(frames)
    attacked["bar_1d.parquet"] = frames["bar_1d.parquet"].filter(
        ~((pl.col("symbol") == "600000.SH") & (pl.col("trade_date") == event_day))
    )
    attacked["price_limit_1d.parquet"] = frames["price_limit_1d.parquet"].filter(
        ~((pl.col("symbol") == "600000.SH") & (pl.col("trade_date") == event_day))
    )
    full = frames["suspension_1d.parquet"].row(0, named=True)
    attacked["suspension_1d.parquet"] = pl.concat(
        [
            frames["suspension_1d.parquet"],
            pl.DataFrame([{**full, "symbol": "600000.SH", "trade_date": event_day}]),
        ]
    ).sort("symbol", "trade_date", "source")
    facts_module._select_and_validate_formal_facts(
        attacked, plan, benchmark="510300.SH"
    )

    missing_ledger = dict(attacked)
    missing_ledger["corporate_action_ledger.parquet"] = attacked[
        "corporate_action_ledger.parquet"
    ].clear()
    with pytest.raises(ValueError):
        facts_module._select_and_validate_formal_facts(
            missing_ledger, plan, benchmark="510300.SH"
        )


def test_formal_domain_lifecycle_limit_and_benchmark_fail_closed() -> None:
    frames, plan = _frames_and_plan()
    terminal = plan.manifest.window.terminal_valuation_date
    attacked = dict(frames)
    attacked["instrument.parquet"] = frames["instrument.parquet"].with_columns(
        pl.when(pl.col("symbol") == "000002.SZ")
        .then(pl.lit(terminal - dt.timedelta(days=1)))
        .otherwise(pl.col("delist_date"))
        .alias("delist_date")
    )
    with pytest.raises(ValueError):
        facts_module._select_and_validate_formal_facts(
            attacked, plan, benchmark="510300.SH"
        )

    attacked = dict(frames)
    attacked["price_limit_1d.parquet"] = frames["price_limit_1d.parquet"].slice(1)
    with pytest.raises(ValueError):
        facts_module._select_and_validate_formal_facts(
            attacked, plan, benchmark="510300.SH"
        )

    attacked = dict(frames)
    attacked["benchmark_bar_1d.parquet"] = frames[
        "benchmark_bar_1d.parquet"
    ].slice(1)
    with pytest.raises(ValueError):
        facts_module._select_and_validate_formal_facts(
            attacked, plan, benchmark="510300.SH"
        )

    attacked = dict(frames)
    attacked["benchmark_bar_1d.parquet"] = frames[
        "benchmark_bar_1d.parquet"
    ].with_columns(pl.lit("H00300.CSI").alias("benchmark"))
    with pytest.raises(ValueError):
        facts_module._select_and_validate_formal_facts(
            attacked, plan, benchmark="510300.SH"
        )

    for invalid_selector in ("H00300.CSI", 510300):
        with pytest.raises(ValueError):
            facts_module._select_and_validate_formal_facts(
                frames, plan, benchmark=cast(Any, invalid_selector)
            )


def test_public_loader_orders_fresh_verification_before_fact_read_and_redacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_root = tmp_path / ("1" * 64)
    plan_root = tmp_path / "plan"
    release_root.mkdir()
    plan_root.mkdir()
    release_id = "1" * 64
    release_handle = _bare(
        G1Release,
        release_id=release_id,
        root=release_root,
        manifest_path=release_root / "manifest.json",
        quality_path=release_root / "quality.json",
    )
    manifest = _bare(G1ManifestV5, release_id=release_id)
    release = _bare(
        VerifiedG1Release,
        release=release_handle,
        manifest=manifest,
        manifest_sha256="2" * 64,
        quality=object(),
        quality_sha256="3" * 64,
        artifact_paths=(),
    )
    window = BacktestWindow(
        signal_dates=(dt.date(2026, 1, 4),),
        execution_dates=(dt.date(2026, 1, 5),),
        first_execution_date=dt.date(2026, 1, 5),
        terminal_valuation_date=dt.date(2026, 1, 5),
        force_liquidation=False,
    )
    plan = _bare(
        VerifiedBacktestPlanArtifact,
        root=plan_root,
        scheduled_targets=pl.DataFrame(),
        manifest=SimpleNamespace(window=window),
        manifest_sha256="4" * 64,
        plan_receipt_sha256="5" * 64,
    )
    calls: list[str] = []
    config = SimpleNamespace(
        section=lambda name: (
            calls.append(f"config:{name}") or {"benchmark": "510300.SH"}
        )
    )
    context = SimpleNamespace(
        plan_receipt_path=tmp_path / "receipt.json",
        target=object(), folds=object(), experiment=object(), config=config,
        plan_fresh_context=object(),
    )
    fixture_frames, fixture_plan = _frames_and_plan()
    selected = facts_module._select_and_validate_formal_facts(
        fixture_frames, fixture_plan, benchmark="510300.SH"
    )
    entities = {
        tmp_path / f"fact-{index}.parquet": facts_module._PathEntity(
            path=tmp_path / f"fact-{index}.parquet", device=1, inode=index + 1,
            mode=1, size=1, mtime_ns=1, ctime_ns=1,
        )
        for index in range(8)
    }
    monkeypatch.setattr(facts_module, "_validate_formal_facts_outer", lambda *args: None)
    monkeypatch.setattr(
        facts_module, "verify_g1_release",
        lambda **kwargs: calls.append("g1") or release,
    )
    monkeypatch.setattr(
        facts_module, "verify_backtest_plan_artifact",
        lambda **kwargs: calls.append("plan") or plan,
    )
    monkeypatch.setattr(
        facts_module, "_read_formal_fact_files",
        lambda *args: (calls.append("facts") or (fixture_frames, {}, entities)),
    )
    monkeypatch.setattr(
        facts_module,
        "_select_and_validate_formal_facts",
        lambda *args, **kwargs: (
            calls.append(f"select:{kwargs['benchmark']}") or selected
        ),
    )
    monkeypatch.setattr(
        facts_module, "_snapshot_regular_file", lambda path: entities[path]
    )
    digests = tuple(
        facts_module.FormalAShareMarketFactArtifactDigestV1(
            root_alias="root", relative_path=f"facts/{index}.parquet",
            size_bytes=0, sha256="6" * 64, table_name=spec[0],
            row_count=0, content_sha256="7" * 64,
        )
        for index, spec in enumerate(facts_module._FORMAL_FACT_SPECS.values())
    )
    monkeypatch.setattr(facts_module, "_formal_fact_digests", lambda *args: digests)
    verified = facts_module.load_verified_a_share_market_facts(
        release=release, plan=plan,
        fresh_context=cast(Any, context), artifact_roots={"root": tmp_path},
    )
    assert calls == [
        "g1", "plan", "config:data", "facts", "select:510300.SH"
    ]
    assert type(verified) is facts_module.VerifiedAShareMarketFacts

    def hostile(**kwargs: object) -> object:
        raise RuntimeError("C:/PRIVATE/TOKEN_G7D")

    monkeypatch.setattr(facts_module, "verify_g1_release", hostile)
    with pytest.raises(ValueError) as caught:
        facts_module.load_verified_a_share_market_facts(
            release=release, plan=plan,
            fresh_context=cast(Any, context), artifact_roots={"root": tmp_path},
        )
    assert str(caught.value) == "M3_A_SHARE_MARKET_FACTS_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "TOKEN_G7D" not in repr(caught.value)

    calls.clear()
    monkeypatch.setattr(
        facts_module, "verify_g1_release",
        lambda **kwargs: calls.append("g1") or release,
    )
    monkeypatch.setattr(
        facts_module,
        "verify_backtest_plan_artifact",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("C:/PRIVATE/TOKEN_PLAN_DRIFT")
        ),
    )
    _assert_public_invalid(
        lambda: facts_module.load_verified_a_share_market_facts(
            release=release,
            plan=plan,
            fresh_context=cast(Any, context),
            artifact_roots={"root": tmp_path},
        )
    )
    assert calls == ["g1"]

    monkeypatch.setattr(
        facts_module, "verify_backtest_plan_artifact",
        lambda **kwargs: calls.append("plan") or plan,
    )
    config.section = lambda name: (_ for _ in ()).throw(
        RuntimeError("C:/PRIVATE/TOKEN_CONFIG_SECTION")
    )
    with pytest.raises(ValueError) as config_caught:
        facts_module.load_verified_a_share_market_facts(
            release=release,
            plan=plan,
            fresh_context=cast(Any, context),
            artifact_roots={"root": tmp_path},
        )
    assert str(config_caught.value) == "M3_A_SHARE_MARKET_FACTS_INVALID"
    assert config_caught.value.__cause__ is None
    assert config_caught.value.__context__ is None
    assert "TOKEN_CONFIG_SECTION" not in repr(config_caught.value)


def test_formal_digest_identity_is_portable_and_constructor_closed() -> None:
    digest = facts_module.FormalAShareMarketFactArtifactDigestV1(
        root_alias="formal", relative_path="g1/bar_1d.parquet",
        size_bytes=12, sha256="a" * 64, table_name="bar_1d",
        row_count=2, content_sha256="b" * 64,
    )
    assert "\\" not in digest.relative_path and not Path(digest.relative_path).is_absolute()
    _assert_public_invalid(lambda: facts_module.VerifiedAShareMarketFacts())


def test_r2_has_no_module_signing_or_factory_surface_and_rejects_forgery() -> None:
    namespace = vars(facts_module)
    assert "_FORMAL_FACTS_SEAL" not in namespace
    assert "_initialize_formal_facts_capability" not in namespace
    assert not any(
        type(value) is bytes and len(value) == 32 for value in namespace.values()
    )
    assert not any(
        callable(value)
        and any(token in name.lower() for token in ("mint", "signer", "factory"))
        for name, value in namespace.items()
    )

    forged = object.__new__(facts_module.VerifiedAShareMarketFacts)
    _assert_public_invalid(lambda: forged.identity)
    _assert_public_invalid(lambda: repr(forged))


def test_r3_reachable_closure_has_no_prepared_facts_mint_and_freshes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_type = facts_module.VerifiedAShareMarketFacts
    roots = [
        facts_module.load_verified_a_share_market_facts,
        public_type.__repr__,
        *(descriptor.fget for descriptor in (
            public_type.identity,
            public_type.instruments,
            public_type.calendar,
            public_type.bars,
            public_type.limits,
            public_type.suspensions,
            public_type.corporate_actions,
            public_type.corporate_action_reconciliation,
            public_type.benchmark_bars,
        )),
    ]
    reachable = _reachable_closure_callables(*roots)
    forbidden = {"identity", "frames", "selected", "provenance"}
    public_parameters = {"release", "plan", "fresh_context", "artifact_roots"}
    full_public_callables: list[Any] = []
    for callback in reachable:
        parameters = set(inspect.signature(callback).parameters)
        assert not (forbidden & parameters)
        if parameters == public_parameters:
            full_public_callables.append(callback)
        try:
            callback(object(), {}, object())
        except Exception:
            pass
        else:
            pytest.fail(f"raw prepared facts reached callable {callback!r}")
    assert full_public_callables == [facts_module.load_verified_a_share_market_facts]

    forged = object.__new__(public_type)
    _assert_public_invalid(lambda: forged.identity)
    prepare_calls: list[str] = []
    issued = _issued_capability(tmp_path, monkeypatch, prepare_calls)
    prepared = facts_module._prepare_verified_a_share_market_facts(
        release=cast(Any, object()), plan=cast(Any, object()),
        fresh_context=cast(Any, object()), artifact_roots={"formal": tmp_path},
    )
    assert type(prepared) is tuple and len(prepared) == 3
    another_forged = object.__new__(public_type)
    _assert_public_invalid(lambda: another_forged.identity)
    assert type(issued) is public_type
    assert prepare_calls == ["prepare", "prepare"]


def test_r2_issued_capability_clones_and_full_slot_clone_is_unissued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued = _issued_capability(tmp_path, monkeypatch)
    assert type(issued) is facts_module.VerifiedAShareMarketFacts
    assert issued.bars.equals(object.__getattribute__(issued, "_bars"))
    assert issued.bars is not object.__getattribute__(issued, "_bars")
    assert "attestation" not in repr(issued).lower()
    with pytest.raises((TypeError, ValueError)) as caught:
        pickle.dumps(issued)
    assert str(caught.value) == "M3_A_SHARE_MARKET_FACTS_INVALID"

    clone = object.__new__(facts_module.VerifiedAShareMarketFacts)
    for slot in facts_module.VerifiedAShareMarketFacts.__slots__:
        if slot != "__weakref__":
            object.__setattr__(clone, slot, object.__getattribute__(issued, slot))
    _assert_public_invalid(lambda: clone.identity)
    _assert_public_invalid(lambda: clone.bars)
    _assert_public_invalid(lambda: repr(clone))


@pytest.mark.parametrize(
    "slot",
    [
        "_identity", "_instruments", "_calendar", "_bars", "_limits",
        "_suspensions", "_corporate_actions",
        "_corporate_action_reconciliation", "_benchmark_bars",
        "_provenance", "_nonce", "_whole_hash", "_attestation",
    ],
)
def test_r2_every_issued_slot_drift_is_rejected(
    slot: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued = _issued_capability(tmp_path, monkeypatch)
    original = object.__getattribute__(issued, slot)
    if slot == "_identity":
        drift = replace(original, input_market_facts_sha256="0" * 64)
    elif slot in facts_module._FORMAL_CAPABILITY_FRAME_SLOTS:
        drift = original.clear()
    elif slot == "_provenance":
        drift = (
            replace(original[0], inode=999), original[1], original[2]
        )
    elif slot == "_nonce":
        drift = b"x" * 16
    elif slot == "_whole_hash":
        drift = "0" * 64
    else:
        drift = b"x" * 32
    object.__setattr__(issued, slot, drift)
    _assert_public_invalid(lambda: issued.identity)
    object.__setattr__(issued, slot, original)
    assert issued.identity.input_market_facts_sha256 == "f" * 64


def test_r2_every_public_consumer_verifies_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued = _issued_capability(tmp_path, monkeypatch)
    object.__setattr__(issued, "_attestation", b"z" * 32)
    consumers = (
        lambda: issued.identity,
        lambda: issued.instruments,
        lambda: issued.calendar,
        lambda: issued.bars,
        lambda: issued.limits,
        lambda: issued.suspensions,
        lambda: issued.corporate_actions,
        lambda: issued.corporate_action_reconciliation,
        lambda: issued.benchmark_bars,
        lambda: repr(issued),
    )
    for consumer in consumers:
        _assert_public_invalid(consumer)


def test_r2_fake_whole_hash_and_eight_frame_resign_cannot_forge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued = _issued_capability(tmp_path, monkeypatch)
    for slot in facts_module._FORMAL_CAPABILITY_FRAME_SLOTS:
        object.__setattr__(
            issued, slot, object.__getattribute__(issued, slot).clear()
        )
    identity = object.__getattribute__(issued, "_identity")
    frames = tuple(
        object.__getattribute__(issued, slot)
        for slot in facts_module._FORMAL_CAPABILITY_FRAME_SLOTS
    )
    _, attacker_whole_hash = facts_module._formal_capability_content(
        identity, frames
    )
    object.__setattr__(issued, "_whole_hash", attacker_whole_hash)
    _assert_public_invalid(lambda: issued.identity)


def test_r3_reload_rejects_old_capability_in_fresh_subprocess() -> None:
    support_path = Path(__file__).resolve()
    script = f"""
import importlib
import importlib.util
import pathlib
import sys
import tempfile
from pytest import MonkeyPatch

path = pathlib.Path({str(support_path)!r})
spec = importlib.util.spec_from_file_location("g7d_f0_reload_support", path)
assert spec is not None and spec.loader is not None
support = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = support
spec.loader.exec_module(support)
patch = MonkeyPatch()
with tempfile.TemporaryDirectory() as directory:
    capability = support._issued_capability(pathlib.Path(directory), patch)
old_type = type(capability)
patch.undo()
importlib.reload(support.facts_module)
assert support.facts_module.VerifiedAShareMarketFacts is not old_type
for callback in (lambda: capability.identity, lambda: repr(capability)):
    try:
        callback()
    except ValueError as error:
        assert str(error) == "M3_A_SHARE_MARKET_FACTS_INVALID"
        assert error.__cause__ is None and error.__context__ is None
    else:
        raise AssertionError("old capability survived reload")
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
