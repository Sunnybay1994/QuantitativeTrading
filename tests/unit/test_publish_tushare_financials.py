from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from quant.data.publish_tushare_financials import (
    TushareFinancialPublishError,
    publish_tushare_financial_snapshot,
)


def test_publisher_requires_explicit_plan_and_catalog_paths() -> None:
    signature = inspect.signature(publish_tushare_financial_snapshot)
    assert tuple(signature.parameters) == (
        "data_root",
        "plan_report_path",
        "catalog_path",
        "threads",
    )
    assert signature.parameters["plan_report_path"].default is inspect.Parameter.empty
    assert signature.parameters["catalog_path"].default is inspect.Parameter.empty


def test_invalid_plan_fails_before_snapshot_directory_creation(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(
        TushareFinancialPublishError,
        match="TUSHARE_FINANCIAL_PUBLISH_INVALID",
    ) as error:
        publish_tushare_financial_snapshot(
            data_root=root,
            plan_report_path=tmp_path / "missing-plan.json",
            catalog_path=tmp_path / "missing-catalog.toml",
        )
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert not (root / "clean" / "tushare_financials").exists()
