from __future__ import annotations

import datetime as dt
import hashlib
import io
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from quant.domain.enums import Market
from quant.execution import paper_formal_daily as daily
from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchFoldV1,
    ResearchInputDigestV1,
    publish_lightweight_research_run,
)

NOW = dt.datetime(2026, 8, 14, 1, 31, tzinfo=dt.timezone.utc)
SESSION = dt.date(2026, 8, 14)


def _parquet(frame: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    return buffer.getvalue()


def _candidate_run() -> LightweightResearchRunV1:
    return LightweightResearchRunV1(
        schema_version="lightweight-research-run-v1",
        run_id="",
        hypothesis_id="paper-candidate-v1",
        hypothesis="A frozen candidate is ready for PAPER-only observation.",
        strategy_name="first_paper_candidate",
        strategy_version="1.0.0",
        conclusion="PAPER_CANDIDATE",
        random_seed=0,
        config_relative_path="configs/research/paper_candidate.toml",
        config_sha256=hashlib.sha256(b"config").hexdigest(),
        code_sha256=hashlib.sha256(b"code").hexdigest(),
        universe_name="PAPER_CANDIDATE_A_SHARE_V1",
        universe_frozen_as_of=dt.date(2026, 8, 13),
        candidate_symbols=("000001.SZ", "600000.SH"),
        data_start=dt.date(2024, 1, 1),
        data_end=dt.date(2026, 8, 13),
        signal_timing="close",
        execution_timing="next_session_open",
        valuation_timing="close",
        folds=(
            ResearchFoldV1(
                1,
                dt.date(2024, 1, 1),
                dt.date(2024, 12, 31),
                dt.date(2025, 1, 1),
                dt.date(2025, 6, 30),
                dt.date(2025, 7, 1),
                dt.date(2026, 8, 13),
            ),
        ),
        cost_multipliers=(0.5, 1.0, 2.0),
        selection_metric="net_sharpe",
        inputs=(
            ResearchInputDigestV1(
                name="clean_daily",
                rows=2,
                min_date=dt.date(2026, 8, 13),
                max_date=dt.date(2026, 8, 13),
                content_sha256=hashlib.sha256(b"input").hexdigest(),
            ),
        ),
        outputs=(),
        aggregate_metrics=(("fold_count", 1),),
        caveats=("PAPER only.",),
    )


def _source_plan(run_id: str) -> daily.FormalPaperDailySourcePlan:
    return daily.FormalPaperDailySourcePlan(
        schema_version="formal-paper-daily-source-v1",
        classification="formal-paper-simulation",
        selector="formal_source_v1",
        target_run_id=run_id,
        market_source_version="clean_opening_v1",
        allowed_markets=(Market.SH, Market.SZ),
        signal_timing="close",
        execution_timing="next_session_open",
        raw_sha256="a" * 64,
        source_identity="b" * 64,
    )


def test_candidate_loader_requires_candidate_and_completes_zero_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = pl.DataFrame(
        {
            "as_of": [dt.date(2026, 8, 13)],
            "strategy": ["first_paper_candidate"],
            "strategy_version": ["1.0.0"],
            "symbol": ["600000.SH"],
            "weight": [0.4],
        }
    )
    _, published, _ = publish_lightweight_research_run(
        artifact_root=tmp_path / "artifacts",
        run=_candidate_run(),
        output_payloads={"target_weights.parquet": _parquet(target)},
    )
    plan = _source_plan(published.run_id)
    environment = SimpleNamespace(config=SimpleNamespace(project_root=tmp_path))
    monkeypatch.setattr(daily, "_fresh_environment", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        daily,
        "load_formal_paper_daily_source_plan",
        lambda **_kwargs: plan,
    )
    loader = daily.FormalPaperCandidateTargetLoader(
        environment=environment,  # type: ignore[arg-type]
        source_plan=plan,
        session_date=SESSION,
        now=NOW,
    )

    verified = loader.load()

    assert [(item.symbol, item.target_weight) for item in verified.targets] == [
        ("600000.SH", Decimal("0.4")),
        ("000001.SZ", Decimal("0")),
    ]


def test_research_only_run_cannot_be_used_as_formal_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = pl.DataFrame(
        {
            "as_of": [dt.date(2026, 8, 13)],
            "strategy": ["first_paper_candidate"],
            "strategy_version": ["1.0.0"],
            "symbol": ["600000.SH"],
            "weight": [0.4],
        }
    )
    _, published, _ = publish_lightweight_research_run(
        artifact_root=tmp_path / "artifacts",
        run=replace(_candidate_run(), conclusion="RESEARCH_ONLY"),
        output_payloads={"target_weights.parquet": _parquet(target)},
    )
    plan = _source_plan(published.run_id)
    environment = SimpleNamespace(config=SimpleNamespace(project_root=tmp_path))
    monkeypatch.setattr(daily, "_fresh_environment", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        daily,
        "load_formal_paper_daily_source_plan",
        lambda **_kwargs: plan,
    )

    with pytest.raises(daily.FormalPaperDailyInputError):
        daily.FormalPaperCandidateTargetLoader(
            environment=environment,  # type: ignore[arg-type]
            source_plan=plan,
            session_date=SESSION,
            now=NOW,
        ).load()


def _market_frames() -> tuple[pl.DataFrame, ...]:
    instruments = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "600000.SH"],
            "market": ["SZ", "SH"],
            "name": ["Ping An", "SPDB"],
            "instrument_type": ["STOCK", "STOCK"],
            "currency": ["CNY", "CNY"],
            "list_date": [dt.date(1991, 4, 3), dt.date(1999, 11, 10)],
            "delist_date": [None, None],
            "board_lot": [100, 100],
            "status": ["LISTED", "LISTED"],
        }
    )
    opening = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "600000.SH"],
            "session_date": [SESSION, SESSION],
            "open": [10.0, 12.0],
            "source": ["clean", "clean"],
            "source_snapshot_id": ["open-v1", "open-v1"],
            "known_at": [NOW, NOW],
        }
    ).with_columns(pl.col("known_at").dt.convert_time_zone("UTC"))
    limits = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "600000.SH"],
            "trade_date": [SESSION, SESSION],
            "pre_close": [9.8, 11.8],
            "has_price_limit": [True, True],
            "up_limit": [10.78, 12.98],
            "down_limit": [8.82, 10.62],
            "source": ["clean", "clean"],
            "source_snapshot_id": ["limit-v1", "limit-v1"],
        }
    )
    suspensions = pl.DataFrame(
        schema={
            "symbol": pl.String,
            "trade_date": pl.Date,
            "suspension_scope": pl.String,
            "suspension_detail": pl.String,
            "source": pl.String,
            "source_snapshot_id": pl.String,
        }
    )
    calendar = pl.DataFrame(
        {
            "market": ["SH", "SZ"],
            "date": [SESSION, SESSION],
            "is_open": [True, True],
            "is_connect_open": [False, False],
            "is_half_day": [False, False],
        }
    )
    return instruments, opening, limits, suspensions, calendar


