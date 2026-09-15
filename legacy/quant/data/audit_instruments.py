"""证券主表覆盖审计，重点确认 M2 所需核心 ETF。"""

import argparse
import json
from pathlib import Path
from typing import Sequence

import polars as pl

from quant.domain import InstrumentSchema


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="审计证券主表与核心 ETF 覆盖")
    parser.add_argument(
        "--required-symbols", nargs="+", default=["510300.SH", "159919.SZ"]
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    frames = []
    for market in ("SH", "SZ", "HK"):
        path = args.data_root / f"clean/instrument/market={market}/data.parquet"
        if not path.exists():
            raise FileNotFoundError(path)
        frames.append(pl.read_parquet(path))
    instruments = InstrumentSchema.validate(pl.concat(frames, how="vertical_relaxed"))
    counts = {
        f"{market}_{instrument_type}": count
        for market, instrument_type, count in instruments.group_by(
            "market", "instrument_type"
        ).len().iter_rows()
    }
    required = instruments.filter(pl.col("symbol").is_in(args.required_symbols))
    valid_required = set(
        required.filter(pl.col("instrument_type") == "ETF").get_column("symbol").to_list()
    )
    missing = sorted(set(args.required_symbols) - valid_required)
    report = {"counts": counts, "required_symbols": args.required_symbols, "missing": missing}
    output = args.artifact_root / "data_quality/instrument/coverage.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.json")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"report_path": str(output), **report}, ensure_ascii=False))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
