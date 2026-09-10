import datetime as dt
import struct

import pytest

from quant.data.tdx_extra import decode_financial, decode_hk, decode_stock


def test_hk_float_prices_and_bad_rows():
    payload = struct.pack("<IfffffIf", 20260909, 69.5, 70.35, 69.2, 70.35,
                          392325472, 56099, 1843000)
    good, excluded = decode_hk(payload, "00001.HK")
    assert excluded == 0
    assert good["close"][0] == pytest.approx(70.35)
    assert good["volume_raw"][0] == 56099
    assert good["trade_date"][0] == dt.date(2026, 9, 9)
    duplicate, excluded = decode_hk(payload * 2, "00001.HK")
    assert duplicate.is_empty() and excluded == 2
    with pytest.raises(ValueError, match="truncated"):
        decode_hk(payload[:-1], "00001.HK")


def test_financial_offset_fields_and_no_assumed_publication_date():
    payload = (struct.pack("<hIHIII", 1, 20260630, 1, 0, 8, 0)
               + struct.pack("<6sBI", b"000001", 0, 31)
               + struct.pack("<ff", 0.75, 1234))
    frame = decode_financial(payload)
    assert frame["field_001"][0] == 0.75
    assert frame["field_002"][0] == 1234
    assert frame["available_date"][0] is None
    assert frame["pit_ready"][0] is False
    with pytest.raises(ValueError, match="offset"):
        decode_financial(payload[:-1])


def test_stock_preserves_unknown_fields_and_invalid_date():
    frame = decode_stock(struct.pack("<BIff", 50, 0, 1.25, 2.5))
    assert frame["field_id"][0] == 50
    assert frame["value_raw"][0] == 1.25
    assert frame["aux_raw"][0] == 2.5
    assert frame["record_date"][0] is None
    with pytest.raises(ValueError):
        decode_stock(b"x")


def test_empty_financial_unsigned_negative_size():
    frame = decode_financial(struct.pack("<hIHIII", 1, 19881231, 0, 720896, 0xFFFFFFFC, 0))
    assert frame.is_empty()
    assert "available_date" in frame.columns


def test_financial_duplicate_records_are_preserved_and_marked():
    payload = (struct.pack("<hIHIII", 1, 20260630, 2, 0, 4, 0)
               + struct.pack("<6sBI", b"301192", 0, 42)
               + struct.pack("<6sBI", b"301192", 0, 46)
               + struct.pack("<ff", 0.13, 0.14))
    frame = decode_financial(payload)
    assert frame.height == 2
    assert frame["duplicate_security"].all()
    assert frame["source_record"].to_list() == [0, 1]
