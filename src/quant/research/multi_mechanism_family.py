"""S1: four frozen equal-z mechanism portfolios. Weights are not fit to the replay."""

from __future__ import annotations

import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

DEFAULT_CONFIG = Path("configs/research/multi_mechanism_family_v1.toml")


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    spec = tomllib.loads(path.read_text(encoding="utf-8"))
    if spec.get("auto_trade") is not False:
        raise ValueError("multi_mechanism_family requires auto_trade=false")
    if [row["id"] for row in spec["members"]] != ["M1", "M2", "M3", "M4"]:
        raise ValueError("S1 members are frozen as M1 M2 M3 M4")
    if len(spec["factors"]) != 3:
        raise ValueError("S1 uses exactly three mechanism factors")
    return spec


def _z(frame: pl.DataFrame, column: str, alias: str, direction: int) -> pl.DataFrame:
    sigma = pl.col(column).std().over("trade_date")
    return frame.with_columns(
        pl.when(sigma > 0)
        .then(direction * (pl.col(column) - pl.col(column).mean().over("trade_date")) / sigma)
        .otherwise(0.0)
        .alias(alias)
    )


def build_scores(spec: dict, *, include_sue: bool, statistics: Path | None = None,
                 predictions: Path | None = None) -> pl.DataFrame:
    """Equal-weight z. Primary variant column is used as published; direction is the frozen sign."""
    stats = statistics or Path(spec["statistics"])
    keys = ["symbol", "trade_date"]
    panel = None
    for factor in spec["factors"]:
        path = stats / "factors" / factor["id"] / "monthly_scores.parquet"
        frame = pl.read_parquet(path).select(*keys, pl.col(spec["score_variant"]).alias(factor["id"]))
        panel = frame if panel is None else panel.join(frame, on=keys, how="inner", validate="1:1")
    assert panel is not None
    pieces = []
    for factor in spec["factors"]:
        panel = _z(panel, factor["id"], f"{factor['id']}_z", int(factor["direction"]))
        pieces.append(pl.col(f"{factor['id']}_z"))
    if include_sue:
        pred = pl.read_parquet((predictions or Path(spec["predictions"])) / "monthly_predictions.parquet")
        sue = pred.select(*keys, pl.col(spec["sue_column"]).alias("sue"))
        panel = panel.join(sue, on=keys, how="inner", validate="1:1")
        panel = _z(panel, "sue", "sue_z", 1)
        pieces.append(pl.col("sue_z"))
    score = pl.sum_horizontal(pieces) / len(pieces)
    return panel.select(
        "symbol",
        "trade_date",
        score.alias(spec["method"]),
        pl.lit(None).cast(pl.Int32).alias("test_year"),
    )


def _annotate_report(folder: Path, result: dict) -> None:
    report = folder / "report.md"
    delta = result.get("vs_q10_2x_excess_pp")
    diagnostics = result.get("diagnostics") or {}
    extra = [
        "",
        f"vs Q10 同窗 2× 超额差 = {delta} pp",
        f"rolling12_excess_min={diagnostics.get('rolling12_excess_min')}",
        f"rolling24_excess={diagnostics.get('rolling24_excess')}",
        f"best_month_share={diagnostics.get('best_month_share')}",
        f"monthly_hit_rate={diagnostics.get('monthly_hit_rate')}",
        "",
    ]
    report.write_text(report.read_text(encoding="utf-8") + "\n".join(extra), encoding="utf-8")


def run(*, config: Path = DEFAULT_CONFIG, output: Path | None = None,
        data_root: Path = Path("data"), resume: bool = True) -> dict:
    from quant.research.q10_sizing import run_cell

    spec = load_config(config)
    root = output or Path(f"artifacts/portfolio/multi_mechanism_v1_{dt.date.today():%Y%m%d}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_bytes(config.read_bytes())
    results = []
    for member in spec["members"]:
        months = tuple(member["execution_months"]) if member.get("execution_months") else None
        scores = build_scores(spec, include_sue=bool(member["include_sue"]))
        cell = {
            "cell_id": member["id"],
            "budget": float(member["budget"]),
            "top_k": int(member["top_k"]),
            "size_neutral": bool(member["size_neutral"]),
        }
        result = run_cell(
            spec=spec,
            cell=cell,
            output=root,
            data_root=data_root,
            resume=resume,
            score_frame=scores,
            execution_months=months,
            research_id=f"multi_mechanism_v1_{member['id']}",
        )
        _annotate_report(root / member["id"], result)
        results.append({"id": member["id"], "conclusion": result.get("conclusion"),
                        "vs_q10_2x_excess_pp": result.get("vs_q10_2x_excess_pp"),
                        "max_drawdown_2x": result.get("max_drawdown_2x")})
    summary = {"output": str(root), "members": results}
    (root / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()
    print(json.dumps(run(config=args.config, output=args.output, data_root=args.data_root),
                     ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
