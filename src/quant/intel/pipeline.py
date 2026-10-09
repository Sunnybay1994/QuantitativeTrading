"""情报扫描 → 去重 →（可选）LLM 提炼 → 写入因子队列与周报。"""

from __future__ import annotations

import argparse
import json
import tomllib
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


def _write_queue(candidates: list[dict[str, Any]], queue: Path, week: str) -> Path | None:
    if not candidates:
        return None
    queue.mkdir(parents=True, exist_ok=True)
    path = queue / f"intel_{week.replace('-', '').lower()}.toml"
    lines = []
    for row in candidates:
        lines.append("[[factors]]")
        for key in ("id", "expr", "family", "direction", "source_ref"):
            lines.append(f"{key} = {json.dumps(row[key], ensure_ascii=False)}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


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
        queued = "是" if linked else "否"
        lines.append(
            f"|[{row['title'][:60]}]({row['url']})|{row['source']}|{mechanism.replace('|', '/')}|"
            f"{feasibility:.2f}|{queued}|"
        )
    if accepted:
        lines += ["", "## 写入队列的候选"]
        for row in accepted:
            lines.append(
                f"- `{row['id']}` `{row['expr']}` dir={row['direction']} "
                f"mechanism={(row.get('rationale') or '')[:80]}"
            )
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
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
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
        digest = _digest(week, [], [], [], None)
        return {"week": week, "items": 0, "accepted": 0, "rejected": 0,
                "digest": str(digest), "queue": None, "dry_run": True}
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
        if complete is not None:
            kwargs["complete"] = complete
        kwargs["library_ids"] = library_ids
        accepted, rejected = extract_candidates(fresh, **kwargs)
    queue = Path(config.get("queue", "configs/factors/queue"))
    if not queue.is_absolute():
        queue = root / queue
    queue_path = _write_queue(accepted, queue, week)
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
    parser = argparse.ArgumentParser(prog="quant intel", description="扫描公开研究并写入因子队列")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--no-extract", action="store_true", help="只抓取摘要，不调用 LLM")
    parser.add_argument("--dry-run", action="store_true", help="不抓取、不调用 LLM，只写空 digest 骨架")
    args = parser.parse_args(argv)
    result = run_intel(config_path=args.config, extract=not args.no_extract, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
