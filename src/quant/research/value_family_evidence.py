"""Read saved accounts and expose finite-sample holdings/accounting diagnostics."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import polars as pl


class Evidence:
    def __init__(self):
        self.sources = {}

    def track(self, path: Path) -> Path:
        key = path.as_posix()
        if key not in self.sources:
            self.sources[key] = {"path": key, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
        return path

    def json(self, path: Path):
        return json.loads(self.track(path).read_text(encoding="utf-8"))

    def parquet(self, path: Path, **kwargs):
        return pl.read_parquet(self.track(path), **kwargs)

    def verify(self):
        bad = [x["path"] for x in self.sources.values() if hashlib.sha256(Path(x["path"]).read_bytes()).hexdigest() != x["sha256"]]
        if bad:
            raise ValueError(f"Source changed: {bad}")


def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def save(path: Path, frame: pl.DataFrame):
    keys = [c for c in ["account", "factor", "variant", "cost", "reference", "year", "date", "symbol", "reason"] if c in frame.columns]
    if keys:
        frame = frame.sort(keys)
    frame.write_parquet(path.with_suffix(".parquet"))
    if not any(isinstance(t, (pl.Struct, pl.List)) for t in frame.schema.values()):
        frame.write_csv(path.with_suffix(".csv"))


def read_account(ev: Evidence, root: Path, identity: dict, snapshot_years: list[int]) -> dict:
    navs, trades, rejections, snapshots, checks = [], [], [], {}, []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not folder.name.isdigit():
            continue
        year = int(folder.name)
        navs.append(ev.parquet(folder / "nav.parquet"))
        trades.append(ev.parquet(folder / "trades.parquet"))
        rejections.append(ev.parquet(folder / "rejections.parquet"))
        if year in snapshot_years:
            state = ev.json(folder / "account.json")["account"]
            date = dt.date.fromisoformat(state["date"])
            ending = navs[-1].filter(pl.col("date") == date).row(0, named=True)
            rows = [{"symbol": name, "quantity": x["quantity"], "mark_price": x["mark_price"],
                     "value": x["quantity"] * x["mark_price"]} for name, x in state["holdings"].items()]
            market_value = sum(x["value"] for x in rows)
            discrepancy = market_value - ending["market_value"]
            if abs(discrepancy) > max(1e-6, ending["equity"] * 1e-10):
                raise ValueError(f"Saved holdings do not match NAV: {root}, {year}: {discrepancy}")
            checks.append({**identity, "year": year, "date": date, "market_value_error": discrepancy,
                "positions": len(rows), "equity": ending["equity"], "market_value": ending["market_value"]})
            frame = pl.DataFrame(rows, schema={"symbol": pl.String, "quantity": pl.Float64, "mark_price": pl.Float64, "value": pl.Float64}, strict=False)
            snapshots[year] = {"date": date, "equity": ending["equity"], "frame": frame,
                               "restricted_shares": state.get("restricted_shares", []), "state": state}
    nav = pl.concat(navs, how="diagonal_relaxed").sort("date")
    if nav["date"].n_unique() != nav.height or not nav["unit_nav"].is_finite().all():
        raise ValueError("Invalid saved NAV sequence")
    return {"identity": identity, "nav": nav, "trades": pl.concat(trades, how="diagonal_relaxed"),
            "rejections": pl.concat(rejections, how="diagonal_relaxed"), "snapshots": snapshots, "checks": checks}


def returns(nav: pl.DataFrame, start: dt.date, end: dt.date) -> pl.DataFrame:
    return nav.sort("date").with_columns((pl.col("unit_nav") / pl.col("unit_nav").shift(1).fill_null(1.) - 1).alias("return"),
        pl.col("equity").shift(1).fill_null(1e6).alias("prior_equity") if "equity" in nav.columns else pl.lit(None).alias("prior_equity")
    ).filter(pl.col("date").is_between(start, end))


def annual_security_bridge(account: dict, years: list[int]) -> tuple[list[dict], list[dict]]:
    """Exact book/trade cash-flow bridge, NOT total-return security attribution.

    Without daily entitlement holdings, cash dividends and corporate cash flows
    are unallocated. Quantity consistency excludes unexplained share changes.
    """
    rows, totals = [], []
    for year in years:
        if year not in account["snapshots"] or year - 1 not in account["snapshots"]:
            continue
        before, after = account["snapshots"][year - 1], account["snapshots"][year]
        first, last = before["date"], after["date"]
        tr = account["trades"].filter((pl.col("date") > first) & (pl.col("date") <= last))
        flows = tr.group_by("symbol").agg(
            pl.when(pl.col("side") == "BUY").then(pl.col("quantity")).otherwise(-pl.col("quantity")).sum().alias("net_quantity"),
            pl.when(pl.col("side") == "SELL").then(pl.col("notional")).otherwise(-pl.col("notional")).sum().alias("net_trade_cash"),
            pl.col("fee").sum().alias("fees"))
        frame = before["frame"].select("symbol", pl.col("quantity").alias("begin_quantity"), pl.col("value").alias("begin_value")).join(
            after["frame"].select("symbol", pl.col("quantity").alias("end_quantity"), pl.col("value").alias("end_value")),
            on="symbol", how="full", coalesce=True).join(flows, on="symbol", how="full", coalesce=True).fill_null(0.)
        frame = frame.with_columns((pl.col("end_quantity") - pl.col("begin_quantity") - pl.col("net_quantity")).alias("unexplained_quantity"),
            (pl.col("end_value") - pl.col("begin_value") + pl.col("net_trade_cash") - pl.col("fees")).alias("mark_trade_bridge_cny"))
        equity_gain = after["equity"] - before["equity"]
        residual = equity_gain - frame["mark_trade_bridge_cny"].sum()
        frame = frame.with_columns((pl.col("unexplained_quantity").abs() < 1e-8).alias("quantity_consistent"),
            (pl.col("mark_trade_bridge_cny") / before["equity"]).alias("bridge_on_begin_equity"))
        for row in frame.iter_rows(named=True):
            rows.append({**account["identity"], "year": year, **row})
        clean = frame.filter(pl.col("quantity_consistent"))
        positive = clean.filter(pl.col("mark_trade_bridge_cny") > 0).sort("mark_trade_bridge_cny", descending=True)
        negative = clean.filter(pl.col("mark_trade_bridge_cny") < 0).sort("mark_trade_bridge_cny")
        plus, minus = positive["mark_trade_bridge_cny"].sum(), -negative["mark_trade_bridge_cny"].sum()
        all_abs = frame["mark_trade_bridge_cny"].abs().sum()
        totals.append({**account["identity"], "year": year, "begin_equity": before["equity"], "equity_gain": equity_gain,
            "bridge_sum": frame["mark_trade_bridge_cny"].sum(), "unallocated_distributions_and_other_cash_cny": residual,
            "unallocated_on_begin_equity": residual / before["equity"],
            "quantity_inconsistent_symbols": frame.filter(~pl.col("quantity_consistent")).height,
            "consistent_absolute_bridge_fraction": clean["mark_trade_bridge_cny"].abs().sum() / all_abs if all_abs else None,
            "top5_positive_bridge_share": positive.head(5)["mark_trade_bridge_cny"].sum() / plus if plus else None,
            "top5_negative_bridge_share": -negative.head(5)["mark_trade_bridge_cny"].sum() / minus if minus else None,
            "reconciliation_error_cny": equity_gain - frame["mark_trade_bridge_cny"].sum() - residual})
    return rows, totals
