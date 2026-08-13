"""Contracts for development HK gross-total-return research-price publication."""

from __future__ import annotations

import datetime as dt
import json
import os
import pickle
import shutil
import subprocess
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import polars as pl
import pytest

import quant.data.hk_total_return_research_price as price
import quant.data.hk_total_return_schedule as schedule

AS_OF = dt.datetime(2026, 5, 10, 12, tzinfo=dt.UTC)


def _bars(*, close: object = 96.0) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"symbol": "00005.HK", "trade_date": dt.date(2026, 5, 5), "close": 100.0},
            {"symbol": "00005.HK", "trade_date": dt.date(2026, 5, 8), "close": close},
            {"symbol": "00005.HK", "trade_date": dt.date(2026, 5, 9), "close": 110.0},
            {"symbol": "00700.HK", "trade_date": dt.date(2026, 5, 5), "close": 50.0},
            {"symbol": "00700.HK", "trade_date": dt.date(2026, 5, 9), "close": 55.0},
        ]
    )


def _schedule_row(
    event: str,
    *,
    action_type: str,
    ex_date: dt.date,
    application_date: dt.date | None,
    disposition: str = "APPLY_IN_WINDOW",
    cash: float | None = None,
    multiplier: float | None = None,
) -> dict[str, Any]:
    identities = {
        "p0_query_sha256": "1" * 64,
        "p0_actions_content_sha256": "2" * 64,
        "p0_evidence_content_sha256": "3" * 64,
        "implementation_evidence_content_sha256": "4" * 64,
        "implementation_projection_sha256": "5" * 64,
        "bar_plan_sha256": "6" * 64,
        "bar_publication_sha256": "7" * 64,
        "bars_content_sha256": "8" * 64,
        "bar_availability_content_sha256": "9" * 64,
    }
    return {
        "event_id": event * 64,
        "symbol": "00005.HK",
        "action_type": action_type,
        "ex_date": ex_date,
        "window_disposition": disposition,
        "application_trade_date": application_date,
        "cash_per_share_gross_hkd": cash,
        "share_multiplier": multiplier,
        **identities,
    }


def _inputs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: list[dict[str, Any]] | None = None,
    bars: pl.DataFrame | None = None,
) -> tuple[
    schedule.VerifiedHkTotalReturnApplicationPlan,
    schedule.HkTotalReturnFreshContext,
    dict[str, int],
]:
    schedule_rows = rows or [
        _schedule_row(
            "a",
            action_type="DIVIDEND",
            ex_date=dt.date(2026, 5, 7),
            application_date=dt.date(2026, 5, 8),
            cash=1.25,
        ),
        _schedule_row(
            "b",
            action_type="DIVIDEND",
            ex_date=dt.date(2026, 5, 7),
            application_date=dt.date(2026, 5, 8),
            cash=0.75,
        ),
        _schedule_row(
            "c",
            action_type="SPLIT",
            ex_date=dt.date(2026, 5, 7),
            application_date=dt.date(2026, 5, 8),
            multiplier=2.0,
        ),
        _schedule_row(
            "d",
            action_type="DIVIDEND",
            ex_date=dt.date(2026, 5, 5),
            application_date=None,
            disposition="BASELINE_PREWINDOW",
            cash=None,
        ),
        _schedule_row(
            "e",
            action_type="BONUS",
            ex_date=dt.date(2026, 5, 12),
            application_date=None,
            disposition="OUTSIDE_FUTURE_WINDOW",
            multiplier=1.1,
        ),
    ]
    frame = pl.DataFrame(schedule_rows).sort(["symbol", "ex_date", "event_id"])
    plan = schedule._issue_plan(frame, AS_OF)
    bar_frame = bars if bars is not None else _bars()
    implemented = SimpleNamespace(
        p0_query_sha256="1" * 64,
        p0_actions_content_sha256="2" * 64,
        p0_evidence_content_sha256="3" * 64,
        implementation_evidence_content_sha256="4" * 64,
        projection_sha256="5" * 64,
    )
    bundle = SimpleNamespace(
        bars=bar_frame,
        plan_sha256="6" * 64,
        publication_sha256="7" * 64,
    )
    context = schedule.HkTotalReturnFreshContext(
        implemented=implemented,  # type: ignore[arg-type]
        implementation_projection=SimpleNamespace(),  # type: ignore[arg-type]
        p0_result=SimpleNamespace(),  # type: ignore[arg-type]
        p0_projection=SimpleNamespace(),  # type: ignore[arg-type]
        bar_bundle=bundle,  # type: ignore[arg-type]
        history_plan=SimpleNamespace(),  # type: ignore[arg-type]
        journal_root=cast(Path, SimpleNamespace()),
        seed_raw_root=cast(Path, SimpleNamespace()),
        raw_store=SimpleNamespace(),  # type: ignore[arg-type]
        clean_root=cast(Path, SimpleNamespace()),
        as_of=AS_OF,
    )
    calls = {"verify": 0}

    def verify(
        candidate: schedule.VerifiedHkTotalReturnApplicationPlan,
        *,
        context: schedule.HkTotalReturnFreshContext,
    ) -> None:
        assert candidate is plan
        assert context is not None
        calls["verify"] += 1

    monkeypatch.setattr(price, "verify_hk_total_return_application_plan", verify)
    return plan, context, calls


