"""M3 数据与运行时就绪审计。不安装依赖、不联网。"""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import polars as pl

from quant.domain import BenchmarkBar1dSchema


@dataclass(frozen=True)
class ReadinessIssue:
    code: str
    severity: Literal["ERROR", "WARNING"]
    message: str


_REQUIRED_BAR_FIELDS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adj_factor",
    "source",
)

_REQUIRED_BENCHMARK_FIELDS = (
    "benchmark",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "source",
    "source_snapshot_id",
)

_M3_BENCHMARK = "H00300.CSI"


def audit_m3_readiness(
    *,
    bars: pl.DataFrame,
    instruments: pl.DataFrame,
    membership: pl.DataFrame,
    calendars: pl.DataFrame,
    benchmark_bars: pl.DataFrame,
    config: Mapping[str, Any],
) -> list[ReadinessIssue]:
    """检查字段契约、PIT 覆盖、基准、交易日、因子、训练长度、截面、embargo 与运行时。

    缺前置字段时记录结构化 ERROR 并跳过依赖检查，函数本身不因契约错误抛异常。
    """
    issues: list[ReadinessIssue] = []
    data_cfg = dict(config.get("data", {}) or {})
    labels_cfg = dict(config.get("labels", {}) or {})
    walk_cfg = dict(config.get("walk_forward", {}) or {})
    runtime_cfg = dict((config.get("runtime", {}) or {}).get("qlib", {}) or {})

    start_date, end_date, date_issues = _parse_config_dates(data_cfg)
    issues.extend(date_issues)

    source, source_issues = _parse_config_source(data_cfg)
    issues.extend(source_issues)

    universe = str(data_cfg.get("universe", "CSI300_PIT"))
    benchmark = str(data_cfg.get("benchmark", _M3_BENCHMARK))
    try:
        min_train = int(data_cfg.get("minimum_train_sessions", 756))
        min_cross = int(data_cfg.get("minimum_cross_section_symbols", 100))
    except (TypeError, ValueError):
        issues.append(_error("CONFIG_INVALID", "minimum_train/cross_section 必须为整数"))
        min_train, min_cross = 756, 100

    try:
        horizons = [int(h) for h in labels_cfg.get("horizons_sessions", [5, 10])]
        embargo = int(walk_cfg.get("embargo_sessions", 0))
    except (TypeError, ValueError):
        issues.append(_error("CONFIG_INVALID", "horizons/embargo 必须为整数"))
        horizons, embargo = [5, 10], 0

    supported_python = str(runtime_cfg.get("supported_python", ">=3.8,<3.13"))

    bars_ok = _has_columns(bars, _REQUIRED_BAR_FIELDS)
    if not bars_ok:
        issues.extend(_missing_field_issues(bars, "BARS_MISSING_FIELDS", "bars", _REQUIRED_BAR_FIELDS))

    bench_ok, _, bench_structure_issues = _benchmark_column_gate(benchmark_bars)
    issues.extend(bench_structure_issues)

    instruments_ok = _has_columns(instruments, {"symbol", "market", "list_date", "status"})
    if not instruments_ok:
        issues.extend(
            _missing_field_issues(
                instruments,
                "INSTRUMENTS_MISSING_FIELDS",
                "instruments",
                ("symbol", "market", "list_date", "status"),
            )
        )
    elif instruments.is_empty():
        issues.append(_error("INSTRUMENTS_EMPTY", "instruments 为空"))

    membership_ok = _has_columns(membership, {"universe", "symbol", "effective_from"})
    if not membership_ok:
        issues.extend(
            _missing_field_issues(
                membership,
                "MEMBERSHIP_MISSING_FIELDS",
                "membership",
                ("universe", "symbol", "effective_from"),
            )
        )

    calendars_ok = _has_columns(calendars, {"market", "date", "is_open"})
    if not calendars_ok:
        issues.extend(
            _missing_field_issues(
                calendars,
                "CALENDAR_MISSING_FIELDS",
                "calendars",
                ("market", "date", "is_open"),
            )
        )

    selected_bars: pl.DataFrame | None = None
    selected_bench: pl.DataFrame | None = None
    if source is not None and bars_ok:
        selected_bars = bars.filter(pl.col("source") == source)
        if selected_bars.is_empty():
            issues.append(
                _error("DATA_SOURCE_MISSING", f"bars 中不存在 source={source}")
            )
            selected_bars = None
            bars_ok = False

    # 基准：列门禁后先投影必需列并走生产 Schema，再只消费 validate 返回值做
    # source / duplicate / identity / coverage；extra 列的 INVALID 已由 gate 记录。
    if bench_ok:
        projection = benchmark_bars.select(list(_REQUIRED_BENCHMARK_FIELDS))
        validated_bench, schema_issues = _validate_benchmark_bars(projection)
        issues.extend(schema_issues)
        if validated_bench is not None:
            if validated_bench.is_empty():
                issues.append(_error("BENCHMARK_EMPTY", f"基准 {benchmark} 行情为空"))
            elif source is not None:
                selected_bench = validated_bench.filter(pl.col("source") == source)
                if selected_bench.is_empty():
                    issues.append(
                        _error(
                            "DATA_SOURCE_MISSING",
                            f"benchmark_bars 中不存在 source={source}",
                        )
                    )
                    selected_bench = None

    if selected_bars is not None:
        issues.extend(_check_duplicate_bars(selected_bars, "BARS_DUPLICATE_KEYS"))
        issues.extend(_check_positive_factor(selected_bars, "FACTOR_NON_POSITIVE"))
        issues.extend(_check_non_finite_bars(selected_bars, "BARS_NON_FINITE"))
    if selected_bench is not None:
        issues.extend(
            _check_duplicate_benchmark_keys(selected_bench, "BENCHMARK_DUPLICATE_KEYS")
        )

    if benchmark != _M3_BENCHMARK:
        issues.append(
            _error(
                "BENCHMARK_SYMBOL_MISMATCH",
                f"M3 v1 仅接受基准 {_M3_BENCHMARK}，配置为 {benchmark}",
            )
        )
    elif selected_bench is not None:
        issues.extend(_check_benchmark_identity(selected_bench, benchmark))

    if membership_ok:
        matched = membership.filter(pl.col("universe") == universe)
        if matched.is_empty():
            issues.append(
                _error("PIT_MEMBERSHIP_MISSING", f"缺少股票池 {universe} 的历史成分记录")
            )
            membership_ok = False

    if calendars_ok:
        open_days = calendars.filter((pl.col("market") == "SH") & pl.col("is_open"))
        if open_days.is_empty():
            issues.append(_error("CALENDAR_NO_OPEN_DAYS", "SH 交易日历没有开市日"))
            calendars_ok = False

    # selected_bench 已是 Schema 返回的规范投影（经 source 过滤）；extra 不阻止独立覆盖收集
    if (
        selected_bars is not None
        and membership_ok
        and calendars_ok
        and start_date is not None
        and end_date is not None
    ):
        issues.extend(
            _check_dense_coverage(
                bars=selected_bars,
                membership=membership,
                calendars=calendars,
                benchmark_bars=selected_bench,
                universe=universe,
                benchmark=benchmark,
                start_date=start_date,
                end_date=end_date,
                min_train=min_train,
                min_cross=min_cross,
            )
        )
    elif selected_bars is not None and calendars_ok:
        issues.extend(_check_calendar_coverage(selected_bars, calendars))
    issues.extend(_check_embargo(horizons, embargo))
    issues.extend(_check_python_version(supported_python))
    issues.extend(_check_qlib_importable())

    return sorted(issues, key=lambda item: (item.severity, item.code, item.message))


