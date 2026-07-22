"""B2B: G1 core mappers over real VerifiedRawResponse."""

from __future__ import annotations

import datetime as dt
import importlib
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from quant.data import m3_backfill as backfill
from quant.data.m3_backfill import (
    TUSHARE_FIELDS,
    TushareRequestReceipt,
    TushareRequestSpec,
    VerifiedRawResponse,
    response_content_sha256,
)
from quant.data.m3_mappers import (
    M3G1MappingError,
    map_g1_adjustment_factor_response,
    map_g1_benchmark_response,
    map_g1_daily_response,
    map_g1_suspension_response,
)
from quant.domain import BenchmarkBar1dSchema, Suspension1dSchema

_HEX = "a" * 64
_START = "20260105"
_END = "20260106"
_SYMBOL = "000001.SZ"
_BENCHMARK = "H00300.CSI"


def _make_verified(
    endpoint: str,
    frame: pl.DataFrame,
    *,
    parameters: dict[str, str] | None = None,
) -> VerifiedRawResponse:
    params = {
        "fields": TUSHARE_FIELDS[endpoint],
        **(parameters or {}),
    }
    if endpoint == "suspend_d":
        params.setdefault("start_date", _START)
        params.setdefault("end_date", _END)
        params.setdefault("suspend_type", "S")
    elif endpoint == "dividend":
        params.setdefault("ts_code", _SYMBOL)
    else:
        params.setdefault("start_date", _START)
        params.setdefault("end_date", _END)
        if endpoint in {"daily", "adj_factor", "stk_limit"}:
            params.setdefault("ts_code", _SYMBOL)
        elif endpoint == "index_daily":
            params.setdefault("ts_code", _BENCHMARK)
        elif endpoint == "index_weight":
            params.setdefault("index_code", "000300.SH")
    spec = TushareRequestSpec.create(endpoint=endpoint, parameters=params)
    content = response_content_sha256(frame, endpoint)
    columns = tuple(frame.columns)
    parameters_sha256 = backfill._parameters_hash(spec.parameters)
    stable = backfill._stable_response_hash_values(
        {
            "request_id": spec.request_id,
            "endpoint": endpoint,
            "parameters_sha256": parameters_sha256,
            "response_content_sha256": content,
            "row_count": frame.height,
            "columns": columns,
        }
    )
    receipt = TushareRequestReceipt(
        schema_version="m3-g1-tushare-receipt-v1",
        request_id=spec.request_id,
        endpoint=endpoint,  # type: ignore[arg-type]
        parameters=spec.parameters,
        parameters_sha256=parameters_sha256,
        raw_snapshot_id=spec.request_id,
        raw_data_path=f"tushare/{endpoint}/request=x/data.parquet",
        raw_metadata_path=f"tushare/{endpoint}/request=x/metadata.json",
        raw_file_sha256=_HEX,
        raw_metadata_sha256=_HEX,
        response_content_sha256=content,
        stable_response_sha256=stable,
        raw_size_bytes=max(frame.height, 1),
        row_count=frame.height,
        columns=columns,
    )
    receipt_sha256 = backfill._sha256(asdict(receipt))
    return VerifiedRawResponse(spec, receipt, receipt_sha256, frame)


def _daily_frame(*, rows: list[dict[str, Any]] | None = None) -> pl.DataFrame:
    default = [
        {
            "ts_code": _SYMBOL,
            "trade_date": "20260106",
            "open": 11.0,
            "high": 12.0,
            "low": 10.0,
            "close": 11.5,
            "pre_close": 10.5,
            "change": 1.0,
            "pct_chg": 1.0,
            "vol": 1.5,
            "amount": 2.5,
        },
        {
            "ts_code": _SYMBOL,
            "trade_date": "20260105",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "pre_close": 9.5,
            "change": 1.0,
            "pct_chg": 1.0,
            "vol": 3.0,
            "amount": 4.0,
        },
    ]
    return pl.DataFrame(rows if rows is not None else default).select(
        TUSHARE_FIELDS["daily"].split(",")
    )


def _factor_frame(*, factors: list[float] | None = None) -> pl.DataFrame:
    values = factors if factors is not None else [1.0, 1.0, 2.0]
    dates = ["20260105", "20260106", "20260107"][: len(values)]
    return pl.DataFrame(
        {
            "ts_code": [_SYMBOL] * len(values),
            "trade_date": dates,
            "adj_factor": values,
        }
    ).select(TUSHARE_FIELDS["adj_factor"].split(","))


