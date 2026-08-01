from __future__ import annotations

import pytest

from quant.research.m3.qlib_adapter import _require_feature_frame_contract


def test_provider_worker_rejects_wrong_multiindex_order() -> None:
    pandas = pytest.importorskip("pandas")
    index = pandas.MultiIndex.from_tuples(
        [(pandas.Timestamp("2026-01-05"), "SZ000001")],
        names=("datetime", "instrument"),
    )
    frame = pandas.DataFrame({"$close": [10.0]}, index=index)

    with pytest.raises(ValueError, match="MultiIndex"):
        _require_feature_frame_contract(frame, ["$close"])


def test_provider_worker_rejects_field_order_drift() -> None:
    pandas = pytest.importorskip("pandas")
    index = pandas.MultiIndex.from_tuples(
        [("SZ000001", pandas.Timestamp("2026-01-05"))],
        names=("instrument", "datetime"),
    )
    frame = pandas.DataFrame(
        [[10.0, 11.0]], index=index, columns=["$close", "$open"]
    )

    with pytest.raises(ValueError, match="columns"):
        _require_feature_frame_contract(frame, ["$open", "$close"])