def _error(code: str, message: str) -> ReadinessIssue:
    return ReadinessIssue(code=code, severity="ERROR", message=message)


def _has_columns(frame: pl.DataFrame, required: set[str] | tuple[str, ...]) -> bool:
    return set(required).issubset(frame.columns)


def _exact_benchmark_columns(frame: pl.DataFrame) -> bool:
    return set(frame.columns) == set(_REQUIRED_BENCHMARK_FIELDS)


def _benchmark_column_gate(
    frame: pl.DataFrame,
) -> tuple[bool, bool, list[ReadinessIssue]]:
    """Column gate before dependent Polars work.

    Returns ``(has_required, is_exact, issues)``. Missing required columns block
    downstream work; unknown extras emit ``BENCHMARK_INVALID`` but still allow
    coverage collection on the required projection.
    """
    missing = sorted(set(_REQUIRED_BENCHMARK_FIELDS) - set(frame.columns))
    if missing:
        return False, False, [
            _error(
                "BENCHMARK_MISSING_FIELDS",
                f"benchmark_bars 缺少字段: {', '.join(missing)}",
            )
        ]
    if not _exact_benchmark_columns(frame):
        return True, False, [
            _error(
                "BENCHMARK_INVALID",
                "benchmark_bars 列集合不符合 BenchmarkBar1dSchema",
            )
        ]
    return True, True, []