def _bench_frame(*, rows: list[dict[str, Any]] | None = None) -> pl.DataFrame:
    default = [
        {
            "ts_code": _BENCHMARK,
            "trade_date": "20260106",
            "open": 101.0,
            "high": 102.0,
            "low": 100.0,
            "close": 101.5,
            "pre_close": 100.5,
            "change": 1.0,
            "pct_chg": 1.0,
            "vol": 0.0,
            "amount": 0.0,
        },
        {
            "ts_code": _BENCHMARK,
            "trade_date": "20260105",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "pre_close": 99.5,
            "change": 1.0,
            "pct_chg": 1.0,
            "vol": 0.0,
            "amount": 0.0,
        },
    ]
    return pl.DataFrame(rows if rows is not None else default).select(
        TUSHARE_FIELDS["index_daily"].split(",")
    )


def _suspend_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(rows).select(TUSHARE_FIELDS["suspend_d"].split(","))


def test_daily_sorts_and_converts_units() -> None:
    out = map_g1_daily_response(response=_make_verified("daily", _daily_frame()))
    assert out.columns == [
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "source",
    ]
    assert out.get_column("trade_date").to_list() == [
        dt.date(2026, 1, 5),
        dt.date(2026, 1, 6),
    ]
    assert out.get_column("volume").to_list() == [300.0, 150.0]
    assert out.get_column("amount").to_list() == [4000.0, 2500.0]
    assert out.dtypes == [
        pl.Utf8,
        pl.Date,
        pl.Float64,
        pl.Float64,
        pl.Float64,
        pl.Float64,
        pl.Float64,
        pl.Float64,
        pl.Utf8,
    ]
    assert "adj_factor" not in out.columns


def test_endpoint_swap_rejected() -> None:
    daily = _make_verified("daily", _daily_frame())
    factor = _make_verified(
        "adj_factor",
        _factor_frame(factors=[1.0, 2.0]),
        parameters={"start_date": _START, "end_date": "20260107", "ts_code": _SYMBOL},
    )
    bench = _make_verified("index_daily", _bench_frame())
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_ENDPOINT_MISMATCH"):
        map_g1_daily_response(response=factor)
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_ENDPOINT_MISMATCH"):
        map_g1_adjustment_factor_response(response=daily)
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_ENDPOINT_MISMATCH"):
        map_g1_benchmark_response(response=daily)
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_ENDPOINT_MISMATCH"):
        map_g1_daily_response(response=bench)


def test_spec_symbol_frame_mismatch_rejected() -> None:
    rows = _daily_frame().with_columns(pl.lit("600000.SH").alias("ts_code"))
    response = _make_verified("daily", rows.select(TUSHARE_FIELDS["daily"].split(",")))
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_REQUEST_SCOPE_MISMATCH"):
        map_g1_daily_response(response=response)


def test_columns_missing_extra_reordered_rejected() -> None:
    base = _daily_frame()
    missing = base.drop("amount")
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_COLUMNS_INVALID"):
        map_g1_daily_response(response=_make_verified("daily", missing))

    extra = base.with_columns(pl.lit(1.0).alias("extra"))
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_COLUMNS_INVALID"):
        map_g1_daily_response(response=_make_verified("daily", extra))

    reordered = base.select(["amount", *base.columns[:-1]])
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_COLUMNS_INVALID"):
        map_g1_daily_response(response=_make_verified("daily", reordered))

    with pytest.raises(M3G1MappingError, match="G1_MAPPER_RESPONSE_INVALID"):
        map_g1_daily_response(response=object())  # type: ignore[arg-type]


