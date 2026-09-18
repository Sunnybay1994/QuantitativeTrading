"""Shadow prices for saved reference orders, separate from realized trading costs."""
import datetime as dt
import json
import math
from pathlib import Path

import polars as pl

from quant.data.shadow_slippage_inputs import read_inputs

ZONE = dt.timezone(dt.timedelta(hours=8))
ORDER_SCHEMA = {'account': pl.String, 'asset_type': pl.String, 'as_of': pl.Date,
    'execution_date': pl.Date, 'symbol': pl.String, 'side': pl.String, 'quantity': pl.Int64,
    'signal_price': pl.Float64}
DETAIL_SCHEMA = {**ORDER_SCHEMA, 'source_kind': pl.String, 'horizon': pl.String,
    'shadow_price': pl.Float64, 'open_price': pl.Float64, 'slippage_bps': pl.Float64,
    'vs_open_bps': pl.Float64, 'status': pl.String, 'reason': pl.String}
MONTH_SCHEMA = {'account': pl.String, 'month': pl.String, 'horizon': pl.String,
    'samples': pl.UInt32, 'valid_samples': pl.UInt32, 'missing_samples': pl.UInt32,
    'pending_samples': pl.UInt32, 'median_bps': pl.Float64, 'p90_bps': pl.Float64}


def read_orders(accounts: list[dict], known_through: dt.date) -> tuple[pl.DataFrame, list[dict]]:
    rows, errors = [], []
    names = [a['account'] for a in accounts]
    if len(names) != len(set(names)):
        raise ValueError('Account ids must be unique')
    for account in accounts:
        if account['asset_type'] not in ('stock', 'etf'):
            raise ValueError('Account asset_type must be stock or etf')
        root = Path(account['root'])
        paths = [root/'orders.csv'] if (root/'orders.csv').is_file() else sorted(root.glob('????-??-??/orders.csv'))
        if not paths:
            errors.append({'account': account['account'], 'error': 'No saved reference order files'})
        for path in paths:
            try:
                frame = pl.read_csv(path, try_parse_dates=True)
                for row in frame.iter_rows(named=True):
                    day = dt.date.fromisoformat(str(row['as_of']))
                    if day > known_through:
                        continue
                    execution = dt.date.fromisoformat(str(row['execution_date']))
                    if execution <= day or row['side'].upper() not in ('BUY', 'SELL') or row['quantity'] <= 0:
                        raise ValueError('Invalid reference order dates, side or quantity')
                    if float(row['quantity']) != int(row['quantity']):
                        raise ValueError('Nonintegral reference quantity')
                    rows.append({'account': account['account'], 'asset_type': account['asset_type'],
                        'as_of': day, 'execution_date': execution, 'symbol': row['symbol'],
                        'side': row['side'].upper(), 'quantity': row['quantity'], 'signal_price': row['reference_price']})
            except Exception as exc:
                errors.append({'account': account['account'], 'path': str(path), 'error': f'{type(exc).__name__}: {exc}'})
    frame = pl.from_dicts(rows, schema=ORDER_SCHEMA) if rows else pl.DataFrame(schema=ORDER_SCHEMA)
    frame = frame.unique().sort('account', 'execution_date', 'symbol', 'side')
    keys = ['account', 'as_of', 'execution_date', 'symbol', 'side']
    conflicts = frame.group_by(keys).len().filter(pl.col('len') > 1)
    if conflicts.height:
        errors.extend({**r, 'error': 'Conflicting saved reference orders'} for r in conflicts.to_dicts())
        frame = frame.join(conflicts.select(keys), on=keys, how='anti')
    return frame, errors


def _positive(value) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def _vwap(frame: pl.DataFrame, day: dt.date, horizon: int) -> tuple[float | None, str]:
    start = dt.datetime.combine(day, dt.time(9, 30), ZONE)
    end = start+dt.timedelta(minutes=horizon)
    frame = frame.filter((pl.col('bar_start') >= pl.lit(start).dt.convert_time_zone('Asia/Shanghai')) & (pl.col('bar_end') <= pl.lit(end).dt.convert_time_zone('Asia/Shanghai'))).sort('bar_start')
    if frame.is_empty():
        return None, 'missing_minute_window'
    cursor, amount, volume = start, 0., 0.
    for row in frame.iter_rows(named=True):
        if row['bar_start'] != cursor or row['bar_end'] <= cursor:
            return None, 'incomplete_or_duplicate_minute_window'
        a, v = row['amount'], row['volume']
        if a is None or v is None or not math.isfinite(a) or not math.isfinite(v) or a < 0 or v < 0 or (v == 0 and a != 0):
            return None, 'missing_or_invalid_minute_turnover'
        cursor, amount, volume = row['bar_end'], amount+a, volume+v
    if cursor != end:
        return None, 'incomplete_minute_window'
    if volume <= 0 or amount <= 0:
        return None, 'no_traded_volume'
    value = amount/volume
    return (value, '') if _positive(value) else (None, 'invalid_vwap')


