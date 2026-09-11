"""Append correction announcements to raw and report financial-title candidates."""

import argparse
import datetime as dt
import json
import re
from pathlib import Path

import polars as pl

from quant.data.connectors.cninfo_announcements import correction_pages
from quant.data.storage import RawStore

_FINANCIAL_TITLE = re.compile(r"年度报告|半年度报告|季度报告|财务报表|财务报告")


def collect(start: dt.date, end: dt.date, data_root: Path) -> dict[str, object]:
    """Keep all source rows; only classify titles after preserving the raw response."""
    store = RawStore(data_root / "raw")
    paths: list[str] = []
    candidates: list[dict[str, object]] = []
    count = 0
    for parameters, rows in correction_pages(start, end):
        raw = store.write(
            source="cninfo", table="announcement_corrections", parameters=parameters,
            frame=pl.from_dicts(rows, infer_schema_length=None) if rows else pl.DataFrame(),
        )
        paths.append(str(raw.data_path))
        count += len(rows)
        for row in rows:
            title = re.sub(r"<[^>]*>", "", str(row.get("announcementTitle") or ""))
            if _FINANCIAL_TITLE.search(title):
                candidates.append({
                    "code": row.get("secCode"), "title": title,
                    "announcement_id": row.get("announcementId"),
                    "announcement_time": row.get("announcementTime"),
                    "document_path": row.get("adjunctUrl"),
                })
    return {"start": str(start), "end": str(end), "rows": count,
            "raw_paths": paths, "financial_title_candidates": candidates}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--to", dest="end", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    print(json.dumps(collect(args.start, args.end, args.data_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
