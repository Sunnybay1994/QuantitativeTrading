"""Bounded, local-only ETF turnover recovery into one observation run."""
import hashlib
from pathlib import Path

import polars as pl

from quant.data.intraday_bars import SCHEMA
from quant.data.tdx_intraday import decode_minute_payload


def validate_day(bars: pl.DataFrame, reference: pl.DataFrame) -> dict:
    if bars.height != 240 or bars['bar_start'].n_unique() != 240:
        raise ValueError('TDX day must contain 240 distinct one-minute bars')
    traded = bars.filter(pl.col('volume') > 0)
    if traded.is_empty() or bars.filter((pl.col('volume') == 0) & (pl.col('amount') != 0)).height:
        raise ValueError('Invalid or absent turnover')
    if traded.filter(~(pl.col('amount')/pl.col('volume')).is_between(
            pl.col('low')-.0011, pl.col('high')+.0011)).height:
        raise ValueError('Turnover units inconsistent with bar prices')
    joined = bars.join(reference.select('bar_start', 'close'), on='bar_start', suffix='_reference')
    if reference['close'].null_count() or not reference['close'].is_finite().all():
        raise ValueError('Reference contains invalid prices')
    if reference['bar_start'].is_duplicated().any() or joined.height < 192:
        raise ValueError('Insufficient distinct reference bars for cross-source check')
    difference = joined.select((pl.col('close')-pl.col('close_reference')).abs().max()).item()
    if difference is None or difference > .0011:
        raise ValueError('Cross-source close mismatch exceeds one ETF price tick')
    return {'matched_reference_bars': joined.height, 'maximum_close_difference': difference}


def recover(*, orders: pl.DataFrame, minutes: pl.DataFrame, known_through,
            tdx_root: Path, output: Path) -> tuple[pl.DataFrame, list[dict]]:
    audit, replacements = [], []
    keys = orders.filter((pl.col('asset_type') == 'etf') &
                         (pl.col('execution_date') <= known_through)).select('symbol', 'execution_date').unique()
    for symbol, day in sorted(keys.iter_rows()):
        mask = (pl.col('symbol') == symbol) & (pl.col('trade_date') == day)
        reference = minutes.filter(mask)
        if reference.height and reference['amount'].null_count() == 0:
            continue
        record = {'symbol': symbol, 'date': str(day), 'source': 'tdx', 'status': 'unavailable'}
        try:
            if len(symbol) != 9 or not symbol[:6].isdigit() or symbol[6:] not in ('.SH', '.SZ'):
                raise ValueError('Unsupported ETF symbol')
            market = symbol[-2:].lower()
            source = tdx_root/market/'minline'/f'{market}{symbol[:6]}.lc1'
            payload = source.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            record.update(source_file=str(source), sha256=digest)
            _, decoded, stats = decode_minute_payload(payload, symbol=symbol, frequency='1m')
            if stats.trailing_bytes:
                raise ValueError('Truncated local minute snapshot')
            bars = decoded.filter(pl.col('trade_date') == day).select(list(SCHEMA))
            record.update(validate_day(bars, reference))
            raw = output/'raw_tdx'/f'{symbol}_{digest}.lc1'
            raw.parent.mkdir(parents=True, exist_ok=True)
            if raw.exists():
                if raw.read_bytes() != payload:
                    raise ValueError('Immutable raw snapshot conflict')
            else:
                with raw.open('xb') as stream:
                    stream.write(payload)
            replacements.append(bars)
            minutes = minutes.filter(~mask)
            record.update(status='recovered', raw_path=str(raw), rows=bars.height)
        except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
            record['reason'] = f'{type(exc).__name__}: {exc}'
        audit.append(record)
    return pl.concat([minutes, *replacements], how='vertical_relaxed'), audit
