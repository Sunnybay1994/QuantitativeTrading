"""Read published financial revision histories for point-in-time factor selection."""

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from quant.data.financial_clean import FinancialFactorDataset


@dataclass(frozen=True)
class TushareFinancialHistoryQuery:
    snapshot_id: str
    dataset: FinancialFactorDataset
    start_period: dt.date
    end_period: dt.date
    symbols: tuple[str, ...]
    threads: int = 2
    extra_fields: tuple[str, ...] = ()


def read_tushare_financial_history(*, data_root: Path, query: TushareFinancialHistoryQuery) -> pl.DataFrame:
    """Return all revisions; the PIT selector enforces announcement lag and conflicts."""
    if (not query.snapshot_id or Path(query.snapshot_id).name != query.snapshot_id
            or query.snapshot_id in (".", "..")
            or query.dataset not in ("income", "balancesheet", "cashflow")
            or query.start_period > query.end_period or not query.symbols):
        raise ValueError("Invalid financial history query")
    economics = {"income": ["n_income", "n_income_attr_p"],
                 "balancesheet": ["total_assets", "total_hldr_eqy_exc_min_int"],
                 "cashflow": ["n_cashflow_act"]}[query.dataset]
    allowed_extra = ({"revenue", "oper_cost", "ebit"} if query.dataset == "income"
                     else {"total_liab", "total_cur_assets", "total_cur_liab", "money_cap", "st_borr", "taxes_payable", "surplus_rese", "undistr_porfit"}
                     if query.dataset == "balancesheet" else {"depr_fa_coga_dpba", "c_pay_acq_const_fiolta"})
    if len(set(query.extra_fields)) != len(query.extra_fields) or not set(query.extra_fields) <= allowed_extra:
        raise ValueError("Unsupported financial fields")
    economics.extend(query.extra_fields)
    path = data_root / "clean/tushare_financials" / query.snapshot_id / f"{query.dataset}.parquet"
    return pl.scan_parquet(path).filter(
        pl.col("symbol").is_in(list(query.symbols))
        & pl.col("end_date").is_between(query.start_period, query.end_period)
    ).select("symbol", "ann_date", "f_ann_date", "available_date", "end_date", "report_type",
             "comp_type", "update_flag", *economics, "source").sort(
                 "symbol", "end_date", "available_date", "report_type", "comp_type", "update_flag", "ann_date"
             ).collect()


def read_debt_ebitda_history(
    *, data_root: Path, snapshot_id: str, symbols: tuple[str, ...],
    start_period: dt.date, end_period: dt.date,
) -> pl.DataFrame:
    """Read published provider debt and EBITDA together, retaining indicator revisions."""
    if (not snapshot_id or Path(snapshot_id).name != snapshot_id or snapshot_id in ('.', '..')
        or not symbols or start_period > end_period):
        raise ValueError('Invalid debt/EBITDA history query')
    path = data_root / 'clean/tushare_financials' / snapshot_id / 'fina_indicator.parquet'
    return pl.scan_parquet(path).filter(pl.col('symbol').is_in(symbols)
        & pl.col('end_date').is_between(start_period, end_period)).select(
            'symbol', 'ann_date', 'available_date', 'end_date', 'interestdebt', 'ebitda', 'source'
        ).sort('symbol', 'end_date', 'available_date').collect()