def test_value_invalid_cases() -> None:
    bad_date = _daily_frame(
        rows=[
            {
                "ts_code": _SYMBOL,
                "trade_date": "2026-01-05",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "pre_close": 9.5,
                "change": 1.0,
                "pct_chg": 1.0,
                "vol": 1.0,
                "amount": 1.0,
            }
        ]
    )
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_VALUE_INVALID"):
        map_g1_daily_response(response=_make_verified("daily", bad_date))

    oob = _daily_frame(
        rows=[
            {
                "ts_code": _SYMBOL,
                "trade_date": "20260107",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "pre_close": 9.5,
                "change": 1.0,
                "pct_chg": 1.0,
                "vol": 1.0,
                "amount": 1.0,
            }
        ]
    )
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_REQUEST_SCOPE_MISMATCH"):
        map_g1_daily_response(response=_make_verified("daily", oob))

    for bad in ["10.0", None]:
        data = _daily_frame().head(1).to_dicts()[0]
        data["open"] = bad
        frame = pl.DataFrame([data]).select(TUSHARE_FIELDS["daily"].split(","))
        with pytest.raises(M3G1MappingError, match="G1_MAPPER_VALUE_INVALID"):
            map_g1_daily_response(response=_make_verified("daily", frame))

    # NaN/Infinity 无法进入合法 VerifiedRawResponse（B2A content digest fail-closed）；
    # 仍覆盖 mapper 数值门禁本身。
    from quant.data.m3_mappers import _parse_finite_number

    for bad in [float("nan"), float("inf")]:
        with pytest.raises(M3G1MappingError, match="G1_MAPPER_VALUE_INVALID"):
            _parse_finite_number(bad)
        with pytest.raises(backfill.M3BackfillError):
            response_content_sha256(
                _daily_frame().with_columns(pl.lit(bad).alias("open")),
                "daily",
            )


def test_ohlc_volume_factor_and_duplicate_keys() -> None:
    bad_ohlc = _daily_frame().head(1).with_columns(
        (pl.col("high") + 1).alias("low")
    )
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_VALUE_INVALID"):
        map_g1_daily_response(
            response=_make_verified("daily", bad_ohlc.select(TUSHARE_FIELDS["daily"].split(",")))
        )

    neg_vol = _daily_frame().head(1).with_columns(pl.lit(-1.0).alias("vol"))
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_VALUE_INVALID"):
        map_g1_daily_response(
            response=_make_verified("daily", neg_vol.select(TUSHARE_FIELDS["daily"].split(",")))
        )

    for factor in [0.0, -1.0]:
        with pytest.raises(M3G1MappingError, match="G1_MAPPER_VALUE_INVALID"):
            map_g1_adjustment_factor_response(
                response=_make_verified(
                    "adj_factor",
                    _factor_frame(factors=[factor]),
                    parameters={
                        "start_date": _START,
                        "end_date": _START,
                        "ts_code": _SYMBOL,
                    },
                )
            )

    dup_daily = pl.concat([_daily_frame().head(1), _daily_frame().head(1)])
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_DUPLICATE_KEY"):
        map_g1_daily_response(response=_make_verified("daily", dup_daily))

    dup_factor = pl.concat(
        [_factor_frame(factors=[1.0]), _factor_frame(factors=[2.0])]
    )
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_DUPLICATE_KEY"):
        map_g1_adjustment_factor_response(
            response=_make_verified(
                "adj_factor",
                dup_factor,
                parameters={
                    "start_date": _START,
                    "end_date": _START,
                    "ts_code": _SYMBOL,
                },
            )
        )

    dup_bench = pl.concat([_bench_frame().head(1), _bench_frame().head(1)])
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_DUPLICATE_KEY"):
        map_g1_benchmark_response(response=_make_verified("index_daily", dup_bench))


def test_factor_keeps_identical_consecutive_values() -> None:
    out = map_g1_adjustment_factor_response(
        response=_make_verified(
            "adj_factor",
            _factor_frame(factors=[1.0, 1.0, 2.0]),
            parameters={
                "start_date": _START,
                "end_date": "20260107",
                "ts_code": _SYMBOL,
            },
        )
    )
    assert out.height == 3
    assert out.get_column("adj_factor").to_list() == [1.0, 1.0, 2.0]


def test_benchmark_output_schema() -> None:
    out = map_g1_benchmark_response(response=_make_verified("index_daily", _bench_frame()))
    assert "symbol" not in out.columns
    assert "volume" not in out.columns
    assert "amount" not in out.columns
    assert "adj_factor" not in out.columns
    BenchmarkBar1dSchema.validate(out)
    assert out.get_column("source_snapshot_id").to_list()[0] == (
        _make_verified("index_daily", _bench_frame()).receipt.raw_snapshot_id
    )


