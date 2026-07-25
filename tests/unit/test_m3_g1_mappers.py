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
from quant.domain import Suspension1dSchema

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
    elif endpoint in {"dividend", "fund_div"}:
        params.setdefault("ts_code", _SYMBOL if endpoint == "dividend" else "510300.SH")
    else:
        params.setdefault("start_date", _START)
        params.setdefault("end_date", _END)
        if endpoint in {"daily", "adj_factor", "stk_limit"}:
            params.setdefault("ts_code", _SYMBOL)
        elif endpoint == "index_daily":
            params.setdefault("ts_code", _BENCHMARK)
        elif endpoint == "index_weight":
            params.setdefault("index_code", "000300.SH")
        elif endpoint in {"fund_daily", "fund_adj"}:
            params.setdefault("ts_code", "510300.SH")
    # Drop accidental dates on fund_div even if caller merged defaults.
    if endpoint == "fund_div":
        params.pop("start_date", None)
        params.pop("end_date", None)
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

# --- B1B ETF total-return mapper adversarial tests (appended) ---

_ETF = "510300.SH"
_ETF_START = dt.date(2026, 1, 15)
_ETF_END = dt.date(2026, 1, 21)


def _etf_verified(
    endpoint: str,
    frame: pl.DataFrame,
    *,
    parameters: dict[str, str] | None = None,
) -> VerifiedRawResponse:
    return _make_verified(endpoint, frame, parameters=parameters)


def _etf_daily_rows() -> list[dict[str, Any]]:
    return [
        {
            "ts_code": _ETF,
            "trade_date": "20260115",
            "open": 4.87,
            "high": 4.88,
            "low": 4.86,
            "close": 4.875,
            "pre_close": 4.866,
            "change": 0.009,
            "pct_chg": 0.18,
            "vol": 1.0,
            "amount": 1.0,
        },
        {
            "ts_code": _ETF,
            "trade_date": "20260116",
            "open": 4.87,
            "high": 4.88,
            "low": 4.85,
            "close": 4.859,
            "pre_close": 4.875,
            "change": -0.016,
            "pct_chg": -0.33,
            "vol": 1.0,
            "amount": 1.0,
        },
        {
            "ts_code": _ETF,
            "trade_date": "20260119",
            "open": 4.74,
            "high": 4.75,
            "low": 4.73,
            "close": 4.738,
            "pre_close": 4.736,
            "change": 0.002,
            "pct_chg": 0.04,
            "vol": 1.0,
            "amount": 1.0,
        },
        {
            "ts_code": _ETF,
            "trade_date": "20260120",
            "open": 4.73,
            "high": 4.74,
            "low": 4.72,
            "close": 4.724,
            "pre_close": 4.738,
            "change": -0.014,
            "pct_chg": -0.3,
            "vol": 1.0,
            "amount": 1.0,
        },
        {
            "ts_code": _ETF,
            "trade_date": "20260121",
            "open": 4.72,
            "high": 4.74,
            "low": 4.72,
            "close": 4.730,
            "pre_close": 4.724,
            "change": 0.006,
            "pct_chg": 0.13,
            "vol": 1.0,
            "amount": 1.0,
        },
    ]


def _etf_adj_rows() -> list[dict[str, Any]]:
    return [
        {"ts_code": _ETF, "trade_date": "20260115", "adj_factor": 1.2350},
        {"ts_code": _ETF, "trade_date": "20260116", "adj_factor": 1.2350},
        {"ts_code": _ETF, "trade_date": "20260119", "adj_factor": 1.2671},
        {"ts_code": _ETF, "trade_date": "20260120", "adj_factor": 1.2671},
        {"ts_code": _ETF, "trade_date": "20260121", "adj_factor": 1.2671},
    ]


