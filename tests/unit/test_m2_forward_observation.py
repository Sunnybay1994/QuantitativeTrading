import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl
import pytest

from quant.research.run_s2_forward_observation import (
    _canonical_text_sha256,
    publish_forward_observation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "configs/research/m2_s2_minimum_breadth_forward.toml"


def _config() -> tuple[dict[str, object], bytes]:
    payload = CONFIG_PATH.read_bytes()
    return tomllib.loads(payload.decode("utf-8")), payload


def _candidates(config: dict[str, object]) -> list[str]:
    universe = config["universe"]
    assert isinstance(universe, dict)
    return [
        symbol
        for group in ("wide", "industry", "hong_kong_theme")
        for symbol in universe[group]
    ]


def _prices(candidates: list[str], as_of: dt.date) -> pl.DataFrame:
    dates: list[dt.date] = []
    cursor = as_of
    while len(dates) < 130:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor -= dt.timedelta(days=1)
    dates.reverse()
    rows = []
    for symbol_index, symbol in enumerate(candidates):
        growth = 0.001 + symbol_index * 0.0001
        rows.extend({
            "symbol": symbol,
            "trade_date": date,
            "adjusted_close": 1.0 + growth * index,
            "adjustment_method": "TOTAL_RETURN_DIVIDEND",
            "source": "forward-test",
        } for index, date in enumerate(dates))
    return pl.DataFrame(rows)


def _calendars() -> pl.DataFrame:
    dates = [
        dt.date(2026, 8, 1) + dt.timedelta(days=offset)
        for offset in range(61)
    ]
    return pl.DataFrame({
        "market": [market for market in ("SH", "SZ") for _ in dates],
        "date": dates * 2,
        "is_open": [date.weekday() < 5 for _market in ("SH", "SZ") for date in dates],
        "is_connect_open": [False] * (len(dates) * 2),
        "is_half_day": [False] * (len(dates) * 2),
    })


def test_candidate_source_hash_is_checkout_eol_independent() -> None:
    payload = b"[meta]\npurpose = \"candidate\"\n"
    assert _canonical_text_sha256(payload) == _canonical_text_sha256(
        payload.replace(b"\n", b"\r\n")
    )


def test_forward_observation_publishes_research_only_target_no_clobber(
    tmp_path: Path,
) -> None:
    config, payload = _config()
    as_of = dt.date(2026, 8, 31)
    candidates = _candidates(config)

    root, observation_id, reused = publish_forward_observation(
        project_root=PROJECT_ROOT,
        artifact_root=tmp_path / "artifacts",
        config_path=CONFIG_PATH,
        config_payload=payload,
        config=config,
        as_of=as_of,
        prices=_prices(candidates, as_of),
        calendars=_calendars(),
    )

    assert not reused
    assert root.name == observation_id
    assert {path.name for path in root.iterdir()} == {
        "observation.json",
        "scheduled_targets.parquet",
        "target_weights.parquet",
    }
    manifest = json.loads((root / "observation.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "RESEARCH_ONLY"
    assert manifest["deployment_authority"] is False
    assert manifest["candidate_source_run_id"] == (
        "4ea4493f798ed5df8ac61d316f74e56fbfd87730bc6ff578bf979705acb5f1e6"
    )
    assert manifest["as_of"] == "2026-08-31"
    assert manifest["execution_dates"] == ["2026-09-01"]
    targets = pl.read_parquet(root / "target_weights.parquet")
    scheduled = pl.read_parquet(root / "scheduled_targets.parquet")
    assert targets.get_column("weight").sum() == pytest.approx(0.9)
    assert targets.filter(pl.col("weight") > 0).height == 2
    assert scheduled.height == targets.height

    same_root, same_id, reused = publish_forward_observation(
        project_root=PROJECT_ROOT,
        artifact_root=tmp_path / "artifacts",
        config_path=CONFIG_PATH,
        config_payload=payload,
        config=config,
        as_of=as_of,
        prices=_prices(candidates, as_of).reverse(),
        calendars=_calendars().reverse(),
    )
    assert reused
    assert (same_root, same_id) == (root, observation_id)


def test_forward_observation_rejects_pre_freeze_or_partial_month(
    tmp_path: Path,
) -> None:
    config, payload = _config()
    candidates = _candidates(config)
    with pytest.raises(ValueError, match="首个允许月末"):
        publish_forward_observation(
            project_root=PROJECT_ROOT,
            artifact_root=tmp_path / "artifacts",
            config_path=CONFIG_PATH,
            config_payload=payload,
            config=config,
            as_of=dt.date(2026, 7, 31),
            prices=_prices(candidates, dt.date(2026, 7, 31)),
            calendars=_calendars(),
        )
    with pytest.raises(ValueError, match="最后一个 SH 开市日"):
        publish_forward_observation(
            project_root=PROJECT_ROOT,
            artifact_root=tmp_path / "artifacts",
            config_path=CONFIG_PATH,
            config_payload=payload,
            config=config,
            as_of=dt.date(2026, 9, 29),
            prices=_prices(candidates, dt.date(2026, 9, 29)),
            calendars=_calendars(),
        )
    assert not (tmp_path / "artifacts").exists()


def test_forward_observation_rejects_incomplete_candidate_prices(
    tmp_path: Path,
) -> None:
    config, payload = _config()
    as_of = dt.date(2026, 8, 31)
    candidates = _candidates(config)
    incomplete = _prices(candidates, as_of).filter(
        ~((pl.col("symbol") == candidates[0]) & (pl.col("trade_date") == as_of))
    )
    with pytest.raises(ValueError, match="未完整覆盖"):
        publish_forward_observation(
            project_root=PROJECT_ROOT,
            artifact_root=tmp_path / "artifacts",
            config_path=CONFIG_PATH,
            config_payload=payload,
            config=config,
            as_of=as_of,
            prices=incomplete,
            calendars=_calendars(),
        )
    assert not (tmp_path / "artifacts").exists()