def test_suspension_cases() -> None:
    empty = _make_verified(
        "suspend_d",
        pl.DataFrame(schema={c: pl.Utf8 for c in TUSHARE_FIELDS["suspend_d"].split(",")}),
    )
    out_empty = map_g1_suspension_response(response=empty)
    assert out_empty.height == 0
    assert list(out_empty.columns) == [
        "symbol",
        "trade_date",
        "suspension_scope",
        "suspension_detail",
        "source",
        "source_snapshot_id",
    ]
    Suspension1dSchema.validate(out_empty)

    full = _suspend_frame(
        [
            {
                "ts_code": _SYMBOL,
                "trade_date": "20260105",
                "suspend_timing": None,
                "suspend_type": "S",
            }
        ]
    )
    out_full = map_g1_suspension_response(response=_make_verified("suspend_d", full))
    assert out_full.to_dicts()[0]["suspension_scope"] == "FULL_DAY"
    assert out_full.to_dicts()[0]["suspension_detail"] is None

    partial = _suspend_frame(
        [
            {
                "ts_code": _SYMBOL,
                "trade_date": "20260105",
                "suspend_timing": "09:30-10:00",
                "suspend_type": "S",
            }
        ]
    )
    out_partial = map_g1_suspension_response(response=_make_verified("suspend_d", partial))
    assert out_partial.to_dicts()[0]["suspension_scope"] == "PARTIAL"
    assert out_partial.to_dicts()[0]["suspension_detail"] == "09:30-10:00"

    multi = _suspend_frame(
        [
            {
                "ts_code": _SYMBOL,
                "trade_date": "20260105",
                "suspend_timing": "b-detail",
                "suspend_type": "S",
            },
            {
                "ts_code": _SYMBOL,
                "trade_date": "20260105",
                "suspend_timing": "a-detail",
                "suspend_type": "S",
            },
            {
                "ts_code": _SYMBOL,
                "trade_date": "20260105",
                "suspend_timing": "a-detail",
                "suspend_type": "S",
            },
        ]
    )
    out_multi = map_g1_suspension_response(response=_make_verified("suspend_d", multi))
    assert out_multi.height == 1
    assert out_multi.to_dicts()[0]["suspension_detail"] == "a-detail | b-detail"

    conflict = _suspend_frame(
        [
            {
                "ts_code": _SYMBOL,
                "trade_date": "20260105",
                "suspend_timing": None,
                "suspend_type": "S",
            },
            {
                "ts_code": _SYMBOL,
                "trade_date": "20260105",
                "suspend_timing": "09:30-10:00",
                "suspend_type": "S",
            },
        ]
    )
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_SUSPENSION_CONFLICT"):
        map_g1_suspension_response(response=_make_verified("suspend_d", conflict))

    non_s = _suspend_frame(
        [
            {
                "ts_code": _SYMBOL,
                "trade_date": "20260105",
                "suspend_timing": None,
                "suspend_type": "R",
            }
        ]
    )
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_VALUE_INVALID"):
        map_g1_suspension_response(response=_make_verified("suspend_d", non_s))


def test_input_order_does_not_affect_output() -> None:
    a = map_g1_daily_response(response=_make_verified("daily", _daily_frame()))
    reversed_rows = _daily_frame().reverse()
    b = map_g1_daily_response(response=_make_verified("daily", reversed_rows))
    assert a.to_dict(as_series=False) == b.to_dict(as_series=False)


def test_error_surfaces_are_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _make_verified("daily", _daily_frame())

    class Boom(ValueError):
        def __str__(self) -> str:
            return "/abs/path/secret token=abcd1234 row={'ts_code': 'X'}"

    import quant.data.m3_mappers as mappers

    def explode(*_a: Any, **_k: Any) -> Any:
        raise Boom()

    monkeypatch.setattr(mappers, "_parse_ohlc", explode)
    with pytest.raises(M3G1MappingError) as excinfo:
        map_g1_daily_response(response=response)
    err = excinfo.value
    for surface in (str(err), repr(err), err.code, f"{err}"):
        assert "/abs/path" not in surface
        assert "token=" not in surface
        assert "ts_code" not in surface
    assert err.__cause__ is None


def test_import_does_not_pull_research_or_token() -> None:
    banned_prefixes = ("quant.research",)
    before = {name for name in sys.modules if name.startswith(banned_prefixes)}
    mod = importlib.import_module("quant.data.m3_mappers")
    source_path = Path(mod.__file__ or "")
    text = source_path.read_text(encoding="utf-8")
    assert "quant.research" not in text
    assert "tushare.local" not in text
    assert "get_token" not in text
    assert "configs/tushare" not in text
    after = {name for name in sys.modules if name.startswith(banned_prefixes)}
    assert after == before
    assert not hasattr(mod, "get_token")


