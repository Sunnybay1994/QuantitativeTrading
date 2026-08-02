"""Strict retained-byte parser for one HKEX Daily Quotations record.

The parser is deliberately independent from vendor ``hk_daily`` ingestion.  A
parsed record becomes verified evidence only when every sales record closes the
official quotation summary under the explicit whole-HKD rounding contract.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import NoReturn, cast

SOURCE = "HKEX_DAILY_QUOTATIONS"
SOURCE_URL = "https://www.hkex.com.hk/eng/stat/smstat/dayquot/d260710e.htm"
PARSER_VERSION = "hkex-daily-quotations-2983-v1"
TURNOVER_ROUNDING_VERSION = "hkex-turnover-whole-hkd-round-half-up-v1"
EXPECTED_DATE = dt.date(2026, 7, 10)
EXPECTED_SYMBOL = "02983.HK"
EXPECTED_CODE = 2983
EXPECTED_NAME = "HESAI-W"
EXPECTED_CURRENCY = "HKD"
EXPECTED_RAW_SHA256 = "67d1109fe358021543579a6cb5f26c2a31c47f8feae6543e451f8356efcec5b8"
EXPECTED_RAW_SIZE = 32_792_632

_INVALID = "HKEX_DAILY_QUOTATIONS_INVALID"
_NOT_CLOSED = "HKEX_DAILY_QUOTATIONS_NOT_CLOSED"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_FLAGS = frozenset({"", "D", "U", "X", "Y"})
_SALE = re.compile(
    r"(?<![A-Za-z0-9])([A-Z]?)([0-9][0-9,]*)-([0-9]+(?:\.[0-9]+)?)"
)
_RECORD_START = re.compile(r"^ ?[0-9]{1,5} [^ ]")
_PAGE_BREAK = "</font></pre><pre><font size='1'>"


class HKEXDailyQuotationsError(ValueError):
    """Stable fail-closed retained-source parsing error."""


def _fail(code: str) -> NoReturn:
    raise HKEXDailyQuotationsError(code) from None


def _decimal(value: str) -> Decimal:
    parsed = Decimal(value)
    if not parsed.is_finite() or parsed < 0:
        raise ValueError
    return parsed


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError
    if value == 0:
        return "0"
    sign, raw_digits, raw_exponent = value.as_tuple()
    exponent = cast(int, raw_exponent)
    digits = list(raw_digits)
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = "".join(str(digit) for digit in digits)
    point = len(coefficient) + exponent
    if point <= 0:
        text = "0." + "0" * (-point) + coefficient
    elif point < len(coefficient):
        text = coefficient[:point] + "." + coefficient[point:]
    else:
        text = coefficient + "0" * exponent
    return "-" + text if sign else text


@dataclass(frozen=True, slots=True)
class HKEXSaleRecord:
    """One sales-record token in official report order."""

    sequence: int
    flag: str
    quantity: int
    price: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.sequence) is not int
            or self.sequence < 0
            or self.flag not in _ALLOWED_FLAGS
            or type(self.quantity) is not int
            or self.quantity <= 0
            or type(self.price) is not Decimal
            or not self.price.is_finite()
            or self.price <= 0
        ):
            _fail(_INVALID)


def _candidate_payload(value: ParsedHKEXDailyQuotation) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "source": value.source,
        "source_url": value.source_url,
        "source_record_id": value.source_record_id,
        "parser_version": value.parser_version,
        "turnover_rounding_version": value.turnover_rounding_version,
        "raw_sha256": value.raw_sha256,
        "raw_size": value.raw_size,
        "trade_date": value.trade_date.isoformat(),
        "symbol": value.symbol,
        "code": value.code,
        "name": value.name,
        "currency": value.currency,
        "previous_close": _decimal_text(value.previous_close),
        "open": _decimal_text(value.open),
        "high": _decimal_text(value.high),
        "low": _decimal_text(value.low),
        "close": _decimal_text(value.close),
        "volume": value.volume,
        "quotation_turnover": _decimal_text(value.quotation_turnover),
        "sales_record_count": value.sales_record_count,
        "sales_volume": value.sales_volume,
        "sales_turnover": _decimal_text(value.sales_turnover),
        "sales_flags": list(value.sales_flags),
        "sales_flag_counts": [list(item) for item in value.sales_flag_counts],
        "first_sale_price": _decimal_text(value.first_sale_price),
        "last_sale_price": _decimal_text(value.last_sale_price),
        "minimum_sale_price": _decimal_text(value.minimum_sale_price),
        "maximum_sale_price": _decimal_text(value.maximum_sale_price),
    }


def _identity(type_name: str, payload: object) -> str:
    raw = json.dumps(
        {"type": type_name, "version": 1, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ParsedHKEXDailyQuotation:
    """Identity-bound parse result; it is not yet verified evidence."""

    parsed_id: str
    schema_version: str
    source: str
    source_url: str
    source_record_id: str
    parser_version: str
    turnover_rounding_version: str
    raw_sha256: str
    raw_size: int
    trade_date: dt.date
    symbol: str
    code: int
    name: str
    currency: str
    previous_close: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    quotation_turnover: Decimal
    sales_record_count: int
    sales_volume: int
    sales_turnover: Decimal
    sales_flags: tuple[str, ...]
    sales_flag_counts: tuple[tuple[str, int], ...]
    first_sale_price: Decimal
    last_sale_price: Decimal
    minimum_sale_price: Decimal
    maximum_sale_price: Decimal

    def __post_init__(self) -> None:
        decimals = (
            self.previous_close,
            self.open,
            self.high,
            self.low,
            self.close,
            self.quotation_turnover,
            self.sales_turnover,
            self.first_sale_price,
            self.last_sale_price,
            self.minimum_sale_price,
            self.maximum_sale_price,
        )
        if (
            not _HEX64.fullmatch(self.parsed_id)
            or self.schema_version != "hkex-daily-quotation-parse-v1"
            or self.source != SOURCE
            or self.source_url != SOURCE_URL
            or self.source_record_id != "HKEX_DAILY_QUOTATIONS:2026-07-10:2983"
            or self.parser_version != PARSER_VERSION
            or self.turnover_rounding_version != TURNOVER_ROUNDING_VERSION
            or not _HEX64.fullmatch(self.raw_sha256)
            or type(self.raw_size) is not int
            or self.raw_size <= 0
            or self.trade_date != EXPECTED_DATE
            or self.symbol != EXPECTED_SYMBOL
            or self.code != EXPECTED_CODE
            or self.name != EXPECTED_NAME
            or self.currency != EXPECTED_CURRENCY
            or any(
                type(item) is not Decimal or not item.is_finite() or item < 0
                for item in decimals
            )
            or type(self.volume) is not int
            or self.volume <= 0
            or type(self.sales_record_count) is not int
            or self.sales_record_count <= 0
            or type(self.sales_volume) is not int
            or self.sales_volume <= 0
            or type(self.sales_flags) is not tuple
            or tuple(sorted(set(self.sales_flags))) != self.sales_flags
            or any(flag not in _ALLOWED_FLAGS for flag in self.sales_flags)
            or type(self.sales_flag_counts) is not tuple
            or any(
                type(item) is not tuple
                or len(item) != 2
                or item[0] not in _ALLOWED_FLAGS
                or type(item[1]) is not int
                or item[1] <= 0
                for item in self.sales_flag_counts
            )
            or tuple(sorted(self.sales_flag_counts)) != self.sales_flag_counts
            or tuple(item[0] for item in self.sales_flag_counts) != self.sales_flags
            or sum(item[1] for item in self.sales_flag_counts)
            != self.sales_record_count
            or self.parsed_id != _identity("ParsedHKEXDailyQuotation", _candidate_payload(self))
        ):
            _fail(_INVALID)


def _verified_payload(value: ParsedHKEXDailyQuotation) -> dict[str, object]:
    return {
        "parsed_id": value.parsed_id,
        "raw_sha256": value.raw_sha256,
        "source_url": value.source_url,
        "source_record_id": value.source_record_id,
        "parser_version": value.parser_version,
        "turnover_rounding_version": value.turnover_rounding_version,
        "trade_date": value.trade_date.isoformat(),
        "symbol": value.symbol,
    }


class VerifiedHKEXDailyQuotation:
    """Public result type; instances only come from retained-byte verification."""

    __slots__ = ("evidence_id", "evidence")

    evidence_id: str
    evidence: ParsedHKEXDailyQuotation

    def __new__(cls, *_args: object, **_kwargs: object) -> VerifiedHKEXDailyQuotation:
        del cls
        _fail(_INVALID)

    def __init_subclass__(cls, **_kwargs: object) -> None:
        del cls
        raise TypeError("VerifiedHKEXDailyQuotation is final")

    def __setattr__(self, _name: str, _value: object) -> NoReturn:
        _fail(_INVALID)


def _quotation(lines: list[str], start: int, end: int) -> tuple[Decimal, ...]:
    code_matches = [
        index
        for index in range(start, end)
        if re.match(r"^\s*2983\s+", lines[index])
    ]
    matches = [
        index
        for index in code_matches
        if re.match(r"^\s*2983\s+HESAI-W\s+HKD\s+", lines[index])
    ]
    if len(code_matches) != 1 or len(matches) != 1 or matches[0] + 1 >= end:
        raise ValueError
    first = re.fullmatch(
        r"\s*2983\s+HESAI-W\s+HKD\s+([0-9.]+)\s+([0-9.]+|-)\s+"
        r"([0-9.]+)\s+([0-9,]+)\s*",
        lines[matches[0]],
    )
    second = re.fullmatch(
        r"\s+([0-9.]+)\s+([0-9.]+|-)\s+([0-9.]+)\s+([0-9,]+)\s*",
        lines[matches[0] + 1],
    )
    if first is None or second is None:
        raise ValueError
    previous_close, _ask, high, volume = first.groups()
    close, _bid, low, turnover = second.groups()
    return (
        _decimal(previous_close),
        _decimal(close),
        _decimal(high),
        _decimal(low),
        Decimal(volume.replace(",", "")),
        _decimal(turnover.replace(",", "")),
    )


def _sales(lines: list[str], start: int, end: int) -> tuple[HKEXSaleRecord, ...]:
    code_matches = [
        index
        for index in range(start, end)
        if re.match(r"^ ?2983\s+", lines[index])
    ]
    matches = [
        index
        for index in code_matches
        if re.match(r"^ ?2983 HESAI-W\s+<", lines[index])
    ]
    if len(code_matches) != 1 or len(matches) != 1:
        raise ValueError
    first = matches[0]
    last = next(
        (index for index in range(first + 1, end) if _RECORD_START.match(lines[index])),
        end,
    )
    block = " ".join(lines[first:last])
    prefix = re.match(r"^ ?2983 HESAI-W\s+", block)
    if prefix is None:
        raise ValueError
    body = block[prefix.end() :].replace(_PAGE_BREAK, "")
    raw_records = list(_SALE.finditer(body))
    if not raw_records:
        raise ValueError
    unexplained = _SALE.sub("", body)
    skeleton = "".join(unexplained.split())
    if skeleton != "<>[]/-//[]<>":
        raise ValueError
    records: list[HKEXSaleRecord] = []
    for sequence, match in enumerate(raw_records):
        flag, quantity, price = match.groups()
        if flag not in _ALLOWED_FLAGS:
            raise ValueError
        records.append(
            HKEXSaleRecord(
                sequence=sequence,
                flag=flag,
                quantity=int(quantity.replace(",", "")),
                price=_decimal(price),
            )
        )
    return tuple(records)


def parse_hkex_daily_quotation(
    raw: bytes,
    *,
    source_url: str,
    expected_raw_sha256: str,
) -> ParsedHKEXDailyQuotation:
    """Parse the exact official sections and preserve unrounded sales turnover."""
    try:
        if (
            type(raw) is not bytes
            or not raw
            or source_url != SOURCE_URL
            or not _HEX64.fullmatch(expected_raw_sha256)
        ):
            raise ValueError
        raw_sha256 = hashlib.sha256(raw).hexdigest()
        if raw_sha256 != expected_raw_sha256:
            raise ValueError
        text = raw.decode("ascii")
        lines = text.splitlines()
        date_marker = "DATE: 10 JUL 2026 (FRIDAY)"
        quotation_marker = '<a name = "quotations">QUOTATIONS</a>'
        sales_marker = '<a name = "sales_all">SALES RECORDS FOR ALL STOCKS</a>'
        sales_over_marker = '<a name = "sales_over">SALES RECORDS OVER $500,000</a>'
        if (
            text.count(date_marker) != 1
            or text.count(quotation_marker) != 1
            or text.count(sales_marker) != 1
            or text.count(sales_over_marker) != 1
            or "C  = Closing Auction Direct/Non-direct" not in text
            or "D  = Odd Lot Direct/Non-direct" not in text
            or "U  = Auction Direct" not in text
            or "Y  = Automatch Direct" not in text
        ):
            raise ValueError
        quotation_start = next(i for i, line in enumerate(lines) if quotation_marker in line)
        sales_start = next(i for i, line in enumerate(lines) if sales_marker in line)
        sales_end = next(i for i, line in enumerate(lines) if sales_over_marker in line)
        if not quotation_start < sales_start < sales_end:
            raise ValueError
        previous_close, close, high, low, volume_value, turnover = _quotation(
            lines, quotation_start, sales_start
        )
        records = _sales(lines, sales_start, sales_end)
        volume = int(volume_value)
        sales_volume = sum(item.quantity for item in records)
        required_precision = max(
            len(str(item.quantity)) + len(item.price.as_tuple().digits)
            for item in records
        ) + len(str(len(records))) + 2
        with localcontext() as context:
            context.prec = required_precision
            sales_turnover = sum(
                (Decimal(item.quantity) * item.price for item in records), Decimal(0)
            )
        flags = tuple(sorted({item.flag for item in records}))
        values: dict[str, object] = {
            "schema_version": "hkex-daily-quotation-parse-v1",
            "source": SOURCE,
            "source_url": source_url,
            "source_record_id": "HKEX_DAILY_QUOTATIONS:2026-07-10:2983",
            "parser_version": PARSER_VERSION,
            "turnover_rounding_version": TURNOVER_ROUNDING_VERSION,
            "raw_sha256": raw_sha256,
            "raw_size": len(raw),
            "trade_date": EXPECTED_DATE,
            "symbol": EXPECTED_SYMBOL,
            "code": EXPECTED_CODE,
            "name": EXPECTED_NAME,
            "currency": EXPECTED_CURRENCY,
            "previous_close": previous_close,
            "open": records[0].price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "quotation_turnover": turnover,
            "sales_record_count": len(records),
            "sales_volume": sales_volume,
            "sales_turnover": sales_turnover,
            "sales_flags": flags,
            "sales_flag_counts": tuple(
                (flag, sum(item.flag == flag for item in records)) for flag in flags
            ),
            "first_sale_price": records[0].price,
            "last_sale_price": records[-1].price,
            "minimum_sale_price": min(item.price for item in records),
            "maximum_sale_price": max(item.price for item in records),
        }
        provisional = ParsedHKEXDailyQuotation.__new__(ParsedHKEXDailyQuotation)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        object.__setattr__(provisional, "parsed_id", "0" * 64)
        parsed_id = _identity("ParsedHKEXDailyQuotation", _candidate_payload(provisional))
        return ParsedHKEXDailyQuotation(parsed_id=parsed_id, **values)  # type: ignore[arg-type]
    except HKEXDailyQuotationsError:
        raise
    except Exception:
        _fail(_INVALID)


def _validate_verified_evidence(
    parsed: ParsedHKEXDailyQuotation,
) -> ParsedHKEXDailyQuotation:
    """Rebuild and validate the official identity plus every quotation closure."""
    try:
        if type(parsed) is not ParsedHKEXDailyQuotation:
            raise ValueError
        rebuilt = ParsedHKEXDailyQuotation(
            **{name: getattr(parsed, name) for name in parsed.__slots__}
        )
        if (
            rebuilt.sales_volume != rebuilt.volume
            or rebuilt.first_sale_price != rebuilt.open
            or rebuilt.last_sale_price != rebuilt.close
            or rebuilt.minimum_sale_price != rebuilt.low
            or rebuilt.maximum_sale_price != rebuilt.high
            or rebuilt.sales_turnover.to_integral_value(rounding=ROUND_HALF_UP)
            != rebuilt.quotation_turnover
        ):
            _fail(_NOT_CLOSED)
        if (
            rebuilt.source_url != SOURCE_URL
            or rebuilt.raw_sha256 != EXPECTED_RAW_SHA256
            or rebuilt.raw_size != EXPECTED_RAW_SIZE
        ):
            _fail(_INVALID)
        return rebuilt
    except HKEXDailyQuotationsError:
        raise
    except Exception:
        _fail(_INVALID)


def _make_verified_evidence(
    evidence: ParsedHKEXDailyQuotation,
) -> VerifiedHKEXDailyQuotation:
    """Create the exact final capability after fresh internal validation."""
    rebuilt = _validate_verified_evidence(evidence)
    evidence_id = _identity("VerifiedHKEXDailyQuotation", _verified_payload(rebuilt))
    value = object.__new__(VerifiedHKEXDailyQuotation)
    object.__setattr__(value, "evidence_id", evidence_id)
    object.__setattr__(value, "evidence", rebuilt)
    if (
        type(value) is not VerifiedHKEXDailyQuotation
        or not _HEX64.fullmatch(value.evidence_id)
        or value.evidence_id
        != _identity("VerifiedHKEXDailyQuotation", _verified_payload(value.evidence))
    ):
        _fail(_INVALID)
    return value


def verify_hkex_daily_quotation(
    raw: bytes,
    *,
    source_url: str,
    expected_raw_sha256: str,
) -> VerifiedHKEXDailyQuotation:
    """Verify retained official bytes; Parsed objects are never verification input."""
    try:
        if expected_raw_sha256 != EXPECTED_RAW_SHA256:
            raise ValueError
        rebuilt = _validate_verified_evidence(
            parse_hkex_daily_quotation(
                raw,
                source_url=source_url,
                expected_raw_sha256=expected_raw_sha256,
            )
        )
        return _make_verified_evidence(rebuilt)
    except HKEXDailyQuotationsError:
        raise
    except Exception:
        _fail(_INVALID)


def parse_and_verify_hkex_daily_quotation(
    raw: bytes,
    *,
    source_url: str,
    expected_raw_sha256: str,
) -> VerifiedHKEXDailyQuotation:
    """Compatibility name for the retained-byte-only verification entrypoint."""
    return verify_hkex_daily_quotation(
        raw,
        source_url=source_url,
        expected_raw_sha256=expected_raw_sha256,
    )


__all__ = [
    "EXPECTED_RAW_SHA256",
    "EXPECTED_RAW_SIZE",
    "HKEXDailyQuotationsError",
    "HKEXSaleRecord",
    "PARSER_VERSION",
    "ParsedHKEXDailyQuotation",
    "SOURCE",
    "SOURCE_URL",
    "TURNOVER_ROUNDING_VERSION",
    "VerifiedHKEXDailyQuotation",
    "parse_and_verify_hkex_daily_quotation",
    "parse_hkex_daily_quotation",
    "verify_hkex_daily_quotation",
]
