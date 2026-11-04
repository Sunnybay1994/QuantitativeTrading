"""情报扫描、原文验证与周报；候选不自动入队。"""

from __future__ import annotations

import argparse
import json
import tomllib
import datetime as dt
import hashlib
import math
from pathlib import Path
from typing import Any, Callable

from quant.core.paths import project_paths
from quant.factors.library import load_library
from quant.factors.search import canonical
from quant.intel.extract import extract_candidates
from quant.intel.sources import collect, iso_week

DEFAULT_CONFIG = Path("configs/research/intel.toml")


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _seen_path(week: str) -> Path:
    return project_paths().artifacts / "intel" / week / "seen.json"


def _load_seen(week: str) -> set[str]:
    path = _seen_path(week)
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return set()


def _digest(week: str, items: list[dict[str, Any]], accepted: list[dict[str, Any]],
            rejected: list[dict[str, Any]], queue_path: Path | None) -> Path:
    root = project_paths().artifacts / "intel" / week
    root.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# 情报周报 {week}",
        "",
        f"扫描 {len(items)} 条，合法候选 {len(accepted)}，表达式拒绝 {len(rejected)}。",
        "",
        "|标题|来源|机制一句话|可实现性|是否入队|",
        "|---|---|---|---:|---|",
    ]
    for row in items:
        linked = next((a for a in accepted if row["id"] in str(a.get("source_ref", ""))), None)
        mechanism = (linked or {}).get("rationale") or (row.get("summary") or "")[:80]
        feasibility = (linked or {}).get("feasibility", 1.0 if linked else 0.0)
        queued = "否"
        lines.append(
            f"|[{row['title'][:60]}]({row['url']})|{row['source']}|{mechanism.replace('|', '/')}|"
            f"{feasibility:.2f}|{queued}|"
        )
    if accepted:
        lines += ["", "## 有原文依据的来源候选（未入队）"]
        for row in accepted:
            lines.append(
                f"- `{row['id']}` `{row['expr']}` dir={row['direction']} "
                f"mechanism={(row.get('rationale') or '')[:80]}"
            )
            lines.append(f"  原文：{row['evidence_quote']}")
    if queue_path:
        lines += ["", f"队列文件：`{queue_path.as_posix()}`"]
    path = root / "digest.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "summary.json").write_text(
        json.dumps({
            "week": week,
            "items": len(items),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "queue": None if queue_path is None else str(queue_path),
            "auto_enqueue":False,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    (root/'candidates.json').write_text(json.dumps(accepted,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'rejected.json').write_text(json.dumps(rejected,ensure_ascii=False,indent=2),encoding='utf-8')
    return path


def run_intel(
    *,
    config_path: Path | None = None,
    extract: bool = True,
    dry_run: bool = False,
    getter: Callable[[str], str] | None = None,
    complete: Callable | None = None,
) -> dict[str, Any]:
    root = project_paths().root
    config = _load_toml(root / (config_path or DEFAULT_CONFIG))
    week = iso_week()
    if dry_run:
        # Do not write an empty digest over a real weekly product.
        return {"week": week, "items": 0, "accepted": 0, "rejected": 0,
                "digest": None, "queue": None, "dry_run": True}
    items = collect(config, getter=getter)
    seen = _load_seen(week)
    fresh = [row for row in items if row["id"] not in seen]
    library_root = Path(config.get("library", "configs/factors/library"))
    if not library_root.is_absolute():
        library_root = root / library_root
    existing = []
    library_ids: list[str] = []
    if library_root.exists():
        try:
            definitions = load_library(library_root)
        except ValueError:
            definitions = []
        existing = [canonical(item.expr) for item in definitions]
        library_ids = [item.id for item in definitions]
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    if extract and fresh:
        kwargs = {"existing_canonical": set(existing), "maximum": int(config.get("maximum_candidates", 8))}
        from quant.llm import complete_messages
        from quant.llm.ledger import append
        from quant.research.gp_hints import priced_usd
        call=complete or complete_messages
        def tracked(messages,settings):
            started=dt.datetime.now(dt.timezone.utc)
            directory=project_paths().artifacts/'intel'/week
            directory.mkdir(parents=True,exist_ok=True)
            receipt=directory/f"extraction_{started:%Y%m%dT%H%M%S_%f}.json"
            record={'status':'attempted','started_at':started.isoformat(),'messages':messages,'settings':settings}
            with receipt.open('x',encoding='utf-8') as handle:
                handle.write(json.dumps(record,ensure_ascii=False,default=str))
            try:
                response=call(messages,settings)
            except Exception as exc:
                record.update(status='request_failed',error_type=type(exc).__name__)
                if getattr(exc,'code','') not in ('connect_failed','monthly_budget_exhausted'):
                    append({'task':'intel_extract','usd':settings['reserve_usd'],'estimated':True,
                        'unknown_charge':True,'artifact':str(receipt)},root/'artifacts/research/llm_ledger',now=started)
                receipt.write_text(json.dumps(record,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
                raise
            usd,estimated=priced_usd(response,Path(__file__).resolve().parents[3]/'configs/llm/pricing.toml')
            unknown=usd is None or not math.isfinite(usd) or usd<=0
            usd=settings['reserve_usd'] if unknown else usd
            record.update(status='responded',response=response,usd=usd,estimated=estimated or unknown,unknown_charge=unknown)
            receipt.write_text(json.dumps(record,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
            append({'task':'intel_extract','usd':usd,'estimated':estimated or unknown,'unknown_charge':unknown,
                'artifact':str(receipt),'artifact_sha256':hashlib.sha256(receipt.read_bytes()).hexdigest(),
                'usage':response.get('usage')},root/'artifacts/research/llm_ledger',now=started)
            return response
        kwargs["complete"] = tracked
        kwargs["library_ids"] = library_ids
        accepted, rejected = extract_candidates(fresh, **kwargs)
    queue_path = None
    digest = _digest(week, fresh, accepted, rejected, queue_path)
    seen_path = _seen_path(week)
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(sorted(seen | {row["id"] for row in fresh})), encoding="utf-8")
    return {
        "week": week,
        "items": len(fresh),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "digest": str(digest),
        "queue": None if queue_path is None else str(queue_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quant intel", description="扫描公开研究并核对来源；仅输出digest，不自动入队")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--no-extract", action="store_true", help="只抓取摘要，不调用 LLM")
    parser.add_argument("--dry-run", action="store_true", help="不抓取、不调用LLM、不覆盖已有产物")
    args = parser.parse_args(argv)
    result = run_intel(config_path=args.config, extract=not args.no_extract, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