def test_empty_daily_rejected() -> None:
    schema = {
        "ts_code": pl.Utf8,
        "trade_date": pl.Utf8,
        "open": pl.Float64,
        "high": pl.Float64,
        "low": pl.Float64,
        "close": pl.Float64,
        "pre_close": pl.Float64,
        "change": pl.Float64,
        "pct_chg": pl.Float64,
        "vol": pl.Float64,
        "amount": pl.Float64,
    }
    empty = pl.DataFrame(schema=schema).select(TUSHARE_FIELDS["daily"].split(","))
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_EMPTY"):
        map_g1_daily_response(response=_make_verified("daily", empty))


def test_mapping_error_code_equals_str() -> None:
    err = M3G1MappingError("G1_MAPPER_EMPTY")
    assert err.code == str(err) == "G1_MAPPER_EMPTY"


def _drift_frame_close(frame: pl.DataFrame, *, trade_date: str, close: float) -> pl.DataFrame:
    """Keep shape/scope/legal OHLC; change only content digest."""
    return frame.with_columns(
        pl.when(pl.col("trade_date") == trade_date)
        .then(pl.lit(close))
        .otherwise(pl.col("close"))
        .alias("close")
    )


def test_p1b_daily_frame_content_drift_rejected() -> None:
    response = _make_verified("daily", _daily_frame())
    changed = _drift_frame_close(response.frame, trade_date="20260105", close=10.6)
    assert tuple(changed.columns) == tuple(response.frame.columns)
    assert changed.height == response.frame.height
    object.__setattr__(response, "frame", changed)
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_RESPONSE_INVALID"):
        map_g1_daily_response(response=response)


def test_p1b_benchmark_frame_content_drift_rejected() -> None:
    response = _make_verified("index_daily", _bench_frame())
    changed = _drift_frame_close(response.frame, trade_date="20260105", close=100.6)
    object.__setattr__(response, "frame", changed)
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_RESPONSE_INVALID"):
        map_g1_benchmark_response(response=response)


def test_p1b_receipt_sha256_drift_rejected() -> None:
    response = _make_verified("daily", _daily_frame())
    object.__setattr__(response, "receipt_sha256", "b" * 64)
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_RESPONSE_INVALID"):
        map_g1_daily_response(response=response)


def test_p1b_receipt_content_identity_drift_rejected() -> None:
    """表面 endpoint/columns 仍匹配，但 receipt content identity 已漂移。"""
    response = _make_verified("daily", _daily_frame())
    object.__setattr__(response.receipt, "response_content_sha256", "c" * 64)
    assert response.receipt.endpoint == "daily"
    assert tuple(response.receipt.columns) == tuple(TUSHARE_FIELDS["daily"].split(","))
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_RESPONSE_INVALID"):
        map_g1_daily_response(response=response)


def test_p1b_spec_parameters_identity_drift_rejected() -> None:
    response = _make_verified("daily", _daily_frame())
    drifted = tuple(
        (key, "20260104" if key == "start_date" else value)
        for key, value in response.spec.parameters
    )
    object.__setattr__(response.spec, "parameters", drifted)
    assert response.spec.endpoint == "daily"
    assert tuple(response.frame.columns) == tuple(TUSHARE_FIELDS["daily"].split(","))
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_RESPONSE_INVALID"):
        map_g1_daily_response(response=response)


def test_p1b_reverify_exception_surfaces_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import traceback

    response = _make_verified("daily", _daily_frame())

    def boom(self: VerifiedRawResponse) -> None:
        raise ValueError("/abs/path/secret token=abcd1234 row={'ts_code': 'X'}")

    monkeypatch.setattr(VerifiedRawResponse, "__post_init__", boom)
    with pytest.raises(M3G1MappingError) as excinfo:
        map_g1_daily_response(response=response)
    err = excinfo.value
    assert err.code == "G1_MAPPER_RESPONSE_INVALID"
    assert err.__cause__ is None
    surfaces = [
        str(err),
        repr(err),
        err.code,
        "".join(traceback.format_exception(type(err), err, err.__traceback__)),
    ]
    for surface in surfaces:
        assert "/abs/path" not in surface
        assert "token=" not in surface
        assert "ts_code" not in surface
        assert "abcd1234" not in surface


def test_p1b_legal_verified_still_maps() -> None:
    """合法对象只经一次生产闭包重验后正常映射。"""
    out = map_g1_daily_response(response=_make_verified("daily", _daily_frame()))
    assert out.height == 2
    assert out.get_column("close").to_list() == [10.5, 11.5]
