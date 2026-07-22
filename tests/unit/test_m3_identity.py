"""Unit tests for m3-clean-table-content-v1 identity."""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from quant.data.m3_identity import M3CleanTableIdentityError, clean_table_content_sha256


def test_row_order_stable_and_column_order_sensitive() -> None:
    left = pl.DataFrame(
        {
            "as_of": [dt.date(2016, 2, 1), dt.date(2016, 2, 2)],
            "symbol": ["000001.SZ", "000002.SZ"],
        }
    )
    right = left.reverse()
    assert clean_table_content_sha256(table_name="eligible_keys", frame=left) == (
        clean_table_content_sha256(table_name="eligible_keys", frame=right)
    )
    swapped = left.select(["symbol", "as_of"])
    assert clean_table_content_sha256(table_name="eligible_keys", frame=left) != (
        clean_table_content_sha256(table_name="eligible_keys", frame=swapped)
    )


def test_dtype_value_duplicate_and_table_name_sensitivity() -> None:
    base = pl.DataFrame({"n": [1, 2], "w": [1.0, 2.0]})
    digest = clean_table_content_sha256(table_name="t1", frame=base)
    as_i64 = pl.DataFrame({"n": pl.Series([1, 2], dtype=pl.Int64), "w": [1.0, 2.0]})
    assert digest == clean_table_content_sha256(table_name="t1", frame=as_i64)
    changed_value = pl.DataFrame({"n": [1, 2], "w": [1.0, 2.1]})
    assert digest != clean_table_content_sha256(table_name="t1", frame=changed_value)
    dup = pl.DataFrame({"n": [1, 1], "w": [1.0, 1.0]})
    single = pl.DataFrame({"n": [1], "w": [1.0]})
    assert clean_table_content_sha256(table_name="t1", frame=dup) != (
        clean_table_content_sha256(table_name="t1", frame=single)
    )
    assert digest != clean_table_content_sha256(table_name="t2", frame=base)


def test_negative_zero_normalized_and_datetime_rejected() -> None:
    a = pl.DataFrame({"w": [0.0]})
    b = pl.DataFrame({"w": [-0.0]})
    assert clean_table_content_sha256(table_name="t", frame=a) == (
        clean_table_content_sha256(table_name="t", frame=b)
    )
    bad = pl.DataFrame({"ts": [dt.datetime(2016, 1, 1, 12, 0, 0)]})
    with pytest.raises(M3CleanTableIdentityError, match="G1_TABLE_IDENTITY_INVALID"):
        clean_table_content_sha256(table_name="t", frame=bad)


def test_nonfinite_and_unsupported_and_bad_table_name() -> None:
    with pytest.raises(M3CleanTableIdentityError, match="G1_TABLE_IDENTITY_INVALID"):
        clean_table_content_sha256(
            table_name="t", frame=pl.DataFrame({"w": [float("nan")]})
        )
    with pytest.raises(M3CleanTableIdentityError, match="G1_TABLE_IDENTITY_INVALID"):
        clean_table_content_sha256(
            table_name="t", frame=pl.DataFrame({"w": [float("inf")]})
        )
    with pytest.raises(M3CleanTableIdentityError, match="G1_TABLE_IDENTITY_INVALID"):
        clean_table_content_sha256(table_name="Bad", frame=pl.DataFrame({"w": [1.0]}))
    with pytest.raises(M3CleanTableIdentityError, match="G1_TABLE_IDENTITY_INVALID"):
        clean_table_content_sha256(table_name="", frame=pl.DataFrame({"w": [1.0]}))


def test_null_bool_int_date_string_roundtrip_tags() -> None:
    frame = pl.DataFrame(
        {
            "flag": [True, None],
            "n": [1, None],
            "d": [dt.date(2016, 1, 4), None],
            "s": ["α", None],
        }
    )
    digest = clean_table_content_sha256(table_name="mixed", frame=frame)
    assert len(digest) == 64 and digest == digest.lower()
    # Duplicate identical rows retained -> different from unique.
    dup = pl.concat([frame, frame])
    assert clean_table_content_sha256(table_name="mixed", frame=dup) != digest


def test_error_repr_is_stable_code_only() -> None:
    err = M3CleanTableIdentityError("G1_TABLE_IDENTITY_INVALID")
    assert str(err) == "G1_TABLE_IDENTITY_INVALID"
    assert repr(err) == "M3CleanTableIdentityError('G1_TABLE_IDENTITY_INVALID')"
    with pytest.raises(ValueError, match="unknown"):
        M3CleanTableIdentityError("NOPE")