def _publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    **kwargs: object,
) -> tuple[
    price.VerifiedDevelopmentHkGrossTotalReturnPublication,
    schedule.VerifiedHkTotalReturnApplicationPlan,
    schedule.HkTotalReturnFreshContext,
    dict[str, int],
]:
    plan, context, calls = _inputs(monkeypatch, **kwargs)  # type: ignore[arg-type]
    development = tmp_path / "development"
    development.mkdir(parents=True)
    publication = price.publish_development_hk_gross_total_return(
        application_plan=plan,
        context=context,
        development_root=development,
    )
    return publication, plan, context, calls


def test_exact_capability_formula_194_and_four_file_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication, plan, context, calls = _publish(tmp_path, monkeypatch)
    assert type(publication) is price.VerifiedDevelopmentHkGrossTotalReturnPublication
    assert publication.classification == "development"
    assert publication.as_of == AS_OF
    assert (
        publication.artifact_id
        == "7e287fd010c41f53f1f62d2c3cdb07a8cbaee9a72d2921177465242fe09d1ae6"
    )
    assert calls == {"verify": 1}
    assert set(path.name for path in publication.publication_root.iterdir()) == {
        "request.json",
        "research_price_1d.parquet",
        "manifest.json",
        "receipt.json",
    }
    frame = publication.research_prices
    assert frame.columns == [
        "symbol",
        "trade_date",
        "adjusted_close",
        "adjustment_method",
        "source",
    ]
    assert (
        frame.filter(
            (pl.col("symbol") == "00005.HK") & (pl.col("trade_date") == dt.date(2026, 5, 8))
        ).item(0, "adjusted_close")
        == 194.0
    )
    assert (
        frame.filter(
            (pl.col("symbol") == "00005.HK") & (pl.col("trade_date") == dt.date(2026, 5, 9))
        ).item(0, "adjusted_close")
        == 222.291666666667
    )
    assert frame.filter(pl.col("symbol") == "00700.HK").get_column("adjusted_close").to_list() == [
        50.0,
        55.0,
    ]
    receipt = json.loads((publication.publication_root / "receipt.json").read_text())
    assert receipt["gate_claim"] == "development_contract_only"
    assert receipt["formula_policy"] == "HK_GROSS_TOTAL_RETURN_CLOSE_V1"
    assert receipt["rounding_policy"] == "DECIMAL50_HALF_EVEN_OUTPUT_12DP_V1"
    verified = price.verify_development_hk_gross_total_return(
        publication_root=publication.publication_root,
        application_plan=plan,
        context=context,
    )
    assert verified.artifact_id == publication.artifact_id
    assert calls == {"verify": 2}
    assert publication.research_prices is not frame
    with pytest.raises(TypeError):
        pickle.dumps(publication)
    with pytest.raises(TypeError):
        type("Child", (price.VerifiedDevelopmentHkGrossTotalReturnPublication,), {})


