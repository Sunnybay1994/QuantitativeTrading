"""Publish R1 ETF bars, cash actions and explicitly sourced split valuations."""
import argparse
import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.mappers import TushareBarMapper
from quant.data.stock_paper_inputs import DIVIDEND_SCHEMA, read_stock_paper_calendar
from quant.domain import Bar1dSchema, InstrumentSchema


def cash_actions(raw: pl.DataFrame, end: dt.date) -> list[dict]:
    if raw.is_empty():
        return []
    rows = []
    for row in raw.filter(pl.col('div_proc') == '实施').iter_rows(named=True):
        if not row.get('ex_date'):
            continue
        def day(field):
            return dt.datetime.strptime(str(row[field]), '%Y%m%d').date()
        ex = day('ex_date')
        if ex > end:
            continue
        ann = day('imp_anndate') if row.get('imp_anndate') else day('ann_date')
        record, pay = day('record_date'), day('pay_date')
        amount = float(row['div_cash'])
        if not ann <= record < ex <= pay or not 0 <= amount < float('inf'):
            raise ValueError('Incomplete or noncausal ETF cash action')
        rows.append(dict(symbol=row['ts_code'], ann_date=ann, record_date=record,
            ex_date=ex, pay_date=pay, share_list_date=None, div_cash=amount, share_ratio=0.))
    unique = {tuple(row.items()): row for row in rows}
    rows = list(unique.values())
    keys = [(row['symbol'], row['ex_date']) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('Conflicting ETF cash action terms')
    return rows


def economic_prices(*, bars: pl.DataFrame, sessions: list[dt.date],
                    actions: list[dict], splits: list[dict]) -> pl.DataFrame:
    """Ex-date reinvestment signal index; actual ledger still pays cash on pay_date.

    Suspended valuations are kept separate from tradable bars. A known split
    carries book value; vendor adjustment factors never determine share counts.
    """
    symbol = bars['symbol'].unique().item()
    quotes = {r['trade_date']: r['close'] for r in bars.iter_rows(named=True)}
    cash = {r['ex_date']: r['div_cash'] for r in actions if r['symbol'] == symbol}
    events = {r['effective_date']: r for r in splits if r['symbol'] == symbol}
    suspended = {day for r in splits if r['symbol'] == symbol for day in r['suspended_dates']}
    previous, index, rows = None, 100., []
    for date in sessions:
        if date < min(quotes):
            continue
        split = events.get(date)
        ratio = float(split['ratio']) if split else 1.
        if split and not split['announcement_date'] <= split['record_date'] < date:
            raise ValueError('Split terms were not known before becoming effective')
        observed = date in quotes
        if not observed and (date not in suspended or previous is None):
            raise ValueError(f'Unexplained absent ETF quote: {symbol} {date}')
        close = quotes[date] if observed else previous/ratio
        if previous is not None:
            index *= ratio*(close+cash.get(date, 0.))/previous
        rows.append({'symbol': symbol, 'trade_date': date, 'valuation_price': close,
                     'total_return_price': index, 'observed_quote': observed,
                     'split_ratio': ratio, 'cash_dividend': cash.get(date, 0.)})
        previous = close
    return pl.from_dicts(rows)


def publish(*, capture: Path, output: Path, data_root: Path = Path('data')) -> dict:
    receipt = json.loads((capture/'summary.json').read_text(encoding='utf-8'))
    if receipt['status'] != 'captured' or receipt['replay_performed'] is not False:
        raise ValueError('Require completed, unreplayed raw capture')
    config_payload = (capture/'config.toml').read_bytes()
    if hashlib.sha256(config_payload).hexdigest() != receipt['config_sha256']:
        raise ValueError('Captured preregistration changed')
    spec = tomllib.loads(config_payload.decode('utf-8'))
    terms = (capture/'corporate_actions.toml').read_bytes()
    if hashlib.sha256(terms).hexdigest() != receipt['events_sha256']:
        raise ValueError('Corporate-action source changed')
    splits = tomllib.loads(terms.decode('utf-8'))['splits']
    for item in receipt['requests'].values():
        if hashlib.sha256(Path(item['raw_path']).read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Captured raw checksum differs')
    def read_raw(symbol, table):
        paths = [item['raw_path'] for key,item in receipt['requests'].items()
                 if key.startswith(f'{symbol}/{table}/')]
        if not paths:
            raise ValueError(f'No captured requests for {symbol}/{table}')
        return pl.concat([pl.read_parquet(path) for path in paths],how='diagonal_relaxed')
    output.mkdir(parents=True, exist_ok=False)
    calendar = read_stock_paper_calendar(data_root)
    sessions = sorted(calendar.filter(pl.col('is_open') &
        pl.col('date').is_between(spec['pessimistic']['pre2019']['start'], spec['end']))['date'].unique())
    frames, prices, actions, instruments, references = [], [], [], [], []
    listings = {row['symbol']: row['listing_date'] for row in spec['etfs'].values()}
    listings['510300.SH'] = dt.date(2012, 5, 28)
    for symbol, listing in listings.items():
        daily = read_raw(symbol,'fund_daily')
        bars = Bar1dSchema.validate(TushareBarMapper().map(daily.with_columns(
            pl.col('ts_code').alias('_request_symbol'), pl.lit('SH').alias('_market'))))
        cash = cash_actions(read_raw(symbol,'fund_div'), spec['end'])
        actions.extend(cash)
        frames.append(bars)
        references.append(daily.select(pl.col('ts_code').alias('symbol'),
            pl.col('trade_date').str.to_date('%Y%m%d'), pl.col('pre_close').cast(pl.Float64)))
        prices.append(economic_prices(bars=bars, sessions=sessions, actions=cash, splits=splits))
        instruments.append(dict(symbol=symbol, market='SH', name=symbol, instrument_type='ETF',
            currency='CNY', list_date=listing, delist_date=None, board_lot=100, status='LISTED'))
    for event in splits:
        actions.append(dict(symbol=event['symbol'], ann_date=event['announcement_date'],
            record_date=event['record_date'], ex_date=event['effective_date'],
            pay_date=event['effective_date'], div_cash=0., share_ratio=event['ratio']-1.,
            share_list_date=event['tradable_date']))
    events = pl.from_dicts(actions, schema=DIVIDEND_SCHEMA)
    if events.select('symbol', 'ex_date').is_duplicated().any():
        raise ValueError('Duplicate ETF corporate actions need explicit reconciliation')
    instruments = InstrumentSchema.validate(pl.from_dicts(instruments, schema_overrides={'delist_date': pl.Date}))
    products = {'bars': pl.concat(frames), 'calendar': calendar, 'instruments': instruments,
                'dividends': events, 'economic_prices': pl.concat(prices),
                'reference_prices': pl.concat(references)}
    manifest = {}
    for name, frame in products.items():
        path = output/f'{name}.parquet'
        frame.write_parquet(path)
        manifest[name] = {'rows': frame.height, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (output/'corporate_actions.toml').write_bytes(terms)
    summary = {'capture': str(capture), 'auto_trade': False, 'status': 'published',
        'products': manifest, 'replay_performed': False,
        'return_convention': 'cash-dividend ex-date reinvestment for volatility only; account cash settles on payment date',
        'suspended_bars_synthesized': 0, 'vendor_adjustment_factor_used': False}
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(publish(capture=args.capture, output=args.output)))


if __name__ == '__main__':
    main()
