"""CNINFO connector contract tests (zero network via fake client)."""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from quant.data.connectors.cninfo import (
    CNINFO_STOCK_ALLOTMENT_FIELDS,
    CninfoConnector,
    CninfoConnectorError,
    batch_cninfo_symbol_groups,
    empty_cninfo_allotment_frame,
    normalize_cninfo_symbols,
)


class _FakeClient:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def post_json(
        self, *, url: str, params: Mapping[str, str], headers: Mapping[str, str]
    ) -> Mapping[str, Any]:
        del url, params
        assert "Accept-Enckey" in headers
        self.calls += 1
        return self.payload


def _record(**overrides: Any) -> dict[str, Any]:
    base = {name: None for name in CNINFO_STOCK_ALLOTMENT_FIELDS}
    base.update(
        {
            "SUBID": 1,
            "SECCODE": "000001",
            "SECNAME": "TEST",
            "DECLAREDATE": "2016-04-14",
            "F011D": "2016-04-18",
            "F012D": "2016-04-27",
            "F013D": "2016-04-19",
            "F014D": "2016-04-25",
            "F005N": 10.0,
            "F004N": 3.0,
            "F017N": 1.0,
            "F024N": 10.0,
            "F025N": 11.0,
            "F052D": "2016-04-27",
            "F038D": "2016-05-09",
            "F002V": "A股",
            "F001V": "001001",
        }
    )
    base.update(overrides)
    return base


def test_normalize_and_batch_50() -> None:
    codes = normalize_cninfo_symbols(["000002.SZ", "000001.SH", "000002.SZ"])
    assert codes == ("000001", "000002")
    groups = batch_cninfo_symbol_groups(
        [f"{i:06d}.SZ" for i in range(100, 150)], batch_size=50
    )
    assert len(groups) == 1
    assert len(groups[0]) == 50


def test_two_codes_and_out_of_scope_rejected() -> None:
    payload = {
        "resultcode": 200,
        "resultmsg": "success",
        "count": 1,
        "total": 1,
        "records": [_record(SECCODE="999999")],
    }
    connector = CninfoConnector(
        client=_FakeClient(payload), enckey_provider=lambda: "fake-key"
    )
    with pytest.raises(CninfoConnectorError) as exc:
        connector.fetch_stock_allotment_raw(
            symbols="000001,000002", start_date="20160101", end_date="20161231"
        )
    assert exc.value.code == "CNINFO_RESPONSE_SCOPE_INVALID"


def test_schema_failures() -> None:
    connector = CninfoConnector(
        client=_FakeClient(
            {
                "resultcode": 500,
                "resultmsg": "success",
                "count": 0,
                "total": 0,
                "records": [],
            }
        ),
        enckey_provider=lambda: "fake-key",
    )
    with pytest.raises(CninfoConnectorError):
        connector.fetch_stock_allotment_raw(
            symbols="000001", start_date="20160101", end_date="20161231"
        )

    bad_count = CninfoConnector(
        client=_FakeClient(
            {
                "resultcode": 200,
                "resultmsg": "success",
                "count": 1,
                "total": 0,
                "records": [],
            }
        ),
        enckey_provider=lambda: "fake-key",
    )
    with pytest.raises(CninfoConnectorError):
        bad_count.fetch_stock_allotment_raw(
            symbols="000001", start_date="20160101", end_date="20161231"
        )

    drift = dict(_record())
    drift.pop("SUBID")
    drift_client = CninfoConnector(
        client=_FakeClient(
            {
                "resultcode": 200,
                "resultmsg": "success",
                "count": 1,
                "total": 1,
                "records": [drift],
            }
        ),
        enckey_provider=lambda: "fake-key",
    )
    with pytest.raises(CninfoConnectorError):
        drift_client.fetch_stock_allotment_raw(
            symbols="000001", start_date="20160101", end_date="20161231"
        )

    dup = CninfoConnector(
        client=_FakeClient(
            {
                "resultcode": 200,
                "resultmsg": "success",
                "count": 2,
                "total": 2,
                "records": [_record(SUBID=1), _record(SUBID=1, SECCODE="000002")],
            }
        ),
        enckey_provider=lambda: "fake-key",
    )
    with pytest.raises(CninfoConnectorError):
        dup.fetch_stock_allotment_raw(
            symbols="000001,000002", start_date="20160101", end_date="20161231"
        )


def test_empty_response_complete_schema() -> None:
    client = _FakeClient(
        {
            "resultcode": 200,
            "resultmsg": "success",
            "count": 0,
            "total": 0,
            "records": [],
        }
    )
    connector = CninfoConnector(client=client, enckey_provider=lambda: "fake-key")
    result = connector.fetch_stock_allotment_raw(
        symbols="000001", start_date="20160101", end_date="20161231"
    )
    assert result.count == 0
    assert tuple(result.frame.columns) == CNINFO_STOCK_ALLOTMENT_FIELDS
    assert result.frame.height == 0
    assert client.calls == 1
    assert empty_cninfo_allotment_frame().columns == list(CNINFO_STOCK_ALLOTMENT_FIELDS)


def test_637_symbols_make_13_batches() -> None:
    symbols = [f"{i:06d}.SZ" for i in range(637)]
    groups = batch_cninfo_symbol_groups(symbols, batch_size=50)
    assert len(groups) == 13
    flat = [code for group in groups for code in group]
    assert flat == sorted(set(flat))
    assert len(flat) == 637
