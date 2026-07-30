"""CNINFO official API thin adapter for A-share corporate actions.

Supports:
- stock_allotment (p_stock2232) — existing rights contract
- stock_dividend (p_sysapi1139) — share reform / dividend announcements
- stock_share_change (p_stock2215) — capital structure changes

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
from typing import Any, Literal, Protocol

import polars as pl

CNINFO_SOURCE = "cninfo"
CNINFO_ENDPOINT = "stock_allotment"
CNINFO_ADAPTER = "akshare_cninfo_p_stock2232_v1"
CNINFO_API_PATH = "/api/stock/p_stock2232"
CNINFO_API_HOST = "webapi.cninfo.com.cn"
CNINFO_API_URL = f"https://{CNINFO_API_HOST}{CNINFO_API_PATH}"

CNINFO_DIVIDEND_ENDPOINT: Literal["stock_dividend"] = "stock_dividend"
CNINFO_DIVIDEND_ADAPTER: Literal["akshare_cninfo_p_sysapi1139_v1"] = (
    "akshare_cninfo_p_sysapi1139_v1"
)
CNINFO_DIVIDEND_API_PATH = "/api/sysapi/p_sysapi1139"
CNINFO_DIVIDEND_API_URL = f"https://{CNINFO_API_HOST}{CNINFO_DIVIDEND_API_PATH}"

CNINFO_SHARE_CHANGE_ENDPOINT: Literal["stock_share_change"] = "stock_share_change"
CNINFO_SHARE_CHANGE_ADAPTER: Literal["akshare_cninfo_p_stock2215_v1"] = (
    "akshare_cninfo_p_stock2215_v1"
)
CNINFO_SHARE_CHANGE_API_PATH = "/api/stock/p_stock2215"
CNINFO_SHARE_CHANGE_API_URL = f"https://{CNINFO_API_HOST}{CNINFO_SHARE_CHANGE_API_PATH}"

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

# Frozen official field set from p_sysapi1139 (11 columns).
CNINFO_STOCK_DIVIDEND_FIELDS: tuple[str, ...] = (
    "F001V",
    "F006D",
    "F007V",
    "F010N",
    "F011N",
    "F012N",
    "F018D",
    "F020D",
    "F023D",
    "F025D",
    "F044V",
)
CNINFO_STOCK_DIVIDEND_FIELD_SET = frozenset(CNINFO_STOCK_DIVIDEND_FIELDS)

# Frozen official field set from p_stock2215 (47 columns).
CNINFO_STOCK_SHARE_CHANGE_FIELDS: tuple[str, ...] = (
    "DECLAREDATE",
    "F001V",
    "F002V",
    "F003N",
    "F004N",
    "F005N",
    "F006N",
    "F007N",
    "F008N",
    "F009N",
    "F010N",
    "F011N",
    "F012N",
    "F013N",
    "F014N",
    "F015N",
    "F016N",
    "F017N",
    "F018N",
    "F019N",
    "F020N",
    "F021N",
    "F022N",
    "F023N",
    "F024N",
    "F025N",
    "F026N",
    "F027C",
    "F028N",
    "F029N",
    "F030N",
    "F031N",
    "F032N",
    "F033N",
    "F034N",
    "F035N",
    "F036N",
    "F037N",
    "F038N",
    "F040N",
    "F049N",
    "F050N",
    "ORGNAME",
    "SECCODE",
    "SECNAME",
    "VARYDATE",
)
CNINFO_STOCK_SHARE_CHANGE_FIELD_SET = frozenset(CNINFO_STOCK_SHARE_CHANGE_FIELDS)

_DEFAULT_ROW_LIMIT = 5000
_PAYLOAD_KEYS = frozenset({"resultcode", "resultmsg", "count", "total", "records"})


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


@dataclass(frozen=True)
class CninfoCorporateActionRawResult:
    """Validated raw corporate-action response with official field codes."""

    endpoint: Literal["stock_dividend", "stock_share_change"]
    frame: pl.DataFrame
    resultcode: int
    resultmsg: str
    count: int
    total: int

    def __post_init__(self) -> None:
        fields = _fields_for_endpoint(self.endpoint)
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
        if tuple(self.frame.columns) != fields:
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
    """CNINFO adapter with injectable client/enckey for tests."""

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
        payload = self._post(url=CNINFO_API_URL, params=params)
        return _validate_allotment_payload(
            payload, requested_codes=set(codes), row_limit=self._row_limit
        )

    def fetch_stock_dividend_raw(self, *, symbol: str) -> CninfoCorporateActionRawResult:
        """Fetch and validate one stock_dividend request; returns official codes."""
        code = _normalize_single_symbol(symbol)
        payload = self._post(url=CNINFO_DIVIDEND_API_URL, params={"scode": code})
        return _validate_corporate_action_payload(
            payload,
            endpoint=CNINFO_DIVIDEND_ENDPOINT,
            requested_code=code,
            row_limit=self._row_limit,
            check_seccode=False,
        )

    def fetch_stock_share_change_raw(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> CninfoCorporateActionRawResult:
        """Fetch and validate one stock_share_change request; returns official codes."""
        code = _normalize_single_symbol(symbol)
        _validate_date8(start_date)
        _validate_date8(end_date)
        if start_date > end_date:
            raise CninfoConnectorError("CNINFO_REQUEST_PARAMS_INVALID")
        params = {
            "scode": code,
            "sdate": _date8_to_iso(start_date),
            "edate": _date8_to_iso(end_date),
        }
        payload = self._post(url=CNINFO_SHARE_CHANGE_API_URL, params=params)
        return _validate_corporate_action_payload(
            payload,
            endpoint=CNINFO_SHARE_CHANGE_ENDPOINT,
            requested_code=code,
            row_limit=self._row_limit,
            check_seccode=True,
        )

    def _post(self, *, url: str, params: Mapping[str, str]) -> Mapping[str, Any]:
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
            return client.post_json(url=url, params=params, headers=headers)
        except CninfoConnectorError:
            raise
        except Exception as exc:
            raise _sanitize_network(exc) from None

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


def empty_cninfo_dividend_frame() -> pl.DataFrame:
    """Complete empty stock_dividend schema with frozen official field order."""
    return pl.DataFrame(
        {name: [] for name in CNINFO_STOCK_DIVIDEND_FIELDS},
        schema={name: pl.Utf8 for name in CNINFO_STOCK_DIVIDEND_FIELDS},
    )


def empty_cninfo_share_change_frame() -> pl.DataFrame:
    """Complete empty stock_share_change schema with frozen official field order."""
    return pl.DataFrame(
        {name: [] for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS},
        schema={name: pl.Utf8 for name in CNINFO_STOCK_SHARE_CHANGE_FIELDS},
    )


def _fields_for_endpoint(
    endpoint: Literal["stock_dividend", "stock_share_change"],
) -> tuple[str, ...]:
    if endpoint == CNINFO_DIVIDEND_ENDPOINT:
        return CNINFO_STOCK_DIVIDEND_FIELDS
    if endpoint == CNINFO_SHARE_CHANGE_ENDPOINT:
        return CNINFO_STOCK_SHARE_CHANGE_FIELDS
    raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")


def _field_set_for_endpoint(
    endpoint: Literal["stock_dividend", "stock_share_change"],
) -> frozenset[str]:
    if endpoint == CNINFO_DIVIDEND_ENDPOINT:
        return CNINFO_STOCK_DIVIDEND_FIELD_SET
    if endpoint == CNINFO_SHARE_CHANGE_ENDPOINT:
        return CNINFO_STOCK_SHARE_CHANGE_FIELD_SET
    raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")


def _empty_frame_for_endpoint(
    endpoint: Literal["stock_dividend", "stock_share_change"],
) -> pl.DataFrame:
    if endpoint == CNINFO_DIVIDEND_ENDPOINT:
        return empty_cninfo_dividend_frame()
    if endpoint == CNINFO_SHARE_CHANGE_ENDPOINT:
        return empty_cninfo_share_change_frame()
    raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")


def _validate_allotment_payload(
    payload: Mapping[str, Any],
    *,
    requested_codes: set[str],
    row_limit: int,
) -> CninfoAllotmentRawResult:
    # Rights allotment keeps historical envelope tolerance (required keys present);
    # corporate-action endpoints enforce exact key sets separately.
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
        resultcode=resultcode,
        resultmsg=resultmsg,
        count=count,
        total=total,
    )


def _validate_corporate_action_payload(
    payload: Mapping[str, Any],
    *,
    endpoint: Literal["stock_dividend", "stock_share_change"],
    requested_code: str,
    row_limit: int,
    check_seccode: bool,
) -> CninfoCorporateActionRawResult:
    fields = _fields_for_endpoint(endpoint)
    field_set = _field_set_for_endpoint(endpoint)
    resultcode, resultmsg, count, total, records = _parse_exact_envelope(
        payload, row_limit=row_limit
    )
    if count == 0:
        return CninfoCorporateActionRawResult(
            endpoint=endpoint,
            frame=_empty_frame_for_endpoint(endpoint),
            resultcode=200,
            resultmsg="success",
            count=0,
            total=0,
        )

    rows: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, Mapping):
            raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
        keys = frozenset(item.keys())
        if keys != field_set:
            raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
        if check_seccode:
            seccode = item.get("SECCODE")
            if type(seccode) is not str or seccode != requested_code:
                raise CninfoConnectorError("CNINFO_RESPONSE_SCOPE_INVALID")
        row: dict[str, Any] = {}
        for name in fields:
            row[name] = _canonicalize_cell(item[name])
        rows.append(row)

    frame = pl.DataFrame(rows, schema={name: pl.Utf8 for name in fields})
    return CninfoCorporateActionRawResult(
        endpoint=endpoint,
        frame=frame,
        resultcode=resultcode,
        resultmsg=resultmsg,
        count=count,
        total=total,
    )


def _parse_exact_envelope(
    payload: Mapping[str, Any], *, row_limit: int
) -> tuple[int, str, int, int, list[Any]]:
    if not isinstance(payload, Mapping):
        raise CninfoConnectorError("CNINFO_RESPONSE_SCHEMA_INVALID")
    if frozenset(payload.keys()) != _PAYLOAD_KEYS:
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
    return resultcode, resultmsg, count, total, records


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


def _normalize_single_symbol(symbol: str) -> str:
    if type(symbol) is not str or not symbol:
        raise CninfoConnectorError("CNINFO_REQUEST_PARAMS_INVALID")
    if "," in symbol:
        raise CninfoConnectorError("CNINFO_REQUEST_PARAMS_INVALID")
    codes = normalize_cninfo_symbols([symbol])
    if len(codes) != 1 or codes[0] != symbol:
        raise CninfoConnectorError("CNINFO_REQUEST_PARAMS_INVALID")
    return codes[0]


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
