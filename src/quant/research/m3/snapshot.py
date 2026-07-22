"""clean -> Qlib staging Parquet 与不可变 snapshot manifest。

复权公式（SSOT 2.3）::

    normalization_base = first_valid_raw_close * first_valid_adj_factor
    qlib_factor        = adj_factor / normalization_base
    qlib_ohlc          = raw_ohlc * qlib_factor
    raw_vwap           = amount / volume
    qlib_vwap          = raw_vwap * qlib_factor
    qlib_volume        = raw_volume / qlib_factor

恒等式：``qlib_vwap / qlib_factor == amount / volume``。

``materialize_qlib_provider`` 仍留待真实 Qlib 环境；``validate_provider`` fail-closed。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import polars as pl

from quant.research.m3.contracts import DatasetSnapshot

STAGING_COLUMNS = (
    "symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "vwap",
    "volume",
    "factor",
)

ADJUSTMENT_SPEC: dict[str, object] = {
    "formula_version": "qlib_yahoo_like_v1",
    "clean_units": {
        "ohlc": "raw_unadjusted",
        "amount": "CNY",
        "volume": "shares",
        "adj_factor": "cumulative_backward",
        "vwap": "amount_per_share_unadjusted",
    },
    "normalization_base": "first_valid_raw_close * first_valid_adj_factor",
    "qlib_factor": "adj_factor / normalization_base",
    "qlib_ohlc": "raw_ohlc * qlib_factor",
    "raw_vwap": "amount / volume",
    "qlib_vwap": "(amount / volume) * qlib_factor",
    "qlib_volume": "raw_volume / qlib_factor",
    "identity": "qlib_vwap / qlib_factor == amount / volume",
}


def to_qlib_symbol(symbol: str) -> str:
    """将项目证券代码映射为 Qlib dump 使用的小写代码。"""
    if "." not in symbol:
        raise ValueError(f"非法证券代码: {symbol}")
    code, market = symbol.rsplit(".", 1)
    market = market.upper()
    if market not in {"SH", "SZ"}:
        raise ValueError(f"Qlib staging 暂仅支持 SH/SZ，收到: {symbol}")
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"非法证券代码: {symbol}")
    return f"{market.lower()}{code}"


def from_qlib_symbol(instrument: str) -> str:
    """将 Qlib instrument（大小写均可）还原为项目证券代码。"""
    text = instrument.strip()
    if len(text) < 8:
        raise ValueError(f"非法 Qlib instrument: {instrument}")
    prefix = text[:2].lower()
    code = text[2:]
    if prefix == "sh":
        market = "SH"
    elif prefix == "sz":
        market = "SZ"
    else:
        raise ValueError(f"未知或不支持的 Qlib 市场前缀: {instrument}")
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"非法 Qlib instrument: {instrument}")
    return f"{code}.{market}"


def prepare_qlib_staging(
    *,
    bars: pl.DataFrame,
    membership: pl.DataFrame,
    calendars: pl.DataFrame,
    source: str,
    universe: str,
) -> pl.DataFrame:
    """按 source → 合法性 → universe 并集/SH 日历 → 逐证券归一化 生成 staging。"""
    required = {
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adj_factor",
        "source",
    }
    missing = sorted(required - set(bars.columns))
    if missing:
        raise ValueError(f"bars 缺少选源所需字段: {missing}")

    if not universe:
        raise ValueError("universe 不得为空")
    if "universe" not in membership.columns or "symbol" not in membership.columns:
        raise ValueError("membership 缺少 universe/symbol")

    selected = bars.filter(pl.col("source") == source)
    if selected.is_empty():
        raise ValueError(f"source={source} 无行情行")
    if selected.get_column("source").n_unique() != 1:
        raise ValueError("禁止混合数据源写入 staging")

    _reject_duplicates(selected)
    _reject_invalid_rows(selected)

    members = membership.filter(pl.col("universe") == universe)
    if members.is_empty():
        raise ValueError(f"universe={universe} 无 membership 行")
    symbol_union = set(members.get_column("symbol").unique().to_list())
    if not symbol_union:
        raise ValueError(f"universe={universe} symbol 并集为空")

    # 交易日域统一使用 SH session calendar，不得把 SH/SZ 开市日做并集。
    open_dates = set(
        calendars.filter((pl.col("market") == "SH") & pl.col("is_open"))
        .get_column("date")
        .to_list()
    )
    if not open_dates:
        raise ValueError("SH 开市日历为空")

    # 仅按 symbol 并集与 SH 开市日过滤；不得按 effective_from/to 删除行情。
    filtered = selected.filter(
        pl.col("symbol").is_in(sorted(symbol_union))
        & pl.col("trade_date").is_in(sorted(open_dates))
    )
    if filtered.is_empty():
        raise ValueError("universe/日历过滤后 staging 为空")

    filtered = filtered.select(
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adj_factor",
    ).unique(subset=["symbol", "trade_date"], keep="first")

    parts: list[pl.DataFrame] = []
    for symbol in filtered.get_column("symbol").unique().sort().to_list():
        part = filtered.filter(pl.col("symbol") == symbol).sort("trade_date")
        first = part.row(0, named=True)
        base = float(first["close"]) * float(first["adj_factor"])
        if not math.isfinite(base) or base <= 0:
            raise ValueError(f"{symbol} normalization_base 非正或非 finite")
        adjusted = part.with_columns(
            (pl.col("adj_factor") / base).alias("factor"),
            (pl.col("amount") / pl.col("volume")).alias("_raw_vwap"),
        ).with_columns(
            (pl.col("open") * pl.col("factor")).alias("open"),
            (pl.col("high") * pl.col("factor")).alias("high"),
            (pl.col("low") * pl.col("factor")).alias("low"),
            (pl.col("close") * pl.col("factor")).alias("close"),
            (pl.col("_raw_vwap") * pl.col("factor")).alias("vwap"),
            (pl.col("volume") / pl.col("factor")).alias("volume"),
            pl.col("trade_date").alias("date"),
        )
        # 验证 qlib_vwap / factor == amount / volume（用未覆写前的 raw_vwap）
        bad = adjusted.filter(
            (pl.col("vwap") / pl.col("factor") - pl.col("_raw_vwap")).abs() > 1e-9
        )
        if not bad.is_empty():
            raise ValueError(f"{symbol} vwap/factor != amount/volume")
        parts.append(adjusted.select(list(STAGING_COLUMNS)))

    return pl.concat(parts).sort(["symbol", "date"])


def write_staging_by_symbol(frame: pl.DataFrame, output_dir: Path) -> list[Path]:
    """每证券写入一个按日期升序的 Parquet；文件名为 Qlib 小写代码。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for symbol in frame.get_column("symbol").unique().sort().to_list():
        part = frame.filter(pl.col("symbol") == symbol).sort("date")
        path = output_dir / f"{to_qlib_symbol(symbol)}.parquet"
        part.write_parquet(path)
        paths.append(path)
    return paths


