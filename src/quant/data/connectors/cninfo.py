"""CNINFO official API thin adapter for A-share rights issues (p_stock2232).

AKShare is used only for Accept-Enckey generation. Production raw keeps official
field codes; Chinese display names are not part of the contract. Tests must
inject a fake HTTP client and/or enckey provider so the default path never
touches the network.
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import polars as pl

CNINFO_SOURCE = "cninfo"
CNINFO_ENDPOINT = "stock_allotment"
CNINFO_ADAPTER = "akshare_cninfo_p_stock2232_v1"
CNINFO_API_PATH = "/api/stock/p_stock2232"
CNINFO_API_HOST = "webapi.cninfo.com.cn"
CNINFO_API_URL = f"https://{CNINFO_API_HOST}{CNINFO_API_PATH}"

# Frozen official field set from p_stock2232 (57 columns). Exact set match required.
CNINFO_STOCK_ALLOTMENT_FIELDS: tuple[str, ...] = (
    "DECLAREDATE",
    "F001V",
    "F002V",
    "F004N",
    "F005N",
    "F006N",
    "F007N",
    "F008N",
    "F009V",
    "F010V",
    "F011D",
    "F012D",
    "F013D",
    "F014D",
    "F017N",
    "F018N",
    "F019N",
    "F020N",
    "F021N",
    "F022N",
    "F023D",
    "F024N",
    "F025N",
    "F026N",
    "F027N",
    "F028V",
    "F029N",
    "F030N",
    "F031N",
    "F032N",
    "F033V",
    "F034V",
    "F035V",
    "F036V",
    "F037D",
    "F038D",
    "F039D",
    "F040D",
    "F041N",
    "F042N",
    "F043N",
    "F044N",
    "F045N",
    "F046N",
    "F047N",
    "F048D",
    "F049D",
    "F050V",
    "F051V",
    "F052D",
    "F053D",
    "F054V",
    "F055N",
    "ORGNAME",
    "SECCODE",
    "SECNAME",
    "SUBID",
)
CNINFO_STOCK_ALLOTMENT_FIELD_SET = frozenset(CNINFO_STOCK_ALLOTMENT_FIELDS)

_DEFAULT_ROW_LIMIT = 5000


class CninfoConnectorError(RuntimeError):
    """Stable, sanitized CNINFO connector failure."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code:
            raise ValueError("CNINFO error code 非法")
        self.code = code
        super().__init__(code)


