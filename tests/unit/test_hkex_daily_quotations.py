"""Strict HKEX Daily Quotations retained-byte evidence tests."""

from __future__ import annotations

import hashlib
from dataclasses import fields
from decimal import Decimal
from typing import Any

import pytest

import quant.data.hkex_daily_quotations as hkex_module
from quant.data.hkex_daily_quotations import (
    EXPECTED_RAW_SHA256,
    EXPECTED_RAW_SIZE,
    SOURCE,
    SOURCE_URL,
    TURNOVER_ROUNDING_VERSION,
    HKEXDailyQuotationsError,
    ParsedHKEXDailyQuotation,
    VerifiedHKEXDailyQuotation,
    parse_and_verify_hkex_daily_quotation,
    parse_hkex_daily_quotation,
    verify_hkex_daily_quotation,
)


def _raw(
    *,
    date: str = "10 JUL 2026 (FRIDAY)",
    code: str = "2983",
    name: str = "HESAI-W",
    currency: str = "HKD",
    volume: str = "680",
    turnover: str = "7,060",
    records: str | None = None,
) -> bytes:
    sales = records or (
        "< 160-10.00 U160-10.00 >[ Y160-11.00 ]/-//[ D40-10.50 ]"
        "< X160-10.50 >"
    )
    return (
        "THE STOCK EXCHANGE OF HONG KONG DATE: "
        f"{date}\n"
        '<a name = "quotations">QUOTATIONS</a>\n'
        " CODE  NAME OF STOCK CUR PRV.CLO. ASK HIGH SHARES TRADED\n"
        f"  {code} {name} HKD 9.50 10.60 11.00 {volume}\n"
        f"                       10.50 10.40 10.00 {turnover}\n"
        '<a name = "sales_all">SALES RECORDS FOR ALL STOCKS</a>\n'
        " C  = Closing Auction Direct/Non-direct\n"
        " D  = Odd Lot Direct/Non-direct\n"
        " U  = Auction Direct\n"
        " Y  = Automatch Direct\n"
        f" {code} {name}          {sales}\n"
        " 3005 NEXT STOCK       < >[ 1-1.00 ]/-//[ ]< >\n"
        '<a name = "sales_over">SALES RECORDS OVER $500,000</a>\n'
    ).replace(f"{name} HKD", f"{name} {currency}").encode("ascii")


def _parse(raw: bytes) -> ParsedHKEXDailyQuotation:
    return parse_hkex_daily_quotation(
        raw,
        source_url=SOURCE_URL,
        expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
    )


def test_exact_official_shape_builds_identity_bound_parsed_fixture() -> None:
    raw = _raw()
    value = _parse(raw)
    assert value.source == SOURCE == "HKEX_DAILY_QUOTATIONS"
    assert value.source != "tushare"
    assert value.symbol == "02983.HK"
    assert value.code == 2983 and value.name == "HESAI-W"
    assert value.currency == "HKD"
    assert value.previous_close == Decimal("9.50")
    assert (value.open, value.high, value.low, value.close) == (
        Decimal("10.00"),
        Decimal("11.00"),
        Decimal("10.00"),
        Decimal("10.50"),
    )
    assert value.volume == value.sales_volume == 680
    assert value.quotation_turnover == value.sales_turnover == Decimal("7060")
    assert value.sales_flag_counts == (
        ("", 1),
        ("D", 1),
        ("U", 1),
        ("X", 1),
        ("Y", 1),
    )
    assert value.turnover_rounding_version == TURNOVER_ROUNDING_VERSION
    assert len(value.parsed_id) == 64


def test_whole_hkd_round_half_up_is_explicit_and_preserves_decimal_total() -> None:
    raw = _raw(
        turnover="7,061",
        records=(
            "< 160-10.00 U160-10.00 >[ Y160-11.00 ]/-//[ D40-10.5125 ]"
            "< X160-10.50 >"
        ),
    )
    parsed = _parse(raw)
    assert parsed.sales_turnover == Decimal("7060.5000")
    assert parsed.quotation_turnover == Decimal("7061")