def test_real_p1a_fresh_rebuild_is_consumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_hk_total_return_schedule import _context

    context = _context(monkeypatch)
    plan = schedule.build_hk_total_return_application_plan(context=context)
    development = tmp_path / "development"
    development.mkdir()
    publication = price.publish_development_hk_gross_total_return(
        application_plan=plan,
        context=context,
        development_root=development,
    )
    assert (
        publication.research_prices.filter(
            (pl.col("symbol") == "00005.HK") & (pl.col("trade_date") == dt.date(2026, 5, 8))
        ).item(0, "adjusted_close")
        == 24.5
    )
    price.verify_development_hk_gross_total_return(
        publication_root=publication.publication_root,
        application_plan=plan,
        context=context,
    )


def test_bonus_and_no_action_recurrence_use_decimal50_and_12dp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        _schedule_row(
            "a",
            action_type="BONUS",
            ex_date=dt.date(2026, 5, 7),
            application_date=dt.date(2026, 5, 8),
            multiplier=1.1,
        )
    ]
    publication, _, _, _ = _publish(tmp_path, monkeypatch, rows=rows)
    values = (
        publication.research_prices.filter(pl.col("symbol") == "00005.HK")
        .get_column("adjusted_close")
        .to_list()
    )
    assert values == [100.0, 105.6, 121.0]


@pytest.mark.parametrize(
    "rows",
    [
        [
            _schedule_row(
                "a",
                action_type="BONUS",
                ex_date=dt.date(2026, 5, 7),
                application_date=dt.date(2026, 5, 8),
                multiplier=1.1,
            ),
            _schedule_row(
                "b",
                action_type="SPLIT",
                ex_date=dt.date(2026, 5, 7),
                application_date=dt.date(2026, 5, 8),
                multiplier=2.0,
            ),
        ],
        [
            _schedule_row(
                "a",
                action_type="DIVIDEND",
                ex_date=dt.date(2026, 5, 6),
                application_date=dt.date(2026, 5, 8),
                cash=1.0,
            ),
            _schedule_row(
                "b",
                action_type="DIVIDEND",
                ex_date=dt.date(2026, 5, 7),
                application_date=dt.date(2026, 5, 8),
                cash=1.0,
            ),
        ],
    ],
)
def test_unsupported_grouping_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, Any]],
) -> None:
    plan, context, _ = _inputs(monkeypatch, rows=rows)
    development = tmp_path / "development"
    development.mkdir()
    with pytest.raises(
        price.HkTotalReturnResearchPriceError,
        match="HK_TOTAL_RETURN_GROUP_UNSUPPORTED",
    ):
        price.publish_development_hk_gross_total_return(
            application_plan=plan,
            context=context,
            development_root=development,
        )


def test_prewindow_and_future_bind_identity_but_not_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _, _, _ = _publish(tmp_path / "one", monkeypatch)
    rows = [
        _schedule_row(
            "a",
            action_type="DIVIDEND",
            ex_date=dt.date(2026, 5, 7),
            application_date=dt.date(2026, 5, 8),
            cash=1.25,
        ),
        _schedule_row(
            "b",
            action_type="DIVIDEND",
            ex_date=dt.date(2026, 5, 7),
            application_date=dt.date(2026, 5, 8),
            cash=0.75,
        ),
        _schedule_row(
            "c",
            action_type="SPLIT",
            ex_date=dt.date(2026, 5, 7),
            application_date=dt.date(2026, 5, 8),
            multiplier=2.0,
        ),
        _schedule_row(
            "f",
            action_type="DIVIDEND",
            ex_date=dt.date(2026, 5, 4),
            application_date=None,
            disposition="BASELINE_PREWINDOW",
        ),
    ]
    second, _, _, _ = _publish(tmp_path / "two", monkeypatch, rows=rows)
    assert first.research_prices.equals(second.research_prices)
    assert first.artifact_id != second.artifact_id