class CninfoHttpClient(Protocol):
    """Minimal POST client returning a parsed JSON mapping."""

    def post_json(
        self,
        *,
        url: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> Mapping[str, Any]:
        """POST and return the JSON object body."""


@dataclass(frozen=True)
class CninfoAllotmentRawResult:
    """Validated raw allotment response with official field codes."""

    frame: pl.DataFrame
    resultcode: int
    resultmsg: str
    count: int
    total: int

    def __post_init__(self) -> None:
        if not isinstance(self.frame, pl.DataFrame):
            raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
        if self.resultcode != 200:
            raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
        if self.resultmsg != "success":
            raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
        if type(self.count) is not int or type(self.total) is not int:
            raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
        if self.count < 0 or self.total < 0:
            raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
        if self.count != self.total or self.count != self.frame.height:
            raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
        if tuple(self.frame.columns) != CNINFO_STOCK_ALLOTMENT_FIELDS:
            raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")


class _RequestsCninfoClient:
    """Production HTTP client; never logs headers or Enckey."""

    def post_json(
        self,
        *,
        url: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
    ) -> Mapping[str, Any]:
        try:
            requests = importlib.import_module("requests")
        except ModuleNotFoundError as exc:
            raise CninfoConnectorError("CNINFO_DEPENDENCY_MISSING") from exc
        try:
            response = requests.post(url, params=dict(params), headers=dict(headers), timeout=60)
            response.raise_for_status()
            payload = response.json()
        except CninfoConnectorError:
            raise
        except Exception as exc:
            raise _sanitize_network(exc) from None
        if not isinstance(payload, dict):
            raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
        return payload


class CninfoConnector:
    """CNINFO p_stock2232 adapter with injectable client/enckey for tests."""

    source = CNINFO_SOURCE

    def __init__(
        self,
        *,
        client: CninfoHttpClient | None = None,
        enckey_provider: Callable[[], str] | None = None,
        row_limit: int = _DEFAULT_ROW_LIMIT,
    ) -> None:
        if type(row_limit) is not int or row_limit <= 0:
            raise ValueError("row_limit 必须是正整数")
        self._client = client
        self._enckey_provider = enckey_provider
        self._row_limit = row_limit

    def fetch_stock_allotment_raw(
        self,
        *,
        symbols: str,
        start_date: str,
        end_date: str,
    ) -> CninfoAllotmentRawResult:
        """Fetch and validate one stock_allotment request; returns official codes."""
        codes = _normalize_symbol_codes(symbols)
        _validate_date8(start_date)
        _validate_date8(end_date)
        if start_date > end_date:
            raise CninfoConnectorError("CNINFO_REQUEST_PARAMS_INVALID")
        params = {
            "scode": ",".join(codes),
            "sdate": _date8_to_iso(start_date),
            "edate": _date8_to_iso(end_date),
        }
        headers = {
            "Accept": "*/*",
            "Accept-Enckey": self._enckey(),
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cache-Control": "no-cache",
            "Content-Length": "0",
            "Host": CNINFO_API_HOST,
            "Origin": f"https://{CNINFO_API_HOST}",
            "Pragma": "no-cache",
            "Proxy-Connection": "keep-alive",
            "Referer": f"https://{CNINFO_API_HOST}/",
            "X-Requested-With": "XMLHttpRequest",
        }
        client = self._client if self._client is not None else _RequestsCninfoClient()
        try:
            payload = client.post_json(url=CNINFO_API_URL, params=params, headers=headers)
        except CninfoConnectorError:
            raise
        except Exception as exc:
            raise _sanitize_network(exc) from None
        return _validate_allotment_payload(
            payload, requested_codes=set(codes), row_limit=self._row_limit
        )

    def _enckey(self) -> str:
        if self._enckey_provider is not None:
            try:
                token = self._enckey_provider()
            except CninfoConnectorError:
                raise
            except Exception as exc:
                raise _sanitize_network(exc) from None
            if type(token) is not str or not token:
                raise CninfoConnectorError("CNINFO_ENCKEY_INVALID")
            return token
        return _enckey_default()


def normalize_cninfo_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    """Strip .SH/.SZ, sort uniquely; used by request planning."""
    if not isinstance(symbols, Sequence) or not symbols:
        raise ValueError("symbols 不能为空")
    codes: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        if type(symbol) is not str:
            raise ValueError("symbol 必须是字符串")
        code = symbol[:-3] if symbol.endswith((".SH", ".SZ")) else symbol
        if len(code) != 6 or not code.isdigit():
            raise ValueError("symbol 非法")
        if code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return tuple(sorted(codes))


def batch_cninfo_symbol_groups(
    symbols: Sequence[str], *, batch_size: int = 50
) -> tuple[tuple[str, ...], ...]:
    """Deterministic 50-symbol batches; each code appears in exactly one batch."""
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("batch_size 必须是正整数")
    codes = normalize_cninfo_symbols(symbols)
    groups: list[tuple[str, ...]] = []
    for index in range(0, len(codes), batch_size):
        groups.append(codes[index : index + batch_size])
    return tuple(groups)


def empty_cninfo_allotment_frame() -> pl.DataFrame:
    """Complete empty schema with frozen official field order."""
    return pl.DataFrame(
        {name: [] for name in CNINFO_STOCK_ALLOTMENT_FIELDS},
        schema={name: pl.Utf8 for name in CNINFO_STOCK_ALLOTMENT_FIELDS},
    )


def _validate_allotment_payload(
    payload: Mapping[str, Any],
    *,
    requested_codes: set[str],
    row_limit: int,
) -> CninfoAllotmentRawResult:
    if not isinstance(payload, Mapping):
        raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
    try:
        resultcode = payload["resultcode"]
        resultmsg = payload["resultmsg"]
        count = payload["count"]
        total = payload["total"]
        records = payload["records"]
    except Exception:
        raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID") from None
    if type(resultcode) is not int or resultcode != 200:
        raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
    if type(resultmsg) is not str or resultmsg != "success":
        raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
    if type(count) is not int or type(total) is not int:
        raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
    if count < 0 or total < 0 or count != total:
        raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
    if records is None:
        raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
    if not isinstance(records, list):
        raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
    if len(records) != count:
        raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
    if count > row_limit:
        raise CninfoConnectorError("CNINFO_RESPONSE_ROW_LIMIT")

    if count == 0:
        frame = empty_cninfo_allotment_frame()
        return CninfoAllotmentRawResult(
            frame=frame, resultcode=200, resultmsg="success", count=0, total=0
        )

    rows: list[dict[str, Any]] = []
    seen_subids: set[str] = set()
    for item in records:
        if not isinstance(item, Mapping):
            raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
        keys = frozenset(item.keys())
        if keys != CNINFO_STOCK_ALLOTMENT_FIELD_SET:
            raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
        seccode = item.get("SECCODE")
        if type(seccode) is not str or seccode not in requested_codes:
            raise CninfoConnectorError("CNINFO_RESPONSE_SCOPE_INVALID")
        subid = item.get("SUBID")
        subid_token = _subid_token(subid)
        if subid_token in seen_subids:
            raise CninfoConnectorError("CNINFO_RESPONSE_DUPLICATE_SUBID")
        seen_subids.add(subid_token)
        row: dict[str, Any] = {}
        for name in CNINFO_STOCK_ALLOTMENT_FIELDS:
            row[name] = _canonicalize_cell(item[name])
        rows.append(row)

    frame = pl.DataFrame(rows, schema={name: pl.Utf8 for name in CNINFO_STOCK_ALLOTMENT_FIELDS})
    return CninfoAllotmentRawResult(
        frame=frame,
        resultcode=200,
        resultmsg="success",
        count=count,
        total=total,
    )


def _canonicalize_cell(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is bool:
        raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
    if type(value) is int:
        return str(value)
    if type(value) is float:
        if not math.isfinite(value):
            raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
        normalized = 0.0 if value == 0.0 else float(value)
        return format(normalized, ".17g")
    if type(value) is str:
        return value
    raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")


def _subid_token(value: object) -> str:
    if type(value) is int:
        return str(value)
    if type(value) is str and value:
        return value
    if type(value) is float and math.isfinite(value) and value == int(value):
        return str(int(value))
    raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")


def _normalize_symbol_codes(symbols: str) -> list[str]:
    if type(symbols) is not str or not symbols:
        raise CninfoConnectorError("CNINFO_REQUEST_PARAMS_INVALID")
    parts = symbols.split(",")
    if not parts or any(not part for part in parts):
        raise CninfoConnectorError("CNINFO_REQUEST_PARAMS_INVALID")
    codes = normalize_cninfo_symbols(parts)
    if ",".join(codes) != symbols:
        # Request parameters must already be normalized (sorted unique bare codes).
        raise CninfoConnectorError("CNINFO_REQUEST_PARAMS_INVALID")
    if not (1 <= len(codes) <= 50):
        raise CninfoConnectorError("CNINFO_REQUEST_PARAMS_INVALID")
    return list(codes)


def _validate_date8(value: str) -> None:
    if type(value) is not str or len(value) != 8 or not value.isdigit():
        raise CninfoConnectorError("CNINFO_REQUEST_PARAMS_INVALID")


def _date8_to_iso(value: str) -> str:
    return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"


def _enckey_default() -> str:
    try:
        py_mini_racer = importlib.import_module("py_mini_racer")
        akshare_datasets = importlib.import_module("akshare.datasets")
    except ModuleNotFoundError as exc:
        raise CninfoConnectorError("CNINFO_DEPENDENCY_MISSING") from exc
    try:
        get_ths_js = akshare_datasets.get_ths_js
        path = get_ths_js("cninfo.js")
        with open(path, encoding="utf-8") as handle:
            js_content = handle.read()
        ctx = py_mini_racer.MiniRacer()
        ctx.eval(js_content)
        token = ctx.call("getResCode1")
    except CninfoConnectorError:
        raise
    except Exception as exc:
        raise _sanitize_network(exc) from None
    if type(token) is not str or not token:
        raise CninfoConnectorError("CNINFO_ENCKEY_INVALID")
    return token


def _sanitize_network(exc: BaseException) -> CninfoConnectorError:
    _ = exc
    return CninfoConnectorError("CNINFO_NETWORK_FAILED")