def test_self_consistent_synthetic_raw_can_parse_but_never_be_official_evidence() -> None:
    raw = _raw()
    parsed = _parse(raw)
    with pytest.raises(
        HKEXDailyQuotationsError, match="^HKEX_DAILY_QUOTATIONS_INVALID$"
    ):
        verify_hkex_daily_quotation(
            raw,
            source_url=SOURCE_URL,
            expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
        )
    with pytest.raises(
        HKEXDailyQuotationsError, match="^HKEX_DAILY_QUOTATIONS_INVALID$"
    ):
        parse_and_verify_hkex_daily_quotation(
            raw,
            source_url=SOURCE_URL,
            expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
        )
    with pytest.raises(
        HKEXDailyQuotationsError, match="^HKEX_DAILY_QUOTATIONS_INVALID$"
    ):
        VerifiedHKEXDailyQuotation(evidence_id="0" * 64, evidence=parsed)


def test_fixed_report_page_break_inside_sales_record_is_non_business_markup() -> None:
    tag = "</font></pre><pre><font size='1'>"
    raw = _raw().replace(b"Y160-11.00", f"Y160-11.00 {tag}".encode("ascii"))
    assert _parse(raw).sales_record_count == 5


@pytest.mark.parametrize(
    ("kwargs", "replace"),
    [
        ({"date": "09 JUL 2026 (THURSDAY)"}, None),
        ({"code": "2984"}, None),
        ({"name": "OTHER-W"}, None),
        ({"currency": "USD"}, None),
        ({}, ("U160-10.00", "C160-10.00")),
        ({}, ("SALES RECORDS FOR ALL STOCKS", "SALES RECORDS")),
    ],
)
def test_source_date_record_and_unknown_flag_drift_fail_closed(
    kwargs: dict[str, str], replace: tuple[str, str] | None
) -> None:
    raw = _raw(**kwargs)
    if replace is not None:
        raw = raw.replace(replace[0].encode(), replace[1].encode())
    with pytest.raises(
        HKEXDailyQuotationsError, match="^HKEX_DAILY_QUOTATIONS_INVALID$"
    ):
        _parse(raw)


def test_raw_digest_and_source_url_are_exact_inputs() -> None:
    raw = _raw()
    digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(
        HKEXDailyQuotationsError, match="^HKEX_DAILY_QUOTATIONS_INVALID$"
    ):
        parse_hkex_daily_quotation(
            raw, source_url=SOURCE_URL, expected_raw_sha256="0" * 64
        )
    with pytest.raises(
        HKEXDailyQuotationsError, match="^HKEX_DAILY_QUOTATIONS_INVALID$"
    ):
        parse_hkex_daily_quotation(
            raw, source_url="https://example.invalid/report", expected_raw_sha256=digest
        )


@pytest.mark.parametrize(
    "raw",
    [
        _raw(volume="681"),
        _raw(turnover="7,062"),
        _raw(records="< 160-10.00 U160-10.00 >[ Y160-10.90 ]/-//[ D40-10.50 ]< X160-10.50 >"),
        _raw(records="< 160-10.10 U160-10.00 >[ Y160-11.00 ]/-//[ D40-10.50 ]< X160-10.50 >"),
        _raw(records="< 160-10.00 U160-10.00 >[ Y160-11.00 ]/-//[ D40-10.50 ]< X160-10.40 >"),
    ],
)
def test_volume_turnover_min_open_and_last_price_must_close(raw: bytes) -> None:
    parsed = _parse(raw)
    with pytest.raises(
        HKEXDailyQuotationsError, match="^HKEX_DAILY_QUOTATIONS_NOT_CLOSED$"
    ):
        hkex_module._validate_verified_evidence(parsed)


def test_parsed_identity_is_freshly_reproved() -> None:
    parsed = _parse(_raw())
    forged = ParsedHKEXDailyQuotation.__new__(ParsedHKEXDailyQuotation)
    for field in fields(ParsedHKEXDailyQuotation):
        object.__setattr__(forged, field.name, getattr(parsed, field.name))
    object.__setattr__(forged, "sales_volume", parsed.sales_volume + 1)
    with pytest.raises(
        HKEXDailyQuotationsError, match="^HKEX_DAILY_QUOTATIONS_INVALID$"
    ):
        hkex_module._validate_verified_evidence(forged)

    forged_source = ParsedHKEXDailyQuotation.__new__(ParsedHKEXDailyQuotation)
    for field in fields(ParsedHKEXDailyQuotation):
        object.__setattr__(forged_source, field.name, getattr(parsed, field.name))
    object.__setattr__(forged_source, "raw_sha256", EXPECTED_RAW_SHA256)
    object.__setattr__(forged_source, "raw_size", EXPECTED_RAW_SIZE)
    with pytest.raises(
        HKEXDailyQuotationsError, match="^HKEX_DAILY_QUOTATIONS_INVALID$"
    ):
        hkex_module._validate_verified_evidence(forged_source)


