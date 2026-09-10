"""Quarterly parent earnings with predecessor revisions bound to publication time."""

import datetime as dt
import math
from collections import defaultdict

import polars as pl

from quant.data.financial_pit import select_financial_revisions_as_of


def select_quarterly_parent_income(history: pl.DataFrame, *, as_of: dt.date) -> tuple[pl.DataFrame, pl.DataFrame]:
    """A cumulative report only subtracts a predecessor known when it was published."""
    columns = ['symbol', 'end_date', 'ann_date', 'f_ann_date', 'available_date',
               'report_type', 'comp_type', 'update_flag', 'n_income_attr_p']
    history = history.select(columns).filter((pl.col('report_type') == '1') & (pl.col('comp_type') == '1'))
    selected = select_financial_revisions_as_of(history, dataset='income', as_of=as_of)
    known = history.filter((pl.col('available_date') < as_of)
        & (pl.col('end_date') <= pl.col('available_date'))
        & pl.col('symbol').str.contains(r'^[0-9]{6}\.(SH|SZ)$'))
    revisions: dict[tuple[str, dt.date], list[dict]] = defaultdict(list)
    for row in known.to_dicts():
        revisions[(row['symbol'], row['end_date'])].append(row)
    output = []
    for row in selected.selected.to_dicts():
        period = row['end_date']
        single = None
        status = 'MISSING_OR_INVALID'
        if (period.month, period.day) in ((3, 31), (6, 30), (9, 30), (12, 31)):
            value = row['n_income_attr_p']
            if period.month == 3:
                single = value
            else:
                predecessor = {6: dt.date(period.year, 3, 31), 9: dt.date(period.year, 6, 30),
                               12: dt.date(period.year, 9, 30)}[period.month]
                candidates = [r for r in revisions[(row['symbol'], predecessor)]
                              if r['available_date'] <= row['available_date']]
                if candidates:
                    latest = max(r['available_date'] for r in candidates)
                    values = {r['n_income_attr_p'] for r in candidates if r['available_date'] == latest}
                    if len(values) == 1:
                        prior = next(iter(values))
                        if value is not None and prior is not None:
                            single = value - prior
                    else:
                        status = 'PREDECESSOR_REVISION_CONFLICT'
        if single is not None and math.isfinite(single):
            status = 'VALID'
        else:
            single = None
        output.append({'symbol': row['symbol'], 'end_date': period,
                       'available_date': row['available_date'], 'single_parent_income': single,
                       'quarter_income_status': status})
    schema = {'symbol': pl.String, 'end_date': pl.Date, 'available_date': pl.Date,
              'single_parent_income': pl.Float64, 'quarter_income_status': pl.String}
    return pl.DataFrame(output, schema=schema), selected.quarantined