@pytest.mark.parametrize("invalid", [0.0, -1.0, float("nan"), float("inf"), "1e999999"])
def test_invalid_numeric_input_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: object
) -> None:
    plan, context, _ = _inputs(monkeypatch, bars=_bars(close=invalid))
    development = tmp_path / "development"
    development.mkdir()
    with pytest.raises(
        price.HkTotalReturnResearchPriceError,
        match="HK_TOTAL_RETURN_PRICE_INVALID",
    ):
        price.publish_development_hk_gross_total_return(
            application_plan=plan,
            context=context,
            development_root=development,
        )


@pytest.mark.parametrize(
    "name",
    ["request.json", "research_price_1d.parquet", "manifest.json", "receipt.json"],
)
def test_each_file_tamper_and_extra_file_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    publication, plan, context, _ = _publish(tmp_path, monkeypatch)
    target = publication.publication_root / name
    target.write_bytes(target.read_bytes() + b"x")
    with pytest.raises(
        price.HkTotalReturnResearchPriceError,
        match="HK_TOTAL_RETURN_PUBLICATION_INVALID",
    ):
        price.verify_development_hk_gross_total_return(
            publication_root=publication.publication_root,
            application_plan=plan,
            context=context,
        )


def test_replay_and_copied_root_are_fresh_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication, plan, context, calls = _publish(tmp_path / "original", monkeypatch)
    replay = price.publish_development_hk_gross_total_return(
        application_plan=plan,
        context=context,
        development_root=publication.publication_root.parents[1],
    )
    assert replay.artifact_id == publication.artifact_id
    assert calls == {"verify": 2}
    copied = (
        tmp_path / "copy" / "development" / "hk_gross_total_return_v1" / publication.artifact_id
    )
    copied.parent.mkdir(parents=True)
    shutil.copytree(publication.publication_root, copied)
    verified = price.verify_development_hk_gross_total_return(
        publication_root=copied,
        application_plan=plan,
        context=context,
    )
    assert verified.artifact_id == publication.artifact_id
    assert calls == {"verify": 3}


def test_bar_shuffle_preserves_logical_identity_and_partial_replay_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _, _, _ = _publish(tmp_path / "ordered", monkeypatch)
    shuffled = _bars().reverse()
    second, plan, context, _ = _publish(tmp_path / "shuffled", monkeypatch, bars=shuffled)
    assert second.artifact_id == first.artifact_id
    assert second.research_prices.equals(first.research_prices)

    partial_development = tmp_path / "partial" / "development"
    partial_root = partial_development / "hk_gross_total_return_v1" / first.artifact_id
    partial_root.mkdir(parents=True)
    shutil.copy2(first.publication_root / "request.json", partial_root / "request.json")
    with pytest.raises(
        price.HkTotalReturnResearchPriceError,
        match="HK_TOTAL_RETURN_PUBLICATION_INVALID",
    ):
        price.publish_development_hk_gross_total_return(
            application_plan=plan,
            context=context,
            development_root=partial_development,
        )