def build_snapshot_manifest(
    *,
    files: Sequence[Path],
    source: str,
    universe: str,
    g1_release_id: str,
    g1_release_manifest_sha256: str,
    schema_version: str,
    snapshot_config_sha256: str,
    config_version: str,
) -> dict[str, object]:
    """构建可复现 manifest；元数据从 staging 文件计算，不可由调用者伪造。"""
    if not files:
        raise ValueError("files 不得为空")

    file_entries: list[dict[str, object]] = []
    total_rows = 0
    symbols: set[str] = set()
    min_dates: list[str] = []
    max_dates: list[str] = []
    seen_paths: set[str] = set()
    seen_rel: set[str] = set()
    seen_symbols: set[str] = set()

    for path in sorted(files, key=lambda item: item.name):
        resolved = str(path.resolve())
        if resolved in seen_paths:
            raise ValueError(f"重复文件路径: {path}")
        seen_paths.add(resolved)

        relative_path = path.name
        if relative_path in seen_rel:
            raise ValueError(f"重复 relative_path: {relative_path}")
        seen_rel.add(relative_path)

        payload = path.read_bytes()
        frame = pl.read_parquet(path)
        if frame.is_empty():
            raise ValueError(f"staging Parquet 为空: {relative_path}")
        if list(frame.columns) != list(STAGING_COLUMNS):
            raise ValueError(
                f"staging 列必须精确等于 STAGING_COLUMNS: {relative_path}"
            )

        symbol_vals = frame.get_column("symbol").unique().to_list()
        if len(symbol_vals) != 1:
            raise ValueError(f"staging 文件必须单证券: {relative_path}")
        symbol = str(symbol_vals[0])
        if symbol in seen_symbols:
            raise ValueError(f"重复 symbol: {symbol}")
        seen_symbols.add(symbol)

        expected_name = f"{to_qlib_symbol(symbol)}.parquet"
        if relative_path != expected_name:
            raise ValueError(
                f"文件名必须等于 to_qlib_symbol(symbol)+'.parquet'："
                f"期望 {expected_name}，收到 {relative_path}"
            )

        dates = frame.get_column("date").to_list()
        if len(dates) != len(set(dates)):
            raise ValueError(f"日期不唯一: {relative_path}")
        if dates != sorted(dates):
            raise ValueError(f"日期必须严格升序: {relative_path}")

        _reject_non_finite_staging(frame, relative_path)

        row_count = frame.height
        min_date = frame.get_column("date").min()
        max_date = frame.get_column("date").max()
        min_iso = _iso_date(min_date)
        max_iso = _iso_date(max_date)
        file_entries.append(
            {
                "relative_path": relative_path,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "symbol": symbol,
                "row_count": row_count,
                "min_date": min_iso,
                "max_date": max_iso,
            }
        )
        total_rows += row_count
        symbols.add(symbol)
        min_dates.append(min_iso)
        max_dates.append(max_iso)

    manifest: dict[str, object] = {
        "source": source,
        "universe": universe,
        "g1_release_id": g1_release_id,
        "g1_release_manifest_sha256": g1_release_manifest_sha256,
        "row_count": total_rows,
        "symbol_count": len(symbols),
        "min_date": min(min_dates),
        "max_date": max(max_dates),
        "schema_version": schema_version,
        "config_version": config_version,
        "snapshot_config_sha256": snapshot_config_sha256,
        "adjustment": dict(ADJUSTMENT_SPEC),
        "files": file_entries,
    }
    manifest["snapshot_id"] = _stable_hash(
        {key: value for key, value in manifest.items() if key != "snapshot_id"}
    )
    return manifest


