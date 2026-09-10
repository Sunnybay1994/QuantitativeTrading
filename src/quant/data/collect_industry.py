"""Collect Shenwan taxonomy and dated memberships; raw only, not PIT publication."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import polars as pl

from quant.data.connectors.tushare import TushareConnector


def collect_industry(
    root: Path,
    *,
    connector: TushareConnector | None = None,
    pause_seconds: float = 1.3,
    page_size: int = 2000,
    member_api: str = "index_member",
) -> dict[str, int | str]:
    """Resume saved pages without replacing raw; fetch both current and retired members."""
    if page_size <= 0 or pause_seconds < 0:
        raise ValueError("Invalid page size or request interval")
    if member_api not in {"index_member", "index_member_all"}:
        raise ValueError("Unsupported industry membership API")
    root.mkdir(parents=True, exist_ok=True)
    client = connector or TushareConnector(config_path=Path("configs/tushare.local.toml"))
    requests = 0

    def fetch(path: Path, api: str, **params: str) -> pl.DataFrame:
        nonlocal requests
        if path.exists():
            return pl.read_parquet(path)
        if requests:
            time.sleep(pause_seconds)
        for attempt in range(3):
            requests += 1
            try:
                frame = client.query_raw(api, **params)
                break
            except Exception:
                if attempt == 2:
                    raise RuntimeError(f"Industry request failed after 3 attempts: {api} {params}") from None
                time.sleep(pause_seconds * (attempt + 2))
        with path.open("xb") as stream:
            frame.write_parquet(stream)
        return frame

    codes: set[str] = set()
    taxonomy_rows = 0
    for version in ("SW2014", "SW2021"):
        for level in ("L1", "L2", "L3"):
            frame = fetch(
                root / f"index_classify_{level}_{version}.parquet",
                "index_classify", level=level, src=version,
            )
            if frame.is_empty():
                raise ValueError(f"Missing taxonomy: {version} {level}")
            taxonomy_rows += frame.height
            if level == "L3" and (member_api == "index_member" or version == "SW2021"):
                codes.update(frame["index_code"].to_list())

    member_rows = 0
    for number, code in enumerate(sorted(codes), 1):
        for flag in ("Y", "N"):
            offset = 0
            previous: pl.DataFrame | None = None
            while True:
                frame = fetch(
                    root / f"{member_api}_{code.replace('.', '_')}_{flag}_{offset}.parquet",
                    member_api, **{"index_code" if member_api == "index_member" else "l3_code": code}, is_new=flag,
                    limit=str(page_size), offset=str(offset),
                )
                if previous is not None and frame.equals(previous):
                    raise ValueError(f"Supplier repeated a full page: {code} {flag}")
                member_rows += frame.height
                if frame.height < page_size:
                    break
                previous = frame
                offset += frame.height
        if number % 25 == 0 or number == len(codes):
            print(json.dumps({"industries_done": number, "industries": len(codes),
                              "member_rows": member_rows}), flush=True)
    return {"raw_root": str(root), "member_api": member_api, "taxonomy_rows": taxonomy_rows,
            "industries": len(codes), "member_rows": member_rows,
            "network_requests": requests}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, help="Existing run resumes saved pages")
    parser.add_argument("--member-api", choices=("index_member", "index_member_all"), default="index_member")
    args = parser.parse_args()
    root = args.raw_root or (
        Path("data/raw/tushare/industry") / dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    )
    print(json.dumps({"raw_root": str(root)}), flush=True)
    print(json.dumps(collect_industry(root, member_api=args.member_api)), flush=True)


if __name__ == "__main__":
    main()