def test_opening_market_publication_is_exact_and_no_clobber(tmp_path: Path) -> None:
    first = daily.publish_formal_paper_opening_market_input(
        project_root=tmp_path,
        session_date=SESSION,
        known_as_of=NOW,
        source_version="clean_opening_v1",
        instruments=_market_frames()[0],
        opening_prices=_market_frames()[1],
        price_limits=_market_frames()[2],
        suspensions=_market_frames()[3],
        calendar=_market_frames()[4],
    )
    second = daily.publish_formal_paper_opening_market_input(
        project_root=tmp_path,
        session_date=SESSION,
        known_as_of=NOW,
        source_version="clean_opening_v1",
        instruments=_market_frames()[0],
        opening_prices=_market_frames()[1],
        price_limits=_market_frames()[2],
        suspensions=_market_frames()[3],
        calendar=_market_frames()[4],
    )
    assert first[0] == second[0]
    assert first[1] == second[1]
    assert first[2] is False
    assert second[2] is True
    assert {path.name for path in first[0].iterdir()} == {
        "instrument.parquet",
        "opening_price.parquet",
        "price_limit_1d.parquet",
        "suspension_1d.parquet",
        "trade_calendar.parquet",
        "receipt.json",
    }

    (first[0] / "receipt.json").write_bytes(b"{}")
    with pytest.raises(daily.FormalPaperDailyInputError):
        daily.publish_formal_paper_opening_market_input(
            project_root=tmp_path,
            session_date=SESSION,
            known_as_of=NOW,
            source_version="clean_opening_v1",
            instruments=_market_frames()[0],
            opening_prices=_market_frames()[1],
            price_limits=_market_frames()[2],
            suspensions=_market_frames()[3],
            calendar=_market_frames()[4],
        )


def test_read_only_runner_rejects_dispatch_actions_before_composition() -> None:
    with pytest.raises(daily.FormalPaperDailyRunnerError) as caught:
        daily.run_formal_paper_daily_read_only(
            action="paper-submit",  # type: ignore[arg-type]
            environment=object(),  # type: ignore[arg-type]
            policy=object(),  # type: ignore[arg-type]
            composition=object(),  # type: ignore[arg-type]
            session_date=SESSION,
            now=NOW,
        )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