def snapshot_id_from_manifest(manifest: Mapping[str, Any]) -> str:
    body = {key: value for key, value in manifest.items() if key != "snapshot_id"}
    return _stable_hash(body)


def validate_provider(*, provider_dir: Path, expected: DatasetSnapshot) -> None:
    """Fail-closed：无 Qlib 或未 materialize 时显式失败，不把空目录当成功。"""
    if not provider_dir.exists():
        raise FileNotFoundError(f"provider 目录不存在: {provider_dir}")
    if expected.symbol_count <= 0:
        raise ValueError("expected.symbol_count 必须为正")

    try:
        import qlib  # type: ignore[import-not-found]  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Qlib 不可导入，无法执行 provider 逐字段回读；G0/G2 未满足"
        ) from exc

    # 即使 Qlib 可导入，本次也不伪造抽样回读通过；要求实际 features 内容
    feature_dir = provider_dir / "features"
    if not feature_dir.exists() or not any(feature_dir.iterdir()):
        raise RuntimeError(
            "provider 未 materialize（features 为空），G2 逐字段回读未验证"
        )
    raise RuntimeError(
        "当前环境未实现 3 证券 × 20 日期逐字段回读；G2 未验证"
    )


def _iso_date(value: object) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    return str(value)


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reject_duplicates(bars: pl.DataFrame) -> None:
    dup = bars.group_by("symbol", "trade_date").len().filter(pl.col("len") > 1)
    if not dup.is_empty():
        raise ValueError("选中 source 存在重复 (symbol, trade_date)")


def _reject_invalid_rows(bars: pl.DataFrame) -> None:
    numeric_cols = ("open", "high", "low", "close", "volume", "amount", "adj_factor")
    for col in numeric_cols:
        series = bars.get_column(col)
        if series.null_count() > 0:
            raise ValueError(f"选中 source 存在非法 OHLC/amount/volume/factor: {col} null")
        values = series.to_list()
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"选中 source 存在非法 OHLC/amount/volume/factor: {col} 非数值"
                )
            if not math.isfinite(float(value)):
                raise ValueError(
                    f"选中 source 存在非法 OHLC/amount/volume/factor: {col} 非 finite"
                )

    bad = bars.filter(
        (pl.col("open") <= 0)
        | (pl.col("high") <= 0)
        | (pl.col("low") <= 0)
        | (pl.col("close") <= 0)
        | (pl.col("volume") <= 0)
        | (pl.col("amount") <= 0)
        | (pl.col("adj_factor") <= 0)
    )
    if not bad.is_empty():
        raise ValueError("选中 source 存在非正 OHLC/amount/volume/factor")


def _reject_non_finite_staging(frame: pl.DataFrame, relative_path: str) -> None:
    for col in ("open", "high", "low", "close", "vwap", "volume", "factor"):
        series = frame.get_column(col)
        if series.null_count() > 0:
            raise ValueError(f"{relative_path} 存在非 finite 数值: {col}")
        for value in series.to_list():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{relative_path} 存在非 finite 数值: {col}")
            if not math.isfinite(float(value)):
                raise ValueError(f"{relative_path} 存在非 finite 数值: {col}")