def _validate_benchmark_bars(
    frame: pl.DataFrame,
) -> tuple[pl.DataFrame | None, list[ReadinessIssue]]:
    """Run production Schema on required projection; return coerced frame or None.

    Never leak validator / Polars text. Callers must consume the returned frame
    only — not the pre-validate input — because Config.coerce=True.
    """
    try:
        validated = BenchmarkBar1dSchema.validate(frame)
    except Exception:
        return None, [
            _error(
                "BENCHMARK_INVALID",
                "benchmark_bars 不符合 BenchmarkBar1dSchema",
            )
        ]
    return validated, []


def _missing_field_issues(
    frame: pl.DataFrame,
    code: str,
    name: str,
    required: tuple[str, ...],
) -> list[ReadinessIssue]:
    missing = sorted(set(required) - set(frame.columns))
    if not missing:
        return []
    return [_error(code, f"{name} 缺少字段: {', '.join(missing)}")]


def _parse_config_source(
    data_cfg: Mapping[str, Any],
) -> tuple[str | None, list[ReadinessIssue]]:
    value = data_cfg.get("source")
    if value is None:
        return None, [_error("CONFIG_INVALID", "data.source 缺失")]
    if not isinstance(value, str) or not value.strip():
        return None, [_error("CONFIG_INVALID", "data.source 缺失或为空")]
    return value.strip(), []


def _parse_config_dates(
    data_cfg: Mapping[str, Any],
) -> tuple[dt.date | None, dt.date | None, list[ReadinessIssue]]:
    issues: list[ReadinessIssue] = []
    start = _coerce_date(data_cfg.get("start_date"), "data.start_date", issues)
    end = _coerce_date(data_cfg.get("end_date"), "data.end_date", issues)
    if start is not None and end is not None and end < start:
        issues.append(_error("CONFIG_INVALID", "data.end_date 不得早于 data.start_date"))
        return None, None, issues
    return start, end, issues


def _coerce_date(
    value: object, field: str, issues: list[ReadinessIssue]
) -> dt.date | None:
    if value is None:
        issues.append(_error("CONFIG_INVALID", f"{field} 缺失"))
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            issues.append(_error("CONFIG_INVALID", f"{field} 不是合法 ISO 日期: {value}"))
            return None
    issues.append(_error("CONFIG_INVALID", f"{field} 类型非法: {type(value).__name__}"))
    return None


def _check_duplicate_bars(frame: pl.DataFrame, code: str) -> list[ReadinessIssue]:
    dup = frame.group_by("symbol", "trade_date").len().filter(pl.col("len") > 1)
    if dup.is_empty():
        return []
    return [_error(code, f"存在 {dup.height} 组重复 (symbol, trade_date)")]


def _check_duplicate_benchmark_keys(
    frame: pl.DataFrame, code: str
) -> list[ReadinessIssue]:
    dup = (
        frame.group_by("benchmark", "trade_date", "source")
        .len()
        .filter(pl.col("len") > 1)
    )
    if dup.is_empty():
        return []
    return [_error(code, f"存在 {dup.height} 组重复 (benchmark, trade_date, source)")]


def _check_positive_factor(frame: pl.DataFrame, code: str) -> list[ReadinessIssue]:
    bad = frame.filter(pl.col("adj_factor").is_not_null() & (pl.col("adj_factor") <= 0))
    if bad.is_empty():
        return []
    return [_error(code, f"存在 {bad.height} 行非正复权因子")]


def _check_non_finite_bars(frame: pl.DataFrame, code: str) -> list[ReadinessIssue]:
    """任一 OHLC/volume/adj_factor 非 finite 时返回 ERROR。"""
    mask = (
        pl.col("open").is_null()
        | pl.col("high").is_null()
        | pl.col("low").is_null()
        | pl.col("close").is_null()
        | pl.col("volume").is_null()
        | pl.col("adj_factor").is_null()
        | ~pl.col("open").is_finite()
        | ~pl.col("high").is_finite()
        | ~pl.col("low").is_finite()
        | ~pl.col("close").is_finite()
        | ~pl.col("volume").is_finite()
        | ~pl.col("adj_factor").is_finite()
    )
    bad = frame.filter(mask)
    if bad.is_empty():
        return []
    return [_error(code, f"存在 {bad.height} 行非 finite OHLC/volume/adj_factor")]


