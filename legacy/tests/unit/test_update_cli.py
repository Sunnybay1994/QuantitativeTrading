"""增量更新 CLI 参数契约。"""

import datetime as dt
from pathlib import Path

import pytest
import polars as pl

from quant.data.update import _require_open_a_share_date, build_parser, build_pipeline


def test_update_cli_parses_date_symbols_and_roots():
    args = build_parser().parse_args(
        [
            "--date",
            "2026-07-10",
            "--symbols",
            "000001.SZ",
            "00700.HK",
            "--data-root",
            "/tmp/quant-data",
            "--source",
            "baostock",
        ]
    )

    assert args.date == dt.date(2026, 7, 10)
    assert args.symbols == ["000001.SZ", "00700.HK"]
    assert args.data_root == Path("/tmp/quant-data")
    assert args.source == "baostock"


def test_update_cli_requires_symbols():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--date", "2026-07-10"])


def test_tushare_can_explicitly_disable_adjustment_factors(tmp_path: Path):
    pipeline = build_pipeline(
        "tushare", tmp_path / "data", tmp_path / "artifacts",
        use_adjustment_factors=False,
    )
    assert pipeline.factor_mapper is None
    assert pipeline.factor_store is None


def test_update_requires_open_clean_calendar(tmp_path: Path):
    calendar_path = (
        tmp_path / "clean" / "trade_calendar" / "market=SZ" / "data.parquet"
    )
    calendar_path.parent.mkdir(parents=True)
    pl.DataFrame(
        {"date": [dt.date(2026, 7, 10), dt.date(2026, 7, 11)], "is_open": [True, False]}
    ).write_parquet(calendar_path)

    _require_open_a_share_date(tmp_path, ["000001.SZ"], dt.date(2026, 7, 10))
    with pytest.raises(RuntimeError, match="休市日"):
        _require_open_a_share_date(tmp_path, ["000001.SZ"], dt.date(2026, 7, 11))
