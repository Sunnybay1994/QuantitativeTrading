"""Anchor a newly prepended ETF total-return history to its existing successor."""

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.etf_paper_inputs import read_etf_dividends
from quant.data.mappers import AkshareResearchPriceMapper
from quant.data.storage import CleanResearchPriceStore


def alignment_scale(*, previous_adjusted: float, previous_close: float,
                    next_adjusted: float, next_close: float, next_dividend: float) -> float:
    """Preserve the cash-dividend return across the old/new publication boundary."""
    import math

    if (not all(math.isfinite(v) and v > 0 for v in
                (previous_adjusted, previous_close, next_adjusted, next_close))
            or not math.isfinite(next_dividend) or next_dividend < 0):
        raise ValueError('Invalid ETF history anchor')
    return next_adjusted / (previous_adjusted * (next_close + next_dividend) / previous_close)


def run(*, data_root: Path, raw_path: Path, symbol: str, output: Path) -> dict[str, Any]:
    raw = pl.read_parquet(raw_path).filter(pl.col('_request_symbol') == symbol)
    if raw.is_empty() or raw['_adjustment'].unique().to_list() != ['total_return_dividend']:
        raise ValueError('Expected archived cash-dividend research prices')
    prefix = AkshareResearchPriceMapper(source='akshare_sina').map(raw).sort('trade_date')
    end = prefix['trade_date'][-1]
    root = data_root / 'clean/research_price_1d'
    successors = pl.scan_parquet(str(root / 'date=*/data.parquet')).filter(
        (pl.col('symbol') == symbol) & (pl.col('trade_date') > end)
        & (pl.col('adjustment_method') == 'TOTAL_RETURN_DIVIDEND')).sort('trade_date').limit(1).collect()
    if successors.height != 1:
        raise ValueError('Missing existing successor anchor')
    anchor = successors.row(0, named=True)
    calendar = pl.read_parquet(data_root / f'clean/trade_calendar/market={symbol[-2:]}/data.parquet')
    next_session = calendar.filter(pl.col('is_open') & (pl.col('date') > end))['date'].min()
    if not isinstance(next_session, dt.date) or anchor['trade_date'] != next_session:
        raise ValueError('History and successor are not adjacent exchange sessions')
    close = pl.read_parquet(data_root / f'clean/bar_1d/date={next_session}/data.parquet').filter(
        (pl.col('symbol') == symbol) & (pl.col('source') == 'akshare'))
    if close.height != 1:
        raise ValueError('Missing unadjusted successor price')
    events = read_etf_dividends(data_root, [symbol], end)
    dividend = float(events.filter(pl.col('ex_date') == next_session)['div_cash'].sum())
    last_raw = raw.with_columns(pl.col('日期').cast(pl.Date)).sort('日期').row(-1, named=True)
    scale = alignment_scale(previous_adjusted=prefix['adjusted_close'][-1],
        previous_close=float(last_raw['收盘']), next_adjusted=anchor['adjusted_close'],
        next_close=close['close'][0], next_dividend=dividend)
    adjusted = prefix.with_columns((pl.col('adjusted_close') * scale).alias('adjusted_close'))
    rows = CleanResearchPriceStore(root).upsert(adjusted)
    result = dict(symbol=symbol, raw_path=str(raw_path), rows=rows, end=str(end),
                  anchor_date=str(next_session), anchor_adjusted_close=anchor['adjusted_close'],
                  scale=scale, boundary_return=(close['close'][0]+dividend)/float(last_raw['收盘'])-1)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--raw-path', type=Path, required=True)
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(**vars(args)), ensure_ascii=False))


if __name__ == '__main__':
    main()