def _etf_div_rows(*, mode: str = "single") -> list[dict[str, Any]]:
    base = {
        "ts_code": _ETF,
        "ann_date": "20260110",
        "imp_anndate": "20260110",
        "base_date": "20260116",
        "div_proc": "实施",
        "record_date": "20260116",
        "ex_date": "20260119",
        "pay_date": "20260120",
        "earpay_date": None,
        "net_ex_date": "20260119",
        "div_cash": 0.123,
        "base_unit": 1.0,
        "ear_distr": None,
        "ear_amount": None,
        "account_date": None,
        "base_year": "2025",
    }
    rows = [dict(base)]
    if mode == "exact":
        rows.append(dict(base))
    elif mode == "net_ex_only":
        alt = dict(base)
        alt["net_ex_date"] = "20260120"
        alt["base_unit"] = 10.0
        rows.append(alt)
    elif mode == "cash_conflict":
        alt = dict(base)
        alt["div_cash"] = 0.2
        rows.append(alt)
    elif mode == "ex_date_conflict":
        alt = dict(base)
        alt["ex_date"] = "20260120"
        rows.append(alt)
    return rows


def _etf_frame(endpoint: str, rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(rows).select(TUSHARE_FIELDS[endpoint].split(","))


def _etf_happy(
    *,
    daily_rows: list[dict[str, Any]] | None = None,
    adj_rows: list[dict[str, Any]] | None = None,
    div_mode: str = "single",
):
    from quant.data.m3_backfill import plan_fund_adj_requests

    daily = _etf_verified(
        "fund_daily",
        _etf_frame("fund_daily", daily_rows or _etf_daily_rows()),
        parameters={
            "ts_code": _ETF,
            "start_date": _ETF_START.strftime("%Y%m%d"),
            "end_date": _ETF_END.strftime("%Y%m%d"),
        },
    )
    specs = plan_fund_adj_requests(symbol=_ETF, start=_ETF_START, end=_ETF_END)
    adj = (
        _etf_verified(
            "fund_adj",
            _etf_frame("fund_adj", adj_rows or _etf_adj_rows()),
            parameters=dict(specs[0].parameters),
        ),
    )
    div = _etf_verified(
        "fund_div",
        _etf_frame("fund_div", _etf_div_rows(mode=div_mode)),
        parameters={"ts_code": _ETF},
    )
    return daily, adj, div


def test_b1b_map_510300_hfq_happy_path() -> None:
    daily, adj, div = _etf_happy()
    out = map_g1_benchmark_response(
        fund_daily=daily, fund_adj_segments=adj, fund_div=div
    )
    assert out.height == 5
    assert set(out.get_column("benchmark").to_list()) == {_ETF}
    row = out.filter(pl.col("trade_date") == dt.date(2026, 1, 19)).to_dicts()[0]
    assert row["close"] == pytest.approx(4.738 * 1.2671)
    assert len(set(out.get_column("source_snapshot_id").to_list())) == 1


@pytest.mark.parametrize(
    "kind",
    ["drop_adj", "dup_adj", "wrong_code", "bad_segment", "zero_factor", "date_mismatch"],
)
def test_b1b_benchmark_closure_fail_closed(kind: str) -> None:
    daily, adj, div = _etf_happy()
    if kind == "drop_adj":
        with pytest.raises(M3G1MappingError):
            map_g1_benchmark_response(
                fund_daily=daily, fund_adj_segments=(), fund_div=div
            )
    elif kind == "dup_adj":
        with pytest.raises(M3G1MappingError):
            map_g1_benchmark_response(
                fund_daily=daily, fund_adj_segments=(adj[0], adj[0]), fund_div=div
            )
    elif kind == "wrong_code":
        bad = _etf_verified(
            "fund_daily",
            _etf_frame(
                "fund_daily",
                [{**r, "ts_code": "159919.SZ"} for r in _etf_daily_rows()],
            ),
            parameters={
                "ts_code": "159919.SZ",
                "start_date": _ETF_START.strftime("%Y%m%d"),
                "end_date": _ETF_END.strftime("%Y%m%d"),
            },
        )
        with pytest.raises(M3G1MappingError):
            map_g1_benchmark_response(
                fund_daily=bad, fund_adj_segments=adj, fund_div=div
            )
    elif kind == "bad_segment":
        bad_adj = _etf_verified(
            "fund_adj",
            _etf_frame("fund_adj", _etf_adj_rows()),
            parameters={
                "ts_code": _ETF,
                "start_date": _ETF_START.strftime("%Y%m%d"),
                "end_date": "20260120",
            },
        )
        with pytest.raises(M3G1MappingError):
            map_g1_benchmark_response(
                fund_daily=daily, fund_adj_segments=(bad_adj,), fund_div=div
            )
    elif kind == "zero_factor":
        rows = _etf_adj_rows()
        rows[0]["adj_factor"] = 0.0
        daily, adj, div = _etf_happy(adj_rows=rows)
        with pytest.raises(M3G1MappingError):
            map_g1_benchmark_response(
                fund_daily=daily, fund_adj_segments=adj, fund_div=div
            )
    else:
        daily, adj, div = _etf_happy(adj_rows=_etf_adj_rows()[:-1])
        with pytest.raises(M3G1MappingError):
            map_g1_benchmark_response(
                fund_daily=daily, fund_adj_segments=adj, fund_div=div
            )


def test_b1b_fund_div_duplicate_classes() -> None:
    daily, adj, _ = _etf_happy()
    for mode in ("exact", "net_ex_only"):
        div = _etf_verified(
            "fund_div",
            _etf_frame("fund_div", _etf_div_rows(mode=mode)),
            parameters={"ts_code": _ETF},
        )
        out = map_g1_benchmark_response(
            fund_daily=daily, fund_adj_segments=adj, fund_div=div
        )
        assert out.height == 5
    for mode in ("cash_conflict", "ex_date_conflict"):
        conflict = _etf_verified(
            "fund_div",
            _etf_frame("fund_div", _etf_div_rows(mode=mode)),
            parameters={"ts_code": _ETF},
        )
        with pytest.raises(
            M3G1MappingError, match="G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED"
        ):
            map_g1_benchmark_response(
                fund_daily=daily, fund_adj_segments=adj, fund_div=conflict
            )


def test_b1b_r2_positive_and_jump_failures() -> None:
    daily, adj, div = _etf_happy()
    out = map_g1_benchmark_response(
        fund_daily=daily, fund_adj_segments=adj, fund_div=div
    )
    assert out.height == 5
    no_jump = _etf_adj_rows()
    no_jump[2]["adj_factor"] = 1.2350
    daily, adj, div = _etf_happy(adj_rows=no_jump)
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED"):
        map_g1_benchmark_response(
            fund_daily=daily, fund_adj_segments=adj, fund_div=div
        )
    unexplained = _etf_adj_rows()
    unexplained[4]["adj_factor"] = 1.3
    daily, adj, div = _etf_happy(adj_rows=unexplained)
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED"):
        map_g1_benchmark_response(
            fund_daily=daily, fund_adj_segments=adj, fund_div=div
        )


def test_b1b_wrong_ex_pre_over_ex_pre_minus_cash_formula_rejected() -> None:
    """Reject factor jump tuned to ex_pre/(ex_pre-div_cash) instead of prev_close/ex_pre."""
    # Synthetic cash large enough that the two formulas diverge beyond rtol=0.001.
    prev_close = 10.0
    div_cash = 2.0
    ex_pre = 8.0
    wrong_ratio = ex_pre / (ex_pre - div_cash)
    correct_ratio = prev_close / ex_pre
    assert abs(wrong_ratio - correct_ratio) / correct_ratio > 0.001
    daily_rows = [
        {
            "ts_code": _ETF,
            "trade_date": "20260115",
            "open": 10.0,
            "high": 10.1,
            "low": 9.9,
            "close": 10.0,
            "pre_close": 9.9,
            "change": 0.1,
            "pct_chg": 1.0,
            "vol": 1.0,
            "amount": 1.0,
        },
        {
            "ts_code": _ETF,
            "trade_date": "20260116",
            "open": 10.0,
            "high": 10.1,
            "low": 9.9,
            "close": prev_close,
            "pre_close": 10.0,
            "change": 0.0,
            "pct_chg": 0.0,
            "vol": 1.0,
            "amount": 1.0,
        },
        {
            "ts_code": _ETF,
            "trade_date": "20260119",
            "open": 8.0,
            "high": 8.1,
            "low": 7.9,
            "close": 8.0,
            "pre_close": ex_pre,
            "change": 0.0,
            "pct_chg": 0.0,
            "vol": 1.0,
            "amount": 1.0,
        },
        {
            "ts_code": _ETF,
            "trade_date": "20260120",
            "open": 8.0,
            "high": 8.1,
            "low": 7.9,
            "close": 8.0,
            "pre_close": 8.0,
            "change": 0.0,
            "pct_chg": 0.0,
            "vol": 1.0,
            "amount": 1.0,
        },
        {
            "ts_code": _ETF,
            "trade_date": "20260121",
            "open": 8.0,
            "high": 8.1,
            "low": 7.9,
            "close": 8.0,
            "pre_close": 8.0,
            "change": 0.0,
            "pct_chg": 0.0,
            "vol": 1.0,
            "amount": 1.0,
        },
    ]
    adj_rows = [
        {"ts_code": _ETF, "trade_date": "20260115", "adj_factor": 1.0},
        {"ts_code": _ETF, "trade_date": "20260116", "adj_factor": 1.0},
        {"ts_code": _ETF, "trade_date": "20260119", "adj_factor": wrong_ratio},
        {"ts_code": _ETF, "trade_date": "20260120", "adj_factor": wrong_ratio},
        {"ts_code": _ETF, "trade_date": "20260121", "adj_factor": wrong_ratio},
    ]
    div_rows = _etf_div_rows()
    div_rows[0]["div_cash"] = div_cash
    daily, adj, div = _etf_happy(
        daily_rows=daily_rows, adj_rows=adj_rows, div_mode="single"
    )
    # Replace div with custom cash.
    div = _etf_verified(
        "fund_div",
        _etf_frame("fund_div", div_rows),
        parameters={"ts_code": _ETF},
    )
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_DIVIDEND_RECONCILIATION_FAILED"):
        map_g1_benchmark_response(
            fund_daily=daily, fund_adj_segments=adj, fund_div=div
        )
    # Control: correct formula ratio must pass.
    adj_ok = [
        {"ts_code": _ETF, "trade_date": "20260115", "adj_factor": 1.0},
        {"ts_code": _ETF, "trade_date": "20260116", "adj_factor": 1.0},
        {"ts_code": _ETF, "trade_date": "20260119", "adj_factor": correct_ratio},
        {"ts_code": _ETF, "trade_date": "20260120", "adj_factor": correct_ratio},
        {"ts_code": _ETF, "trade_date": "20260121", "adj_factor": correct_ratio},
    ]
    daily2, adj2, _ = _etf_happy(daily_rows=daily_rows, adj_rows=adj_ok)
    out = map_g1_benchmark_response(
        fund_daily=daily2, fund_adj_segments=adj2, fund_div=div
    )
    assert out.height == 5


def test_b1b_source_snapshot_changes_with_any_response_identity() -> None:
    daily, adj, div = _etf_happy()
    base = map_g1_benchmark_response(
        fund_daily=daily, fund_adj_segments=adj, fund_div=div
    )
    snap0 = base.item(0, "source_snapshot_id")
    # Mutate fund_div frame content → new stable_response_sha256 → new snapshot.
    alt_rows = _etf_div_rows()
    alt_rows[0]["ann_date"] = "20260111"
    alt_div = _etf_verified(
        "fund_div",
        _etf_frame("fund_div", alt_rows),
        parameters={"ts_code": _ETF},
    )
    alt = map_g1_benchmark_response(
        fund_daily=daily, fund_adj_segments=adj, fund_div=alt_div
    )
    assert alt.item(0, "source_snapshot_id") != snap0
    assert div.receipt.stable_response_sha256 != alt_div.receipt.stable_response_sha256


# --- B1B-R3 mapper evidence closures ---

_ETF_LONG_START = dt.date(2015, 10, 8)
_ETF_LONG_END = dt.date(2026, 7, 10)


def _long_session_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sparse sessions spanning three fund_adj segments with one in-window cash event."""
    # Segments: 2015-10-08..2018-12-31 | 2019-01-01..2022-12-31 | 2023-01-01..2026-07-10
    # Factor platform is flat until ex_date; only 2026-01-19 jumps (B0 freeze numbers).
    sessions = [
        (dt.date(2015, 10, 8), 4.50, 1.2350),
        (dt.date(2016, 6, 1), 4.60, 1.2350),
        (dt.date(2019, 1, 2), 4.70, 1.2350),
        (dt.date(2020, 6, 1), 4.80, 1.2350),
        (dt.date(2023, 1, 3), 4.90, 1.2350),
        (dt.date(2026, 1, 16), 4.859, 1.2350),
        (dt.date(2026, 1, 19), 4.738, 1.2671),
        (dt.date(2026, 1, 20), 4.724, 1.2671),
    ]
    daily_rows: list[dict[str, Any]] = []
    adj_rows: list[dict[str, Any]] = []
    for day, close, factor in sessions:
        text = day.strftime("%Y%m%d")
        daily_rows.append(
            {
                "ts_code": _ETF,
                "trade_date": text,
                "open": close,
                "high": close + 0.01,
                "low": close - 0.01,
                "close": close,
                "pre_close": close,
                "change": 0.0,
                "pct_chg": 0.0,
                "vol": 1.0,
                "amount": 1.0,
            }
        )
        adj_rows.append(
            {"ts_code": _ETF, "trade_date": text, "adj_factor": factor}
        )
    # Freeze OHLC/pre_close around the cash event.
    daily_rows[5].update(
        {
            "open": 4.87,
            "high": 4.88,
            "low": 4.85,
            "close": 4.859,
            "pre_close": 4.875,
        }
    )
    daily_rows[6].update(
        {
            "open": 4.74,
            "high": 4.75,
            "low": 4.73,
            "close": 4.738,
            "pre_close": 4.736,
        }
    )
    return daily_rows, adj_rows


def _etf_long_happy():
    from quant.data.m3_backfill import plan_fund_adj_requests

    daily_rows, adj_rows = _long_session_rows()
    daily = _etf_verified(
        "fund_daily",
        _etf_frame("fund_daily", daily_rows),
        parameters={
            "ts_code": _ETF,
            "start_date": _ETF_LONG_START.strftime("%Y%m%d"),
            "end_date": _ETF_LONG_END.strftime("%Y%m%d"),
        },
    )
    specs = plan_fund_adj_requests(
        symbol=_ETF, start=_ETF_LONG_START, end=_ETF_LONG_END
    )
    assert len(specs) == 3
    by_seg: list[list[dict[str, Any]]] = [[], [], []]
    for row in adj_rows:
        day = dt.datetime.strptime(row["trade_date"], "%Y%m%d").date()
        for idx, spec in enumerate(specs):
            start = dt.datetime.strptime(
                dict(spec.parameters)["start_date"], "%Y%m%d"
            ).date()
            end = dt.datetime.strptime(
                dict(spec.parameters)["end_date"], "%Y%m%d"
            ).date()
            if start <= day <= end:
                by_seg[idx].append(row)
                break
        else:
            raise AssertionError(f"date not covered: {row['trade_date']}")
    adj = tuple(
        _etf_verified(
            "fund_adj",
            _etf_frame("fund_adj", rows),
            parameters=dict(spec.parameters),
        )
        for spec, rows in zip(specs, by_seg, strict=True)
    )
    div = _etf_verified(
        "fund_div",
        _etf_frame("fund_div", _etf_div_rows()),
        parameters={"ts_code": _ETF},
    )
    return daily, adj, div, specs


def test_b1b_r3_three_segment_closure_missing_dup_overlap_and_shuffle() -> None:
    daily, adj, div, specs = _etf_long_happy()
    assert len(adj) == 3
    # Missing middle segment.
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_BENCHMARK_CLOSURE_INVALID"):
        map_g1_benchmark_response(
            fund_daily=daily, fund_adj_segments=(adj[0], adj[2]), fund_div=div
        )
    # Duplicate request_id.
    with pytest.raises(M3G1MappingError, match="G1_MAPPER_BENCHMARK_CLOSURE_INVALID"):
        map_g1_benchmark_response(
            fund_daily=daily,
            fund_adj_segments=(adj[0], adj[1], adj[1]),
            fund_div=div,
        )
    # Overlapping middle params (reuse seg0 frame with seg1 identity).
    overlap = _etf_verified(
        "fund_adj",
        adj[1].frame,
        parameters=dict(specs[0].parameters),
    )
    with pytest.raises(M3G1MappingError):
        map_g1_benchmark_response(
            fund_daily=daily,
            fund_adj_segments=(adj[0], overlap, adj[2]),
            fund_div=div,
        )
    # Shuffle input order: OHLC + snapshot stable.
    base = map_g1_benchmark_response(
        fund_daily=daily, fund_adj_segments=adj, fund_div=div
    )
    shuffled = map_g1_benchmark_response(
        fund_daily=daily,
        fund_adj_segments=(adj[2], adj[0], adj[1]),
        fund_div=div,
    )
    assert shuffled.get_column("source_snapshot_id").to_list() == base.get_column(
        "source_snapshot_id"
    ).to_list()
    for col in ("open", "high", "low", "close", "trade_date"):
        assert shuffled.get_column(col).to_list() == base.get_column(col).to_list()


def test_b1b_r3_snapshot_sensitive_to_daily_adj_and_div_identities() -> None:
    daily, adj, div = _etf_happy()
    base = map_g1_benchmark_response(
        fund_daily=daily, fund_adj_segments=adj, fund_div=div
    )
    snap0 = base.item(0, "source_snapshot_id")

    daily_rows = _etf_daily_rows()
    daily_rows[0]["amount"] = 9.9
    alt_daily = _etf_verified(
        "fund_daily",
        _etf_frame("fund_daily", daily_rows),
        parameters={
            "ts_code": _ETF,
            "start_date": _ETF_START.strftime("%Y%m%d"),
            "end_date": _ETF_END.strftime("%Y%m%d"),
        },
    )
    out_daily = map_g1_benchmark_response(
        fund_daily=alt_daily, fund_adj_segments=adj, fund_div=div
    )
    assert out_daily.item(0, "source_snapshot_id") != snap0
    assert alt_daily.receipt.stable_response_sha256 != daily.receipt.stable_response_sha256

    alt_adj_frame = adj[0].frame.with_columns(pl.col("adj_factor").cast(pl.Float32))
    alt_adj = _etf_verified(
        "fund_adj",
        alt_adj_frame,
        parameters=dict(adj[0].spec.parameters),
    )
    out_adj = map_g1_benchmark_response(
        fund_daily=daily, fund_adj_segments=(alt_adj,), fund_div=div
    )
    assert out_adj.item(0, "source_snapshot_id") != snap0
    assert alt_adj.receipt.stable_response_sha256 != adj[0].receipt.stable_response_sha256

    alt_div_rows = _etf_div_rows()
    alt_div_rows[0]["ann_date"] = "20260112"
    alt_div = _etf_verified(
        "fund_div",
        _etf_frame("fund_div", alt_div_rows),
        parameters={"ts_code": _ETF},
    )
    out_div = map_g1_benchmark_response(
        fund_daily=daily, fund_adj_segments=adj, fund_div=alt_div
    )
    assert out_div.item(0, "source_snapshot_id") != snap0


def test_b1b_r3_ohlc_all_columns_equal_raw_times_factor() -> None:
    daily, adj, div = _etf_happy()
    out = map_g1_benchmark_response(
        fund_daily=daily, fund_adj_segments=adj, fund_div=div
    )
    factors = {r["trade_date"]: r["adj_factor"] for r in _etf_adj_rows()}
    raw_by_day = {r["trade_date"]: r for r in _etf_daily_rows()}
    for row in out.iter_rows(named=True):
        text = row["trade_date"].strftime("%Y%m%d")
        raw = raw_by_day[text]
        factor = factors[text]
        assert row["open"] == pytest.approx(raw["open"] * factor)
        assert row["high"] == pytest.approx(raw["high"] * factor)
        assert row["low"] == pytest.approx(raw["low"] * factor)
        assert row["close"] == pytest.approx(raw["close"] * factor)


def test_b1b_r3_window_first_day_ex_date_ok() -> None:
    """Window starts on ex_date: prior jump undecidable; must not guess-fail."""
    from quant.data.m3_backfill import plan_fund_adj_requests

    start = dt.date(2026, 1, 19)
    end = dt.date(2026, 1, 21)
    daily_rows = [
        {
            "ts_code": _ETF,
            "trade_date": "20260119",
            "open": 4.74,
            "high": 4.75,
            "low": 4.73,
            "close": 4.738,
            "pre_close": 4.736,
            "change": 0.002,
            "pct_chg": 0.04,
            "vol": 1.0,
            "amount": 1.0,
        },
        {
            "ts_code": _ETF,
            "trade_date": "20260120",
            "open": 4.73,
            "high": 4.74,
            "low": 4.72,
            "close": 4.724,
            "pre_close": 4.738,
            "change": -0.014,
            "pct_chg": -0.3,
            "vol": 1.0,
            "amount": 1.0,
        },
        {
            "ts_code": _ETF,
            "trade_date": "20260121",
            "open": 4.72,
            "high": 4.74,
            "low": 4.72,
            "close": 4.730,
            "pre_close": 4.724,
            "change": 0.006,
            "pct_chg": 0.13,
            "vol": 1.0,
            "amount": 1.0,
        },
    ]
    adj_rows = [
        {"ts_code": _ETF, "trade_date": "20260119", "adj_factor": 1.2671},
        {"ts_code": _ETF, "trade_date": "20260120", "adj_factor": 1.2671},
        {"ts_code": _ETF, "trade_date": "20260121", "adj_factor": 1.2671},
    ]
    daily = _etf_verified(
        "fund_daily",
        _etf_frame("fund_daily", daily_rows),
        parameters={
            "ts_code": _ETF,
            "start_date": start.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
        },
    )
    specs = plan_fund_adj_requests(symbol=_ETF, start=start, end=end)
    adj = tuple(
        _etf_verified(
            "fund_adj",
            _etf_frame("fund_adj", adj_rows),
            parameters=dict(spec.parameters),
        )
        for spec in specs
    )
    div = _etf_verified(
        "fund_div",
        _etf_frame("fund_div", _etf_div_rows()),
        parameters={"ts_code": _ETF},
    )
    out = map_g1_benchmark_response(
        fund_daily=daily, fund_adj_segments=adj, fund_div=div
    )
    assert out.height == 3
    assert out.item(0, "trade_date") == start