def _reidentified_forgery(
    parsed: ParsedHKEXDailyQuotation, **changes: object
) -> ParsedHKEXDailyQuotation:
    values = {field.name: getattr(parsed, field.name) for field in fields(parsed)}
    values.update(changes)
    provisional = ParsedHKEXDailyQuotation.__new__(ParsedHKEXDailyQuotation)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "parsed_id", "0" * 64)
    values["parsed_id"] = hkex_module._identity(
        "ParsedHKEXDailyQuotation", hkex_module._candidate_payload(provisional)
    )
    return ParsedHKEXDailyQuotation(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("break_closure", [False, True])
def test_recomputed_forged_identities_cannot_use_public_verified_constructor(
    break_closure: bool,
) -> None:
    parsed = _parse(_raw())
    changes: dict[str, object] = {
        "raw_sha256": EXPECTED_RAW_SHA256,
        "raw_size": EXPECTED_RAW_SIZE,
    }
    if break_closure:
        changes["sales_volume"] = parsed.sales_volume + 1
    forged = _reidentified_forgery(parsed, **changes)
    evidence_id = hkex_module._identity(
        "VerifiedHKEXDailyQuotation", hkex_module._verified_payload(forged)
    )

    with pytest.raises(
        HKEXDailyQuotationsError, match="^HKEX_DAILY_QUOTATIONS_INVALID$"
    ):
        VerifiedHKEXDailyQuotation(evidence_id=evidence_id, evidence=forged)
    with pytest.raises(
        HKEXDailyQuotationsError, match="^HKEX_DAILY_QUOTATIONS_INVALID$"
    ):
        verify_hkex_daily_quotation(
            forged,  # type: ignore[arg-type]
            source_url=SOURCE_URL,
            expected_raw_sha256=EXPECTED_RAW_SHA256,
        )


def test_public_verified_subclass_cannot_create_a_capability() -> None:
    with pytest.raises(TypeError, match="^VerifiedHKEXDailyQuotation is final$"):

        class ForgedVerified(VerifiedHKEXDailyQuotation):
            pass


@pytest.mark.parametrize("break_closure", [False, True])
def test_hostile_subclass_cannot_override_new_and_write_forged_dict(
    break_closure: bool,
) -> None:
    parsed = _parse(_raw())
    changes: dict[str, object] = {
        "raw_sha256": EXPECTED_RAW_SHA256,
        "raw_size": EXPECTED_RAW_SIZE,
    }
    if break_closure:
        changes["sales_volume"] = parsed.sales_volume + 1
    forged = _reidentified_forgery(parsed, **changes)
    evidence_id = hkex_module._identity(
        "VerifiedHKEXDailyQuotation", hkex_module._verified_payload(forged)
    )
    capabilities: list[object] = []

    def hostile_new(
        cls: type[object], *_args: object, **_kwargs: object
    ) -> object:
        return object.__new__(cls)

    def hostile_init(self: Any, **payload: object) -> None:
        self.__dict__.update(payload)

    with pytest.raises(TypeError, match="^VerifiedHKEXDailyQuotation is final$"):
        hostile_type = type(
            "HostileVerified",
            (VerifiedHKEXDailyQuotation,),
            {"__new__": hostile_new, "__init__": hostile_init},
        )
        capabilities.append(
            hostile_type(evidence=forged, evidence_id=evidence_id)
        )

    assert not any(
        isinstance(value, VerifiedHKEXDailyQuotation) for value in capabilities
    )


def test_retained_raw_constants_are_frozen_without_reading_formal_data() -> None:
    assert EXPECTED_RAW_SIZE == 32_792_632
    assert EXPECTED_RAW_SHA256 == (
        "67d1109fe358021543579a6cb5f26c2a31c47f8feae6543e451f8356efcec5b8"
    )
