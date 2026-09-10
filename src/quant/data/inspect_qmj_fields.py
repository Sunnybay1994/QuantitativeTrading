"""Inspect local financial inputs needed before preregistering QMJ research."""

import argparse
import datetime as dt
import json
from pathlib import Path

import polars as pl

from quant.data.financial_pit import select_financial_revisions_as_of

FIELDS = {
    "income": ("n_income", "n_income_attr_p", "revenue", "oper_cost", "ebit", "ebitda"),
    "cashflow": ("n_cashflow_act", "depr_fa_coga_dpba", "amort_intang_assets",
                 "lt_amort_deferred_exp", "c_pay_acq_const_fiolta", "free_cashflow"),
    "balancesheet": ("total_assets", "total_hldr_eqy_exc_min_int", "total_cur_assets",
                     "total_cur_liab", "money_cap", "st_borr", "lt_borr", "taxes_payable",
                     "non_cur_liab_due_1y", "bond_payable", "minority_int", "total_share"),
}


def inspect_fields(*, data_root: Path, snapshot: str, symbols: list[str], as_of: dt.date) -> dict:
    """Count finite published observations; these are coverage, not PIT factor values."""
    if not snapshot or Path(snapshot).name != snapshot or snapshot in (".", ".."):
        raise ValueError("Invalid snapshot")
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("Invalid symbol pool")
    tables = {}
    for table, fields in FIELDS.items():
        scan = pl.scan_parquet(data_root / "clean/tushare_financials" / snapshot / f"{table}.parquet")
        schema = scan.collect_schema()
        available = [f for f in fields if f in schema]
        frame = scan.filter(
            pl.col("symbol").is_in(symbols) & (pl.col("available_date") < as_of)
            & (pl.col("end_date") >= dt.date(2017, 1, 1))
            & (pl.col("report_type") == "1") & (pl.col("comp_type") == "1")
        ).select("symbol", "end_date", "source_file", *available).collect()
        counts = []
        for field in fields:
            valid = frame.filter(pl.col(field).is_finite()) if field in available else frame.head(0)
            counts.append({"field": field, "column_present": field in available,
                           "finite_rows": valid.height, "symbols": valid["symbol"].n_unique(),
                           "symbol_periods": valid.select("symbol", "end_date").unique().height,
                           "report_months": valid.group_by(pl.col("end_date").dt.month().alias("month"))
                           .len().sort("month").to_dicts(),
                           "years": valid.group_by(pl.col("end_date").dt.year().alias("year"))
                           .len().sort("year").to_dicts()})
        # A deterministic raw sample distinguishes omitted columns from normalization loss.
        sample = sorted(frame["source_file"].drop_nulls().unique().to_list())[:3]
        raw_checks = []
        for source in sample:
            raw = pl.read_parquet(source)
            raw_checks.append({"path": source, "rows": raw.height,
                               "fields": {f: {"column_present": f in raw.columns,
                                              "finite_rows": raw.select(pl.col(f).cast(pl.Float64, strict=False)
                                              .is_finite().sum()).item() if f in raw.columns else 0}
                                          for f in fields}})
        tables[table] = {"rows": frame.height, "symbols": frame["symbol"].n_unique(),
                         "fields": counts, "raw_samples": raw_checks}
    return {"snapshot": snapshot, "as_of": str(as_of), "pool_size": len(symbols),
            "period_start": "2017-01-01", "report_type": "1", "company_type": "1",
            "meaning": "Finite revision rows; not conflict-resolved PIT or rolling-factor coverage.",
            "tables": tables}


def annual_cfoa_input_coverage(*, data_root: Path, snapshot: str, symbols: list[str],
                               signals: list[dt.date]) -> list[dict]:
    """Require current annual income and matching cash/balance plus prior-year WC."""
    required = {
        "income": ["n_income"],
        "cashflow": ["depr_fa_coga_dpba", "c_pay_acq_const_fiolta"],
        "balancesheet": ["total_assets", "total_cur_assets", "total_cur_liab",
                         "money_cap", "st_borr", "taxes_payable"],
    }
    structural = ["symbol", "ann_date", "f_ann_date", "available_date", "end_date",
                  "report_type", "comp_type", "update_flag"]
    histories = {table: pl.scan_parquet(data_root / "clean/tushare_financials" / snapshot
                                       / f"{table}.parquet").filter(
        pl.col("symbol").is_in(symbols) & (pl.col("report_type") == "1")
        & (pl.col("comp_type") == "1") & (pl.col("end_date").dt.month() == 12)
        & (pl.col("end_date") >= dt.date(2017, 1, 1))
    ).select(*structural, *fields).collect() for table, fields in required.items()}
    output = []
    for signal in signals:
        selected = {table: select_financial_revisions_as_of(
            histories[table], dataset=table, as_of=signal).selected
            for table in ("income", "cashflow", "balancesheet")}
        key = ["symbol", "end_date"]
        latest = selected["income"].sort(key).group_by("symbol", maintain_order=True).tail(1)
        current = latest.select(*key, "n_income").join(
            selected["cashflow"].select(*key, *required["cashflow"]), on=key, how="left"
        ).join(selected["balancesheet"].select(*key, *required["balancesheet"]), on=key, how="left")
        wc = required["balancesheet"][1:]
        prior = selected["balancesheet"].select(
            "symbol", pl.col("end_date").dt.offset_by("1y"),
            *[pl.col(f).alias("prior_" + f) for f in wc])
        current = current.join(prior, on=key, how="left")
        fields = [f for fields in required.values() for f in fields] + ["prior_" + f for f in wc]
        valid = current.filter(pl.all_horizontal(pl.col(f).is_finite() for f in fields)
                               & (pl.col("total_assets") > 0))
        output.append({"as_of": str(signal), "latest_income_symbols": current.height,
                       "complete_annual_cfoa_symbols": valid.height,
                       "complete_within_18_months": valid.filter(
                           pl.col("end_date") >= pl.lit(signal).dt.offset_by("-18mo")).height,
                       "report_years": valid.group_by(pl.col("end_date").dt.year().alias("year"))
                       .len().sort("year").to_dicts()})
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--pool-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--signal-targets", type=Path)
    args = parser.parse_args()
    symbols = json.loads(args.pool_run.read_text(encoding="utf-8"))["candidate_symbols"]
    report = inspect_fields(data_root=Path("data"), snapshot=args.snapshot,
                            symbols=symbols, as_of=dt.date(2026, 9, 8))
    if args.signal_targets:
        signals = sorted(pl.read_parquet(args.signal_targets)["as_of"].unique().to_list())
        report["annual_cfoa_inputs"] = annual_cfoa_input_coverage(
            data_root=Path("data"), snapshot=args.snapshot, symbols=symbols, signals=signals)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2, default=str)
    print(json.dumps({k: [{"field": f["field"], "finite_rows": f["finite_rows"],
                          "symbols": f["symbols"]} for f in v["fields"]]
                      for k, v in report["tables"].items()}))


if __name__ == "__main__":
    main()
