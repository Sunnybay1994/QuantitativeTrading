"""Build residual GP search labels for incremental_residual_ic_v1 (B1)."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import polars as pl
import tomllib

from quant.data.model_forecast_labels import residual_labels
from quant.factors.expressions import evaluate_expressions
from quant.factors.library import load_library


def alias_gp_terminals(panel: pl.DataFrame, expressions: dict[str, str]) -> pl.DataFrame:
    """N2 samples store PIT terminals as gp_<id>; library exprs use bare ids."""
    needed = {
        node.id
        for expr in expressions.values()
        for node in ast.walk(ast.parse(expr, mode="eval"))
        if isinstance(node, ast.Name)
    }
    aliases = [
        pl.col(f"gp_{name}").alias(name)
        for name in sorted(needed)
        if name not in panel.columns and f"gp_{name}" in panel.columns
    ]
    return panel.with_columns(aliases) if aliases else panel


def load_residual_controls(
    *,
    labels: pl.DataFrame,
    residual_cfg: dict,
    panel: pl.DataFrame,
) -> pl.DataFrame:
    """Assemble Q10 score + ngp expression scores + log_size + industry."""
    pred = pl.read_parquet(residual_cfg["q10_predictions"])
    score_col = residual_cfg.get("q10_score_column", "lightgbm")
    rename = {}
    if "ts_code" in pred.columns and "symbol" not in pred.columns:
        rename["ts_code"] = "symbol"
    if "date" in pred.columns and "trade_date" not in pred.columns:
        rename["date"] = "trade_date"
    if rename:
        pred = pred.rename(rename)
    if score_col not in pred.columns:
        raise ValueError(f"q10 predictions lack {score_col}: {pred.columns}")
    controls = pred.select("symbol", "trade_date", pl.col(score_col).alias("q10_score"))

    month_ends = labels["trade_date"].unique()
    monthly_panel = panel.filter(pl.col("trade_date").is_in(month_ends.implode()))
    library = {d.id: d for d in load_library(Path(residual_cfg["ngp_library"]))}
    ngp_names = [
        c for c in residual_cfg["control_columns"] if c not in ("q10_score", "log_size")
    ]
    exprs = {}
    for name in ngp_names:
        if name not in library:
            raise ValueError(f"ngp factor missing from library: {name}")
        exprs[name] = library[name].expr
    if exprs:
        monthly_panel = alias_gp_terminals(monthly_panel, exprs)
        scored = evaluate_expressions(monthly_panel, exprs)
        for name in ngp_names:
            controls = controls.join(
                scored.select("symbol", "trade_date", name),
                on=["symbol", "trade_date"],
                how="inner",
                validate="1:1",
            )

    if "total_market_value" in monthly_panel.columns:
        size = monthly_panel.select(
            "symbol",
            "trade_date",
            pl.when(pl.col("total_market_value") > 0)
            .then(pl.col("total_market_value").log())
            .otherwise(None)
            .alias("log_size"),
            "industry_l1",
        )
    elif "log_size" in monthly_panel.columns:
        size = monthly_panel.select("symbol", "trade_date", "log_size", "industry_l1")
    else:
        raise ValueError("panel lacks total_market_value/log_size for residual controls")
    return controls.join(size, on=["symbol", "trade_date"], how="inner", validate="1:1")


def apply_residual_search_labels(
    *,
    labels: pl.DataFrame,
    panel: pl.DataFrame,
    residual_cfg: dict,
    output: Path,
) -> pl.DataFrame:
    controls = load_residual_controls(labels=labels, residual_cfg=residual_cfg, panel=panel)
    resid = residual_labels(
        labels,
        controls,
        label_column=residual_cfg.get("label_column", "label"),
        control_columns=list(residual_cfg["control_columns"]),
        industry_column=residual_cfg.get("industry_column", "industry_l1"),
    )
    output.mkdir(parents=True, exist_ok=True)
    resid.write_parquet(output / "residual_labels.parquet")
    controls.write_parquet(output / "residual_controls.parquet")
    (output / "residual_config.json").write_text(
        json.dumps(residual_cfg, indent=2, default=str), encoding="utf-8"
    )
    return resid


def residual_spec_from_recipe(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))