def _valid_bars(frame: pl.DataFrame) -> pl.DataFrame:
    """有效行情：OHLC/volume/adj_factor 完整、finite 且合法。"""
    return frame.filter(
        pl.col("open").is_not_null()
        & pl.col("high").is_not_null()
        & pl.col("low").is_not_null()
        & pl.col("close").is_not_null()
        & pl.col("volume").is_not_null()
        & pl.col("adj_factor").is_not_null()
        & pl.col("open").is_finite()
        & pl.col("high").is_finite()
        & pl.col("low").is_finite()
        & pl.col("close").is_finite()
        & pl.col("volume").is_finite()
        & pl.col("adj_factor").is_finite()
        & (pl.col("open") > 0)
        & (pl.col("high") > 0)
        & (pl.col("low") > 0)
        & (pl.col("close") > 0)
        & (pl.col("volume") >= 0)
        & (pl.col("adj_factor") > 0)
        & (pl.col("high") >= pl.col("low"))
        & (pl.col("high") >= pl.col("open"))
        & (pl.col("high") >= pl.col("close"))
        & (pl.col("low") <= pl.col("open"))
        & (pl.col("low") <= pl.col("close"))
    )


def _valid_benchmark_bars(frame: pl.DataFrame) -> pl.DataFrame:
    """有效基准：仅 OHLC 完整、finite 且合法，不含股票专属列。"""
    return frame.filter(
        pl.col("open").is_not_null()
        & pl.col("high").is_not_null()
        & pl.col("low").is_not_null()
        & pl.col("close").is_not_null()
        & pl.col("open").is_finite()
        & pl.col("high").is_finite()
        & pl.col("low").is_finite()
        & pl.col("close").is_finite()
        & (pl.col("open") > 0)
        & (pl.col("high") > 0)
        & (pl.col("low") > 0)
        & (pl.col("close") > 0)
        & (pl.col("high") >= pl.col("low"))
        & (pl.col("high") >= pl.col("open"))
        & (pl.col("high") >= pl.col("close"))
        & (pl.col("low") <= pl.col("open"))
        & (pl.col("low") <= pl.col("close"))
    )


def _check_dense_coverage(
    *,
    bars: pl.DataFrame,
    membership: pl.DataFrame,
    calendars: pl.DataFrame,
    benchmark_bars: pl.DataFrame | None,
    universe: str,
    benchmark: str,
    start_date: dt.date,
    end_date: dt.date,
    min_train: int,
    min_cross: int,
) -> list[ReadinessIssue]:
    issues: list[ReadinessIssue] = []
    open_dates = (
        calendars.filter(
            (pl.col("market") == "SH")
            & pl.col("is_open")
            & (pl.col("date") >= start_date)
            & (pl.col("date") <= end_date)
        )
        .sort("date")
        .get_column("date")
        .to_list()
    )
    if not open_dates:
        return [_error("CALENDAR_NO_OPEN_DAYS", "配置区间内没有 SH 开市日")]

    members = membership.filter(pl.col("universe") == universe)
    if "effective_to" not in members.columns:
        members = members.with_columns(pl.lit(None).cast(pl.Date).alias("effective_to"))

    valid = _valid_bars(bars)
    daily_counts: list[tuple[dt.date, int]] = []
    for day in open_dates:
        active = members.filter(
            (pl.col("effective_from") <= day)
            & (pl.col("effective_to").is_null() | (pl.col("effective_to") >= day))
        )
        active_symbols = set(active.get_column("symbol").to_list())
        if not active_symbols:
            daily_counts.append((day, 0))
            continue
        n = (
            valid.filter(
                (pl.col("trade_date") == day)
                & pl.col("symbol").is_in(sorted(active_symbols))
            )
            .select("symbol")
            .unique()
            .height
        )
        daily_counts.append((day, n))

    below = [(day, n) for day, n in daily_counts if n < min_cross]
    if below:
        min_n = min(n for _, n in below)
        issues.append(
            _error(
                "CROSS_SECTION_TOO_SMALL",
                f"逐日截面最小值 {min_n} 低于阈值 {min_cross}，受影响日数 {len(below)}",
            )
        )

    bench_dates: set[dt.date] = set()
    if (
        benchmark_bars is not None
        and _exact_benchmark_columns(benchmark_bars)
        and benchmark == _M3_BENCHMARK
    ):
        bench_valid = _valid_benchmark_bars(
            benchmark_bars.filter(pl.col("benchmark") == benchmark)
        )
        bench_dates = set(bench_valid.get_column("trade_date").to_list())
        if not bench_dates:
            issues.append(_error("BENCHMARK_EMPTY", f"基准 {benchmark} 行情为空"))
        missing_bench = [day for day in open_dates if day not in bench_dates]
        if missing_bench:
            issues.append(
                _error(
                    "BENCHMARK_DATE_COVERAGE",
                    f"基准 {benchmark} 在配置区间内缺少 {len(missing_bench)} 个开市日",
                )
            )

    trainable = [
        day for day, n in daily_counts if n >= min_cross and day in bench_dates
    ]
    if len(trainable) < min_train:
        issues.append(
            _error(
                "HISTORY_TOO_SHORT",
                f"可训练 session 仅 {len(trainable)}，少于最小训练长度 {min_train}",
            )
        )

    for row in members.iter_rows(named=True):
        symbol = row["symbol"]
        eff_from = max(row["effective_from"], start_date)
        eff_to_raw = row["effective_to"]
        eff_to = end_date if eff_to_raw is None else min(eff_to_raw, end_date)
        if eff_to < eff_from:
            continue
        covered = valid.filter(
            (pl.col("symbol") == symbol)
            & (pl.col("trade_date") >= eff_from)
            & (pl.col("trade_date") <= eff_to)
        )
        if covered.is_empty():
            issues.append(
                _error(
                    "PIT_BAR_COVERAGE_EMPTY",
                    f"股票池成员 {symbol} 在生效区间 [{eff_from.isoformat()}, "
                    f"{eff_to.isoformat()}] 没有任何有效行情",
                )
            )

    bad_dates = sorted(set(bars.get_column("trade_date").to_list()) - set(open_dates))
    bad_in_range = [d for d in bad_dates if start_date <= d <= end_date]
    if bad_in_range:
        issues.append(
            _error(
                "BAR_DATE_NOT_IN_CALENDAR",
                f"有 {len(bad_in_range)} 个行情日不在配置区间 SH 开市日历中",
            )
        )
    return issues


