"""Publish one non-deploying forward target observation for a frozen M2 candidate."""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import io
import json
import os
import shutil
import tomllib
from pathlib import Path
from typing import Any, Sequence, cast

import polars as pl

from quant.backtest import schedule_next_trading_day
from quant.domain import TargetWeightSchema, TradeCalendarSchema
from quant.factors import compute_trend_factors_from_prices
from quant.research.lightweight_run import (
    canonical_json_bytes,
    compute_code_sha256,
    dataframe_input_digest,
)
from quant.strategies import RegimeFilteredEtfTrendStrategy

_SCHEMA_VERSION = "m2-forward-target-observation-v1"
_EXPECTED_ARTIFACT_KIND = "non_deploying_forward_observation"
_EXPECTED_CONCLUSION = "RESEARCH_ONLY"
_CODE_PATHS = (
    "src/quant/backtest/timing.py",
    "src/quant/factors/trend.py",
    "src/quant/research/lightweight_run.py",
    "src/quant/research/run_s2_forward_observation.py",
    "src/quant/strategies/baselines.py",
)


def main(argv: Sequence[str] | None = None) -> int:
    """Build an observation only for a completed, post-freeze month-end."""
    parser = argparse.ArgumentParser(description="生成 M2 冻结候选的前向目标观察")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/research/m2_s2_minimum_breadth_forward.toml"),
    )
    parser.add_argument("--as-of", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--project-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve(strict=True)
    config_path = _inside(project_root, args.config)
    data_root = _inside(project_root, args.data_root)
    artifact_root = _inside(project_root, args.artifact_root, strict=False)
    config_payload = config_path.read_bytes()
    with config_path.open("rb") as stream:
        config = cast(dict[str, Any], tomllib.load(stream))

    candidates = _candidates(config)
    prices = pl.read_parquet(
        data_root / "clean" / "research_price_1d" / "date=*" / "data.parquet"
    ).filter(
        pl.col("symbol").is_in(candidates)
        & (pl.col("adjustment_method") == "TOTAL_RETURN_DIVIDEND")
        & (pl.col("trade_date") <= args.as_of)
    )
    calendars = pl.concat([
        pl.read_parquet(
            data_root
            / "clean"
            / "trade_calendar"
            / f"market={market}"
            / "data.parquet"
        )
        for market in ("SH", "SZ")
    ])
    root, observation_id, reused = publish_forward_observation(
        project_root=project_root,
        artifact_root=artifact_root,
        config_path=config_path,
        config_payload=config_payload,
        config=config,
        as_of=args.as_of,
        prices=prices,
        calendars=calendars,
    )
    print(json.dumps({
        "observation_id": observation_id,
        "path": root.relative_to(project_root).as_posix(),
        "reused": reused,
        "status": _EXPECTED_CONCLUSION,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


def publish_forward_observation(
    *,
    project_root: Path,
    artifact_root: Path,
    config_path: Path,
    config_payload: bytes,
    config: dict[str, Any],
    as_of: dt.date,
    prices: pl.DataFrame,
    calendars: pl.DataFrame,
) -> tuple[Path, str, bool]:
    """Build and no-clobber publish one research-only forward observation."""
    root = project_root.resolve(strict=True)
    config_source = _validate_config(
        project_root=root,
        config_path=config_path,
        config=config,
        as_of=as_of,
    )
    candidates = _candidates(config)
    clean_calendars = TradeCalendarSchema.validate(calendars)
    _require_complete_month_end(clean_calendars, as_of)
    clean_prices = _validated_prices(
        prices=prices,
        candidates=candidates,
        as_of=as_of,
        minimum_observations=config["data"]["minimum_history_observations"],
    )
    target_weights, scheduled_targets = _build_targets(
        config=config,
        candidates=candidates,
        prices=clean_prices,
        calendars=clean_calendars,
        as_of=as_of,
    )
    target_payload = _parquet_bytes(target_weights)
    scheduled_payload = _parquet_bytes(scheduled_targets)
    input_digests = tuple(sorted((
        dataframe_input_digest(
            name="calendars",
            frame=clean_calendars,
            sort_by=("market", "date"),
            date_column="date",
        ),
        dataframe_input_digest(
            name="research-prices",
            frame=clean_prices,
            sort_by=("trade_date", "symbol"),
            date_column="trade_date",
        ),
    ), key=lambda item: item.name))
    body: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": _EXPECTED_CONCLUSION,
        "artifact_kind": _EXPECTED_ARTIFACT_KIND,
        "hypothesis_id": config["research"]["hypothesis_id"],
        "strategy_name": config["research"]["strategy_kind"],
        "strategy_version": config["research"]["strategy_version"],
        "candidate_source_run_id": config_source["candidate_source_run_id"],
        "candidate_source_config": config_source["candidate_source_config_relative_path"],
        "candidate_source_config_sha256": config_source["candidate_source_config_sha256"],
        "candidate_frozen_date": config_source["candidate_frozen_date"],
        "config_relative_path": config_path.relative_to(root).as_posix(),
        "config_sha256": hashlib.sha256(config_payload).hexdigest(),
        "code_sha256": compute_code_sha256(
            project_root=root, relative_paths=_CODE_PATHS
        ),
        "universe_name": config["universe"]["name"],
        "universe_frozen_as_of": config["universe"]["frozen_as_of"],
        "candidate_symbols": sorted(candidates),
        "as_of": as_of,
        "execution_dates": sorted(
            set(scheduled_targets.get_column("execution_date").to_list())
        ),
        "positive_symbols": sorted(
            target_weights.filter(pl.col("weight") > 0)
            .get_column("symbol")
            .to_list()
        ),
        "inputs": [
            {
                "name": item.name,
                "rows": item.rows,
                "min_date": item.min_date,
                "max_date": item.max_date,
                "content_sha256": item.content_sha256,
            }
            for item in input_digests
        ],
        "outputs": {
            "scheduled_targets.parquet": hashlib.sha256(scheduled_payload).hexdigest(),
            "target_weights.parquet": hashlib.sha256(target_payload).hexdigest(),
        },
        "deployment_authority": False,
        "caveats": [
            "This observation is research-only and cannot authorize PAPER or live orders.",
            "Economic evaluation starts only after subsequent realized sessions exist.",
        ],
    }
    observation_id = _sha256([_SCHEMA_VERSION, body])
    manifest_payload = canonical_json_bytes({"observation_id": observation_id, **body})
    payloads = {
        "observation.json": manifest_payload,
        "scheduled_targets.parquet": scheduled_payload,
        "target_weights.parquet": target_payload,
    }
    observation_root = artifact_root / "research" / "forward_observations" / observation_id
    return _publish_exact(observation_root, observation_id, payloads)


def _validate_config(
    *, project_root: Path, config_path: Path, config: dict[str, Any], as_of: dt.date
) -> dict[str, Any]:
    forward = config.get("forward_observation")
    research = config.get("research")
    strategy = config.get("strategy", {}).get("etf_regime_trend")
    if not isinstance(forward, dict) or set(forward) != {
        "artifact_kind",
        "candidate_frozen_date",
        "candidate_source_config_relative_path",
        "candidate_source_config_sha256",
        "candidate_source_run_id",
        "first_eligible_signal_date",
        "selected_regression_window",
        "selected_top_k",
    }:
        raise ValueError("forward_observation 配置字段不完整或包含未知字段")
    if (
        not isinstance(research, dict)
        or research.get("conclusion") != _EXPECTED_CONCLUSION
        or research.get("strategy_kind") != "etf_regime_trend"
        or not isinstance(strategy, dict)
        or forward["artifact_kind"] != _EXPECTED_ARTIFACT_KIND
        or strategy.get("top_k") != forward["selected_top_k"]
        or strategy.get("regression_window") != forward["selected_regression_window"]
    ):
        raise ValueError("前向观察候选与冻结策略不一致")
    source_path = _inside(
        project_root, Path(forward["candidate_source_config_relative_path"])
    )
    if _canonical_text_sha256(source_path.read_bytes()) != forward[
        "candidate_source_config_sha256"
    ]:
        raise ValueError("候选来源配置身份不匹配")
    if (
        type(as_of) is not dt.date
        or as_of < forward["first_eligible_signal_date"]
        or as_of <= forward["candidate_frozen_date"]
    ):
        raise ValueError("信号日期早于候选冻结后的首个允许月末")
    return forward


def _canonical_text_sha256(payload: bytes) -> str:
    """Hash UTF-8 config text independently of Git checkout line endings."""
    text = payload.decode("utf-8")
    canonical = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _require_complete_month_end(calendars: pl.DataFrame, as_of: dt.date) -> None:
    month_last = dt.date(as_of.year, as_of.month, calendar.monthrange(as_of.year, as_of.month)[1])
    sh_month = calendars.filter(
        (pl.col("market") == "SH")
        & pl.col("date").is_between(as_of.replace(day=1), month_last, closed="both")
    )
    if sh_month.is_empty() or sh_month.get_column("date").max() != month_last:
        raise ValueError("SH 日历没有覆盖完整信号月份")
    last_open = sh_month.filter(pl.col("is_open")).get_column("date").max()
    if last_open != as_of:
        raise ValueError("as_of 必须是完整月份的最后一个 SH 开市日")


def _validated_prices(
    *, prices: pl.DataFrame, candidates: list[str], as_of: dt.date,
    minimum_observations: int,
) -> pl.DataFrame:
    selected = prices.filter(
        pl.col("symbol").is_in(candidates)
        & (pl.col("adjustment_method") == "TOTAL_RETURN_DIVIDEND")
        & (pl.col("trade_date") <= as_of)
    ).sort("symbol", "trade_date")
    coverage = {
        symbol: (count, max_date)
        for symbol, count, max_date in selected.group_by("symbol").agg(
            pl.len().alias("count"), pl.col("trade_date").max().alias("max_date")
        ).iter_rows()
    }
    if (
        not isinstance(minimum_observations, int)
        or isinstance(minimum_observations, bool)
        or minimum_observations < 2
        or any(
            coverage.get(symbol, (0, None))[0] < minimum_observations
            or coverage.get(symbol, (0, None))[1] != as_of
            for symbol in candidates
        )
    ):
        raise ValueError("候选价格未完整覆盖信号日或最小历史")
    return selected


def _build_targets(
    *, config: dict[str, Any], candidates: list[str], prices: pl.DataFrame,
    calendars: pl.DataFrame, as_of: dt.date,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    strategy_config = config["strategy"]["etf_regime_trend"]
    factors = compute_trend_factors_from_prices(
        prices,
        as_of=as_of,
        source=None,
        momentum_windows=tuple(strategy_config["momentum_windows"]),
        regression_window=strategy_config["regression_window"],
        factor_version=strategy_config["factor_version"],
    )
    strategy = RegimeFilteredEtfTrendStrategy(
        candidates=tuple(candidates),
        regime_symbol=strategy_config["regime_symbol"],
        top_k=strategy_config["top_k"],
        cash_buffer=strategy_config["cash_buffer"],
        factor_version=strategy_config["factor_version"],
        momentum_windows=tuple(strategy_config["momentum_windows"]),
        regression_window=strategy_config["regression_window"],
        name=config["research"]["hypothesis_id"].replace("-", "_"),
        version=config["research"]["strategy_version"],
    )
    targets = TargetWeightSchema.validate(
        strategy.target_weights(as_of, factors).sort("symbol")
    )
    scheduled = schedule_next_trading_day(targets, calendars)
    if scheduled.height != targets.height:
        raise ValueError("日历没有覆盖所有目标的下一开市日")
    return targets, scheduled.sort("execution_date", "symbol")


def _candidates(config: dict[str, Any]) -> list[str]:
    universe = config.get("universe")
    if not isinstance(universe, dict):
        raise ValueError("universe 配置无效")
    candidates = [
        symbol
        for group in ("wide", "industry", "hong_kong_theme")
        for symbol in universe.get(group, [])
    ]
    if not candidates or len(candidates) != len(set(candidates)):
        raise ValueError("冻结候选池必须非空且不能重复")
    return candidates


def _publish_exact(
    root: Path, observation_id: str, payloads: dict[str, bytes]
) -> tuple[Path, str, bool]:
    if root.exists():
        _verify_existing(root, payloads)
        return root, observation_id, True
    root.parent.mkdir(parents=True, exist_ok=True)
    temp = root.parent / f".{observation_id}.tmp-{os.getpid()}"
    if temp.exists():
        raise ValueError("前向观察临时目录已存在")
    temp.mkdir()
    try:
        for name, payload in sorted(payloads.items()):
            with (temp / name).open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        temp.rename(root)
    except FileExistsError:
        shutil.rmtree(temp, ignore_errors=True)
        _verify_existing(root, payloads)
        return root, observation_id, True
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return root, observation_id, False


def _verify_existing(root: Path, payloads: dict[str, bytes]) -> None:
    actual = {path.name for path in root.iterdir() if path.is_file()}
    if actual != set(payloads) or any(
        (root / name).read_bytes() != payload for name, payload in payloads.items()
    ):
        raise ValueError("已有前向观察与本次内容不一致")


def _parquet_bytes(frame: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.write_parquet(buffer, compression="zstd", statistics=True)
    return buffer.getvalue()


def _inside(root: Path, path: Path, *, strict: bool = True) -> Path:
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve(strict=strict)
    if resolved != root and root not in resolved.parents:
        raise ValueError("路径必须位于项目根目录内")
    return resolved


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