def test_partial_extra_symlink_and_wrong_root_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication, plan, context, _ = _publish(tmp_path / "complete", monkeypatch)
    (publication.publication_root / "extra").write_text("x")
    with pytest.raises(price.HkTotalReturnResearchPriceError):
        price.verify_development_hk_gross_total_return(
            publication_root=publication.publication_root,
            application_plan=plan,
            context=context,
        )
    wrong = tmp_path / "not-development"
    wrong.mkdir()
    with pytest.raises(price.HkTotalReturnResearchPriceError):
        price.publish_development_hk_gross_total_return(
            application_plan=plan,
            context=context,
            development_root=wrong,
        )
    target = tmp_path / "plain" / "development"
    target.mkdir(parents=True)
    linked = tmp_path / "linked" / "development"
    linked.parent.mkdir()
    try:
        linked.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit directory symlinks")
    with pytest.raises(price.HkTotalReturnResearchPriceError):
        price.publish_development_hk_gross_total_return(
            application_plan=plan,
            context=context,
            development_root=linked,
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows junction-specific contract")
def test_windows_junction_development_root_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, context, _ = _inputs(monkeypatch)
    target = tmp_path / "plain" / "development"
    target.mkdir(parents=True)
    junction = tmp_path / "junction" / "development"
    junction.parent.mkdir()
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip("host does not permit directory junctions")
    try:
        with pytest.raises(price.HkTotalReturnResearchPriceError):
            price.publish_development_hk_gross_total_return(
                application_plan=plan,
                context=context,
                development_root=junction,
            )
    finally:
        junction.rmdir()


def test_whole_resigned_upstream_closure_rejects_old_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication, _, _, _ = _publish(tmp_path, monkeypatch)
    changed = _schedule_row(
        "f",
        action_type="DIVIDEND",
        ex_date=dt.date(2026, 5, 7),
        application_date=dt.date(2026, 5, 8),
        cash=3.0,
    )
    plan, context, _ = _inputs(monkeypatch, rows=[changed])
    with pytest.raises(price.HkTotalReturnResearchPriceError):
        price.verify_development_hk_gross_total_return(
            publication_root=publication.publication_root,
            application_plan=plan,
            context=context,
        )


def test_competitor_replacement_is_not_removed_during_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, context, _ = _inputs(monkeypatch)
    development = tmp_path / "development"
    development.mkdir()
    original = price._write_exclusive
    calls = {"count": 0}

    def fail_after_replacement(path: Path, payload: bytes) -> tuple[int, int, int]:
        calls["count"] += 1
        if calls["count"] == 1:
            identity = original(path, payload)
            path.unlink()
            path.write_bytes(b"competitor")
            return identity
        raise price.HkTotalReturnResearchPriceError("HK_TOTAL_RETURN_IO_FAILED")

    monkeypatch.setattr(price, "_write_exclusive", fail_after_replacement)
    with pytest.raises(price.HkTotalReturnResearchPriceError, match="HK_TOTAL_RETURN_IO_FAILED"):
        price.publish_development_hk_gross_total_return(
            application_plan=plan,
            context=context,
            development_root=development,
        )
    competitor = next((development / "hk_gross_total_return_v1").glob("*/request.json"))
    assert competitor.read_bytes() == b"competitor"


def test_hostile_recursive_upstream_exception_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, context, _ = _inputs(monkeypatch)

    def hostile(*_args: object, **_kwargs: object) -> None:
        error = RuntimeError("SECRET_PATH/TOKEN/raw payload")
        error.__cause__ = error
        raise error

    monkeypatch.setattr(price, "verify_hk_total_return_application_plan", hostile)
    development = tmp_path / "development"
    development.mkdir()
    with pytest.raises(price.HkTotalReturnResearchPriceError) as caught:
        price.publish_development_hk_gross_total_return(
            application_plan=plan,
            context=context,
            development_root=development,
        )
    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.code == "HK_TOTAL_RETURN_PRICE_INPUT_INVALID"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "SECRET_PATH" not in rendered and "TOKEN" not in rendered


def test_mid_verify_root_replacement_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication, plan, context, _ = _publish(tmp_path, monkeypatch)
    original = price._read_stable_file
    calls = {"count": 0}

    def replace_root(path: Path) -> bytes:
        payload = original(path)
        calls["count"] += 1
        if calls["count"] == 1:
            root = path.parent
            displaced = root.with_name(root.name + "-old")
            root.rename(displaced)
            root.mkdir()
        return payload

    monkeypatch.setattr(price, "_read_stable_file", replace_root)
    with pytest.raises(price.HkTotalReturnResearchPriceError):
        price.verify_development_hk_gross_total_return(
            publication_root=publication.publication_root,
            application_plan=plan,
            context=context,
        )


def test_public_surface_is_exact() -> None:
    assert price.__all__ == [
        "HK_GROSS_TOTAL_RETURN_V1",
        "HkTotalReturnResearchPriceError",
        "VerifiedDevelopmentHkGrossTotalReturnPublication",
        "publish_development_hk_gross_total_return",
        "verify_development_hk_gross_total_return",
    ]
    assert "VerifiedG1Release" not in vars(price)
