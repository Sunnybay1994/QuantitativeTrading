"""Daily three-ETF inputs for the preregistered B20 forward observation."""

import datetime as dt
import json
import time
from pathlib import Path

from quant.data.connectors.tushare import TushareConnector
from quant.data.etf_limits import refresh_limits
from quant.data.publish_cross_asset_etfs import SYMBOLS, publish, read_cross_asset_etfs
from quant.data.storage import RawStore


def refresh_cross_asset_forward(*, data_root: Path, end: dt.date) -> dict:
    """Keep each completed daily view and every supplier response as a new artifact."""
    name = f"b20_forward_{end:%Y%m%d}"
    root = data_root / "clean/etf_cross_asset" / name
    if (root / "summary.json").exists():
        frames = read_cross_asset_etfs(data_root, name)
        if frames["bars"]["trade_date"].max() != end:
            raise ValueError("Forward data latest date differs")
        refresh_limits(data_root=data_root, symbols=list(SYMBOLS), end=end, start=dt.date(2026, 9, 9))
        return {"snapshot": name, "new_snapshot": False}
    connector = TushareConnector(config_path=Path("configs/tushare.local.toml"))
    captured = []
    for symbol in SYMBOLS[1:]:
        for dataset, params in (
            ("fund_daily", {"ts_code": symbol, "start_date": "20230101", "end_date": end.strftime("%Y%m%d")}),
            ("fund_basic", {"ts_code": symbol, "market": "E"}),
            ("fund_div", {"ts_code": symbol}),
        ):
            try:
                raw = connector.query_raw(dataset, **params)
            except Exception:
                raise RuntimeError(f"Cross-asset {dataset} request failed for {symbol}") from None
            record = RawStore(data_root / "raw").write(source="tushare", table=dataset, frame=raw, parameters=params)
            captured.append({"symbol": symbol, "dataset": dataset, "raw_path": str(record.data_path)})
            time.sleep(.4)
    folder = Path("artifacts/data_quality/cross_asset_forward")
    folder.mkdir(parents=True, exist_ok=True)
    capture = folder / f"{end}_{dt.datetime.now():%H%M%S%f}.json"
    capture.write_text(json.dumps(captured, indent=2), encoding="utf-8")
    result = publish(data_root=data_root, capture=capture, name=name, start=dt.date(2023, 1, 1), end=end)
    refresh_limits(data_root=data_root, symbols=list(SYMBOLS), end=end, start=dt.date(2026, 9, 9))
    return {"snapshot": name, "new_snapshot": True, "rows": result["rows"]}
