"""G7D development A-share market-facts and open-state contract tests."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import shutil
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

from quant.backtest.a_share_execution import (
    AShareMarketFactsIdentityV1,
    build_a_share_market_facts,
    build_open_execution_states,
)
from quant.domain import OpenExecutionStateSchema
from quant.research.m3.development_example import (
    DevelopmentExampleReleaseHandle,
    VerifiedDevelopmentExampleAShareMarketFacts,
)

_PLAN_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "m3_plan_test_support_for_market_facts",
    Path(__file__).with_name("test_m3_backtest_plan_artifact.py"),
)
assert _PLAN_SUPPORT_SPEC is not None and _PLAN_SUPPORT_SPEC.loader is not None
_PLAN_SUPPORT = importlib.util.module_from_spec(_PLAN_SUPPORT_SPEC)
_PLAN_SUPPORT_SPEC.loader.exec_module(_PLAN_SUPPORT)

_FACT_FILES = {
    "instrument.parquet",
    "trade_calendar.parquet",
    "bar_1d.parquet",
    "price_limit_1d.parquet",
    "suspension_1d.parquet",
    "corporate_action_ledger.parquet",
    "corporate_action_reconciliation.parquet",
    "benchmark_bar_1d.parquet",
}


def _build_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, ...]:
    plan_bundle = _PLAN_SUPPORT._build_bundle(tmp_path, monkeypatch)
    plan = _PLAN_SUPPORT._verify(plan_bundle)
    parts = _PLAN_SUPPORT._TARGET_SUPPORT._parts(plan_bundle[0][0])
    release = parts["release"]
    facts = build_a_share_market_facts(release=release, plan=plan)
    return plan_bundle, plan, release, facts


@pytest.fixture(scope="module")
def market_bundle(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, ...]:
    monkeypatch = pytest.MonkeyPatch()
    try:
        yield _build_bundle(tmp_path_factory.mktemp("market-facts"), monkeypatch)
    finally:
        monkeypatch.undo()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: item.isoformat(),
    ).encode("utf-8")


def _copy_release_with_artifact(
    release: Any,
    root: Path,
    name: str,
    frame: pl.DataFrame,
) -> Any:
    shutil.copytree(release.release.root, root)
    frame.write_parquet(root / "contract" / name)
    return replace(
        release,
        release=DevelopmentExampleReleaseHandle(
            root=root,
            manifest_path=root / "manifest.json",
        ),
        artifact_paths=tuple(
            (path_name, root / "contract" / path_name)
            for path_name, _ in release.artifact_paths
        ),
    )


def _partial(
    facts: VerifiedDevelopmentExampleAShareMarketFacts,
    *,
    symbol: str,
    day: Any,
    detail: str,
) -> VerifiedDevelopmentExampleAShareMarketFacts:
    source = facts.suspensions.row(0, named=True)
    row = {
        "symbol": symbol,
        "trade_date": day,
        "suspension_scope": "PARTIAL",
        "suspension_detail": detail,
        "source": source["source"],
        "source_snapshot_id": source["source_snapshot_id"],
    }
    return replace(facts, suspensions=pl.DataFrame([row]).with_columns(
        pl.col("trade_date").cast(pl.Date)
    ))


def _state(
    facts: VerifiedDevelopmentExampleAShareMarketFacts,
    *,
    day: Any,
    symbol: str,
) -> dict[str, Any]:
    result = build_open_execution_states(facts=facts, date=day, symbols=(symbol,))
    assert result.height == 1
    return result.row(0, named=True)


def test_market_facts_builder_binds_exact_eight_release_files(
    market_bundle: tuple[Any, ...],
) -> None:
    _, plan, release, facts = market_bundle
    assert isinstance(facts, VerifiedDevelopmentExampleAShareMarketFacts)
    assert facts.release_kind == "development_example"
    assert facts.formal_gate_eligible is False
    assert facts.example_id == release.manifest.example_id
    assert type(facts.identity) is AShareMarketFactsIdentityV1
    assert facts.identity.schema_version == "m3-a-share-market-facts-v1"
    assert facts.identity.g1_release_id == release.manifest.release_id
    assert facts.identity.g1_release_manifest_sha256 == release.manifest_sha256
    assert facts.identity.window_sha256 == hashlib.sha256(
        _canonical(asdict(plan.manifest.window))
    ).hexdigest()
    relative_paths = tuple(item.relative_path for item in facts.identity.artifact_digests)
    assert relative_paths == tuple(sorted(relative_paths))
    assert {Path(path).name for path in relative_paths} == _FACT_FILES
    source_paths = dict(release.artifact_paths)
    for item in facts.identity.artifact_digests:
        source = source_paths[Path(item.relative_path).name]
        raw = source.read_bytes()
        assert item.size_bytes == len(raw)
        assert item.sha256 == hashlib.sha256(raw).hexdigest()
    assert len(facts.identity.input_market_facts_sha256) == 64
    assert all(char in "0123456789abcdef" for char in facts.identity.input_market_facts_sha256)
    assert facts.instruments.equals(pl.read_parquet(source_paths["instrument.parquet"]))
    assert facts.calendar.equals(pl.read_parquet(source_paths["trade_calendar.parquet"]))


def test_market_facts_public_builder_accepts_only_verified_bundles() -> None:
    parameters = inspect.signature(build_a_share_market_facts).parameters
    assert tuple(parameters) == ("release", "plan")
    assert all(value.kind is inspect.Parameter.KEYWORD_ONLY for value in parameters.values())
    forbidden = {
        "release_id", "artifact_paths", "instruments", "calendar", "bars", "limits",
        "suspensions", "corporate_actions", "corporate_action_reconciliation",
        "benchmark_bars", "window_sha256",
    }
    assert forbidden.isdisjoint(parameters)


def test_market_facts_rejects_development_identity_mix(
    market_bundle: tuple[Any, ...],
) -> None:
    plan_bundle, plan, release, _ = market_bundle
    mixed = replace(plan, example_id="development-example-" + "f" * 64)
    with pytest.raises(ValueError):
        build_a_share_market_facts(release=release, plan=mixed)
    assert plan_bundle[3].exists()


def test_full_day_is_blocked_even_without_bar_or_limit(
    market_bundle: tuple[Any, ...],
) -> None:
    _, _, _, facts = market_bundle
    full = facts.suspensions.filter(pl.col("suspension_scope") == "FULL_DAY").row(
        0, named=True
    )
    state = _state(facts, day=full["trade_date"], symbol=full["symbol"])
    assert state["full_day_suspended"] is True
    assert state["has_open"] is False
    assert state["open"] is None
    assert state["has_price_limit"] is False
    assert state["buy_allowed"] is False
    assert state["sell_allowed"] is False
    assert state["reason"] == "SUSPENDED"


@pytest.mark.parametrize(
    ("detail", "partial_status", "allowed", "reason"),
    [
        ("09:30-10:00", "SUSPENDED_AT_OPEN", False, "SUSPENDED"),
        ("09:00-09:15 | 10:00-10:30", "PROVEN_OPEN_TRADABLE", True, None),
        ("09:00-09:15|10:00-10:30", "OPEN_UNKNOWN", False, "OPEN_UNKNOWN"),
        ("临时停牌", "OPEN_UNKNOWN", False, "OPEN_UNKNOWN"),
        ("09:30-09:30", "OPEN_UNKNOWN", False, "OPEN_UNKNOWN"),
        ("24:00-24:30", "OPEN_UNKNOWN", False, "OPEN_UNKNOWN"),
    ],
)
def test_partial_suspension_uses_exact_delimiter_and_half_open_0930(
    market_bundle: tuple[Any, ...],
    detail: str,
    partial_status: str,
    allowed: bool,
    reason: str | None,
) -> None:
    _, plan, _, facts = market_bundle
    day = plan.manifest.window.first_execution_date
    symbol = facts.bars.filter(pl.col("trade_date") == day).item(0, "symbol")
    partial = _partial(facts, symbol=symbol, day=day, detail=detail)
    state = _state(partial, day=day, symbol=symbol)
    assert state["partial_open_status"] == partial_status
    assert state["buy_allowed"] is allowed
    assert state["sell_allowed"] is allowed
    assert state["reason"] == reason


def test_bar_never_overrides_partial_open_suspension(
    market_bundle: tuple[Any, ...],
) -> None:
    _, plan, _, facts = market_bundle
    day = plan.manifest.window.first_execution_date
    bar = facts.bars.filter(pl.col("trade_date") == day).row(0, named=True)
    partial = _partial(
        facts,
        symbol=bar["symbol"],
        day=day,
        detail="09:30-11:30",
    )
    state = _state(partial, day=day, symbol=bar["symbol"])
    assert state["has_open"] is True
    assert state["open"] == bar["open"]
    assert state["buy_allowed"] is False
    assert state["sell_allowed"] is False
    assert state["reason"] == "SUSPENDED"


def test_non_full_day_missing_or_one_sided_limit_fails_closed(
    market_bundle: tuple[Any, ...],
) -> None:
    plan_bundle, plan, release, facts = market_bundle
    parts = _PLAN_SUPPORT._TARGET_SUPPORT._parts(plan_bundle[0][0])
    limits_path = dict(release.artifact_paths)["price_limit_1d.parquet"]
    limits = pl.read_parquet(limits_path)
    day = plan.manifest.window.first_execution_date
    bars = pl.read_parquet(dict(release.artifact_paths)["bar_1d.parquet"])
    symbol = bars.filter(pl.col("trade_date") == day).item(0, "symbol")
    missing = limits.filter(
        ~((pl.col("symbol") == symbol) & (pl.col("trade_date") == day))
    )
    drifted = _copy_release_with_artifact(
        release,
        cast(Path, parts["common"]) / "development-example-release-missing-limit",
        "price_limit_1d.parquet",
        missing,
    )
    with pytest.raises(ValueError):
        build_a_share_market_facts(release=drifted, plan=plan)

    one_sided = facts.limits.with_columns(
        pl.when(
            (pl.col("symbol") == symbol) & (pl.col("trade_date") == day)
        ).then(None).otherwise(pl.col("up_limit")).alias("up_limit")
    )
    with pytest.raises(ValueError):
        build_open_execution_states(
            facts=replace(facts, limits=one_sided), date=day, symbols=(symbol,)
        )


def test_open_state_does_not_read_close_high_low_volume(
    market_bundle: tuple[Any, ...],
) -> None:
    _, plan, _, facts = market_bundle
    day = plan.manifest.window.first_execution_date
    symbol = facts.bars.filter(pl.col("trade_date") == day).item(0, "symbol")
    expected = build_open_execution_states(facts=facts, date=day, symbols=(symbol,))
    mutated_bars = facts.bars.with_columns(
        (pl.col("open") + 1000.0).alias("high"),
        (pl.col("open") / 2.0).alias("low"),
        pl.col("open").alias("close"),
        (pl.col("volume") + 987654321.0).alias("volume"),
    )
    actual = build_open_execution_states(
        facts=replace(facts, bars=mutated_bars), date=day, symbols=(symbol,)
    )
    assert actual.equals(expected)


def test_open_state_schema_columns_order_and_duplicate_symbol_rejection(
    market_bundle: tuple[Any, ...],
) -> None:
    _, plan, _, facts = market_bundle
    day = plan.manifest.window.first_execution_date
    symbol = facts.bars.filter(pl.col("trade_date") == day).item(0, "symbol")
    states = build_open_execution_states(facts=facts, date=day, symbols=(symbol,))
    assert states.columns == [
        "date", "symbol", "open", "has_open", "full_day_suspended",
        "partial_open_status", "has_price_limit", "up_limit", "down_limit",
        "buy_allowed", "sell_allowed", "reason",
    ]
    assert OpenExecutionStateSchema.validate(states).equals(states)
    with pytest.raises(ValueError):
        build_open_execution_states(
            facts=facts, date=day, symbols=(symbol, symbol)
        )


def test_market_facts_and_open_state_do_not_write_files(
    market_bundle: tuple[Any, ...],
) -> None:
    _, plan, release, facts = market_bundle
    tmp_path = release.release.root
    before = {
        str(path.relative_to(tmp_path)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    symbol = facts.bars.filter(
        pl.col("trade_date") == plan.manifest.window.first_execution_date
    ).item(0, "symbol")
    build_open_execution_states(
        facts=facts,
        date=plan.manifest.window.first_execution_date,
        symbols=(symbol,),
    )
    after = {
        str(path.relative_to(tmp_path)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert release.release.root.is_dir()
    assert not any(name.startswith("formal") for name in os.listdir(tmp_path))
