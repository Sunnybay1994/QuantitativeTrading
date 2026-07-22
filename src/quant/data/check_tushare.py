"""不泄露 Token 的 Tushare Pro 连通性与 2000 积分基础权限检查。"""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Sequence

from quant.data.connectors import TushareConnector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查 Tushare Pro 基础权限")
    parser.add_argument("--date", type=dt.date.fromisoformat, default=dt.date.today())
    parser.add_argument("--config", type=Path, default=Path("configs/tushare.local.toml"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    connector = TushareConnector(config_path=args.config)
    calendar = connector.fetch_trade_calendar("SH", args.date, args.date)
    instruments = connector.fetch_instruments("SH")
    print(json.dumps({
        "source": "tushare", "date": args.date.isoformat(),
        "trade_calendar_rows": calendar.height,
        "sh_instrument_rows": instruments.height,
        "token": "<redacted>",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
