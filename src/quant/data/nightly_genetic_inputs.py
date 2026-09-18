"""Daily published terminals for the bounded nightly GP training sample."""
import datetime as dt
import json
from pathlib import Path

import polars as pl

from quant.data.factor_panels import available_sessions, read_factor_inputs, read_factor_industry
from quant.data.genetic_factor_inputs import read_genetic_panel


def latest_month_end(data_root: Path, today: dt.date) -> dt.date:
    """Target the latest completed month, never silently shrink to stale inputs."""
    previous=today.replace(day=1)-dt.timedelta(days=1)
    dates=available_sessions(data_root,previous)
    if not dates or dates[-1].month!=previous.month or dates[-1].year!=previous.year:
        raise ValueError(f'Local exchange calendar lacks completed month {previous:%Y-%m}')
    return dates[-1]


def require_execution_coverage(data_root: Path, snapshot: str, as_of: dt.date) -> None:
    folder=data_root/'clean/stock_execution'/snapshot
    limits=pl.scan_parquet(folder/'limits.parquet').select(pl.col('trade_date').max()).collect().item()
    if limits is None or limits<as_of:
        raise ValueError(f'Execution snapshot {snapshot} ends {limits}; requires {as_of}. Refresh inputs before retry.')


def read_raw_monthly(*,data_root: Path,statistics: Path,factors: list[str],start: dt.date,end: dt.date) -> pl.DataFrame:
    labels=read_genetic_panel(data_root=data_root,statistics=[statistics],factors=[],start=start,end=end)
    for factor in factors:
        paths=[data_root/'factors'/factor/f'year={year}'/'data.parquet' for year in range(start.year,end.year+1)]
        paths=[p for p in paths if p.exists()]
        if not paths:
            labels=labels.with_columns(pl.lit(None,dtype=pl.Float64).alias(factor))
            continue
        values=pl.scan_parquet(paths).filter(pl.col('trade_date').is_in(labels['trade_date'].unique().implode())).select(
            pl.col('ts_code').alias('symbol'),'trade_date',pl.col('value').alias(factor)).collect()
        labels=labels.join(values,on=['symbol','trade_date'],how='left',validate='1:1')
    return labels


def admitted_controls(statistics: Path, scorecard: pl.DataFrame) -> tuple[pl.DataFrame,list[str]]:
    """Preserve each admitted raw/neutral variant and its published direction."""
    admitted=scorecard.filter(pl.col('factor_admitted')).select('factor','variant','mean_ic').unique()
    panel=None
    names=[]
    for factor,variant,mean_ic in admitted.iter_rows():
        name=f'control_{factor}_{variant}'
        folder=statistics/'factors'/factor
        saved=json.loads((folder/'statistics.json').read_text(encoding='utf-8'))
        rows=saved['statistics']
        rows=rows.values() if isinstance(rows,dict) else rows
        same=[r for r in rows if r.get('variant')==variant]
        if same and abs(same[0]['mean_ic']-mean_ic)>1e-10:
            raise ValueError(f'Admitted scorecard/statistics mismatch: {factor}/{variant}')
        values=pl.read_parquet(folder/'monthly_scores.parquet').select('symbol','trade_date',pl.col(variant).alias(name))
        panel=values if panel is None else panel.join(values,on=['symbol','trade_date'],how='full',coalesce=True,validate='1:1')
        names.append(name)
    if panel is None:
        raise ValueError('Current published reference has no admitted controls')
    return panel,names


def read_training_sample(*, data_root: Path, refresh_config: Path, statistics: list[Path],
                         factors: list[str], end: dt.date, symbols: int = 300,
                         months: int = 72, cross_stock: dict | None = None) -> tuple[pl.DataFrame, pl.DataFrame]:
    # Sample by stable symbol hash, including historical delistings, never by returns.
    start = dt.date(end.year - 7, 1, 1)
    labels = read_genetic_panel(data_root=data_root, statistics=statistics, factors=[],
                               start=start, end=end)
    labels = labels.filter(pl.col('label_exit_date') <= end)
    dates = labels['trade_date'].unique().sort().tail(months)
    labels = labels.filter(pl.col('trade_date').is_in(dates.implode()))
    cohort = labels.select('symbol').unique().with_columns(
        pl.col('symbol').hash(seed=20260913).alias('sample_order')).sort('sample_order').head(symbols)['symbol']
    if cross_stock:
        from quant.data.cross_stock_sampling import stock_groups
        assignments = stock_groups(labels['symbol'].unique().to_list(), groups=cross_stock['sample_groups'],
            per_group=cross_stock['symbols_per_group'], seed=cross_stock['sample_seed'])
        cohort = pl.Series('symbol', list(assignments))
    labels = labels.filter(pl.col('symbol').is_in(cohort.implode()))
    sessions = available_sessions(data_root, end)
    # Five nested sixty-session operations require 300 preceding sessions.
    first = max(0, sessions.index(dates.min()) - 300)
    low = sessions[first]
    parts = []
    for year in range(low.year, end.year + 1):
        panel, _ = read_factor_inputs(data_root, refresh_config,
            max(low, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31)), sessions)
        panel = panel.filter(pl.col('symbol').is_in(cohort.implode()))
        panel = read_factor_industry(data_root, panel)
        for factor in factors:
            path = data_root/'factors'/factor/f'year={year}'/'data.parquet'
            if path.exists():
                values = pl.scan_parquet(path).filter(pl.col('ts_code').is_in(cohort.implode())).select(
                    pl.col('ts_code').alias('symbol'), 'trade_date', pl.col('value').alias(f'gp_{factor}')).collect()
                panel = panel.join(values, on=['symbol', 'trade_date'], how='left', validate='1:1')
            else:
                panel = panel.with_columns(pl.lit(None, dtype=pl.Float64).alias(f'gp_{factor}'))
        parts.append(panel)
    return pl.concat(parts, how='diagonal_relaxed').sort('symbol', 'trade_date'), labels