def calculate(*, orders: pl.DataFrame, daily: pl.DataFrame, minutes: pl.DataFrame,
              known_through: dt.date) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Positive signed bps means adverse price movement; fees never enter this calculation."""
    if orders.select('account', 'as_of', 'execution_date', 'symbol', 'side').is_duplicated().any():
        raise ValueError('Duplicate shadow order keys')
    rows = []
    for order in orders.iter_rows(named=True):
        day = order['execution_date']
        if order['side'] not in ('BUY', 'SELL') or day <= order['as_of'] or order['as_of'] > known_through:
            raise ValueError('Invalid shadow order contract')
        quotes = daily.filter((pl.col('symbol') == order['symbol']) & (pl.col('trade_date') == day))
        opening = quotes['open'][0] if quotes.height == 1 and _positive(quotes['open'][0]) else None
        bars = minutes.filter((pl.col('symbol') == order['symbol']) & (pl.col('trade_date') == day))
        for horizon in (0, 5, 15, 30):
            price, reason = opening, '' if opening else 'missing_or_duplicate_daily_open'
            if day > known_through:
                price, reason, status = None, 'execution_session_not_completed', 'pending'
            else:
                if horizon:
                    price, reason = _vwap(bars, day, horizon)
                status = 'observed' if price is not None else 'missing'
                if not _positive(order['signal_price']):
                    status, reason = 'missing', 'missing_or_invalid_signal_price'
            sign = 1 if order['side'] == 'BUY' else -1
            rows.append({**order, 'source_kind': 'reference_orders', 'horizon': 'open' if horizon == 0 else f'vwap_{horizon}m',
                'shadow_price': price, 'open_price': opening if day <= known_through else None,
                'slippage_bps': sign*(price/order['signal_price']-1)*10000 if status == 'observed' else None,
                'vs_open_bps': sign*(price/opening-1)*10000 if status == 'observed' and opening else None,
                'status': status, 'reason': reason})
    detail = pl.from_dicts(rows, schema=DETAIL_SCHEMA) if rows else pl.DataFrame(schema=DETAIL_SCHEMA)
    if detail.is_empty():
        return detail, pl.DataFrame(schema=MONTH_SCHEMA)
    monthly = detail.with_columns(pl.col('execution_date').dt.strftime('%Y-%m').alias('month')).group_by(
        'account', 'month', 'horizon').agg(pl.len().alias('samples'),
        (pl.col('status') == 'observed').sum().alias('valid_samples'),
        (pl.col('status') == 'missing').sum().alias('missing_samples'),
        (pl.col('status') == 'pending').sum().alias('pending_samples'),
        pl.col('slippage_bps').median().alias('median_bps'),
        pl.col('slippage_bps').quantile(.9, interpolation='linear').alias('p90_bps')).sort('account', 'month', 'horizon')
    return detail, monthly


def run(*, accounts: list[dict], known_through: dt.date, output: Path,
        data_root: Path = Path('data'), refresh_config: Path = Path('configs/data/refresh.toml'),
        etf_snapshot: str | None = None, minute_source: str = 'baostock', frequency: str = '5m',
        etf_minute_source: str = 'yahoo') -> dict:
    now = dt.datetime.now(ZONE)
    if known_through > now.date() or (known_through == now.date() and now.hour < 15):
        raise ValueError('Shadow recording requires an actual completed close')
    output.mkdir(parents=True, exist_ok=False)
    orders, errors = read_orders(accounts, known_through)
    daily, minutes, input_errors = read_inputs(orders=orders, known_through=known_through,
        data_root=data_root, refresh_config=refresh_config, etf_snapshot=etf_snapshot,
        minute_source=minute_source, frequency=frequency, etf_minute_source=etf_minute_source)
    detail, monthly = calculate(orders=orders, daily=daily, minutes=minutes, known_through=known_through)
    detail.write_csv(output/'shadow_execution.csv')
    monthly.write_csv(output/'slippage_monthly.csv')
    from quant.execution.shadow_data_gaps import summarize_gaps
    gaps, gap_summary = summarize_gaps(detail, etf_minute_source=etf_minute_source)
    gaps.write_csv(output/'data_gaps.csv')
    valid = detail.filter(pl.col('status') == 'observed').height
    summary = {'known_through': str(known_through), 'accounts': accounts, 'orders': orders.height,
        'observed_horizons': valid, 'missing_horizons': detail.filter(pl.col('status') == 'missing').height,
        'pending_horizons': detail.filter(pl.col('status') == 'pending').height, 'data_gaps': gap_summary,
        'status': ('failed' if errors else 'no_samples') if detail.is_empty() else ('partial' if errors or input_errors or detail.filter(pl.col('status') != 'observed').height else 'recorded'),
        'errors': [*errors, *input_errors], 'requires_review': bool(errors or input_errors or detail.filter(pl.col('status') == 'missing').height), 'auto_trade': False, 'calibration_complete': False,
        'sample_basis': 'saved reference orders; hypothetical prices, not actual execution fills',
        'price_basis': 'unadjusted signal reference, daily open, sum(amount CNY)/sum(volume shares)',
        'sign': 'positive adverse: BUY +1, SELL -1; price-only, excludes all fees',
        'minute_source': minute_source, 'frequency': frequency,
        'etf_minute_source': etf_minute_source, 'etf_frequency': '1m', 'output': str(output)}
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding='utf-8')
    return summary
