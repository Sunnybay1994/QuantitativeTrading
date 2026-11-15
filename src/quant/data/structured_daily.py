"""One scheduled D2 capture plus observed IF/IC/IM daily quotes."""

import datetime as dt
import hashlib
import json
from pathlib import Path

from quant.data.structured_incremental import run as incremental
from quant.data.structured_futures import capture as futures


def run(*, config, data_root, output, as_of=None, resume=False):
    output = Path(output)
    structured = incremental(
        config=config, data_root=data_root, output=output, as_of=as_of, resume=resume
    )
    panel = {"status": "deferred", "reason": "structured capture yielded to capital path"}
    if (structured.get("time_budget_exhausted") or
            structured.get("elapsed_seconds", 0) >= structured.get("max_run_seconds", float('inf'))):
        panel = {"status": "deferred", "reason": "structured runtime budget exhausted"}
    elif structured["status"] != "deferred":
        try:
            folder = output / "futures"
            if (folder / "summary.json").is_file():
                panel = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
            else:
                panel = futures(
                    config=config,
                    data_root=data_root,
                    output=folder,
                    as_of=dt.date.fromisoformat(structured["as_of"]),
                )
        except Exception as exc:
            panel = dict(status="failed", error=f"{type(exc).__name__}: {exc}")
    status = (
        "deferred"
        if structured["status"] == "deferred"
        else "checked"
        if structured["status"] == "checked" and panel["status"] == "captured"
        else "partial"
    )
    receipt = dict(
        status=status,
        as_of=structured["as_of"],
        auto_trade=False,
        structured_status=structured["status"],
        futures=panel,
        structured_receipt=str(output / "summary.json"),
        structured_receipt_sha256=hashlib.sha256(
            (output / "summary.json").read_bytes()
        ).hexdigest(),
        scope="Data collection only; permission-limited sources remain partial; no trading or strategy admission.",
    )
    (output / "pipeline.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return receipt