def _check_calendar_coverage(
    bars: pl.DataFrame, calendars: pl.DataFrame
) -> list[ReadinessIssue]:
    open_dates = set(
        calendars.filter((pl.col("market") == "SH") & pl.col("is_open"))
        .get_column("date")
        .to_list()
    )
    if not open_dates:
        return []
    bad_dates = sorted(set(bars.get_column("trade_date").to_list()) - open_dates)
    if bad_dates:
        return [
            _error(
                "BAR_DATE_NOT_IN_CALENDAR",
                f"有 {len(bad_dates)} 个行情日不在 SH 开市日历中",
            )
        ]
    return []


def _check_benchmark_identity(
    benchmark_bars: pl.DataFrame, benchmark: str
) -> list[ReadinessIssue]:
    foreign = benchmark_bars.filter(pl.col("benchmark") != benchmark)
    if not foreign.is_empty():
        return [
            _error(
                "BENCHMARK_SYMBOL_MISMATCH",
                f"benchmark_bars 含非配置基准，期望 {benchmark}",
            )
        ]
    matched = benchmark_bars.filter(pl.col("benchmark") == benchmark)
    if matched.is_empty():
        return [_error("BENCHMARK_EMPTY", f"基准 {benchmark} 行情为空")]
    return []


def _check_embargo(horizons: list[int], embargo_sessions: int) -> list[ReadinessIssue]:
    if not horizons:
        return [_error("HORIZON_EMPTY", "labels.horizons_sessions 为空")]
    max_h = max(horizons)
    if embargo_sessions < max_h:
        return [
            _error(
                "EMBARGO_TOO_SMALL",
                f"embargo_sessions={embargo_sessions} 小于最大 horizon={max_h}",
            )
        ]
    return []


def _check_python_version(supported_python: str) -> list[ReadinessIssue]:
    current = f"{sys.version_info.major}.{sys.version_info.minor}"
    ok = True
    for part in supported_python.split(","):
        part = part.strip()
        if part.startswith(">="):
            ok = ok and _version_tuple(current) >= _version_tuple(part[2:])
        elif part.startswith("<"):
            ok = ok and _version_tuple(current) < _version_tuple(part[1:])
        elif part.startswith("=="):
            ok = ok and current == part[2:]
    if ok:
        return []
    return [
        _error(
            "PYTHON_UNSUPPORTED",
            f"当前 Python {current} 不满足 Qlib 支持范围 {supported_python}",
        )
    ]


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(".")[:2])


def _check_qlib_importable() -> list[ReadinessIssue]:
    try:
        import qlib  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return [
            _error(
                "QLIB_NOT_IMPORTABLE",
                "当前环境无法 import qlib；meta.enabled 必须保持 false",
            )
        ]
    return []
