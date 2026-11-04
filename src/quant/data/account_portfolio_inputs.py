"""Capture bounded ETF history for the preregistered account portfolio replay."""
import argparse
import datetime as dt
import hashlib
import json
import time
import tomllib
from pathlib import Path

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.stock_paper_inputs import read_stock_paper_calendar
from quant.data.storage import RawStore

DEFAULT_CONFIG = Path('configs/research/account_portfolio_v1.toml')
EVENTS = Path('configs/data/account_portfolio_events_v1.toml')


def daily_diagnostics(frame: pl.DataFrame, *, symbol: str, start: dt.date,
                      end: dt.date, calendar: pl.DataFrame,
                      suspended_dates: tuple[dt.date, ...] = ()) -> dict:
    days = frame['trade_date'].str.to_date('%Y%m%d')
    expected = set(calendar.filter(pl.col('is_open') & (pl.col('market') == symbol[-2:])
        & pl.col('date').is_between(start, end))['date'])
    if set(frame['ts_code']) != {symbol} or days.n_unique() != frame.height:
        raise ValueError(f'ETF raw key/scope mismatch: {symbol}')
    suspended = set(suspended_dates) & expected
    missing, extra = expected-set(days)-suspended, set(days)-expected
    if set(days) & suspended:
        raise ValueError(f'Observed trading conflicts with declared suspension: {symbol}')
    if missing or extra:
        raise ValueError(f'ETF calendar mismatch {symbol}: missing={len(missing)}, extra={len(extra)}')
    if frame.filter(~pl.col('close').is_finite() | (pl.col('close') <= 0)
                    | pl.col('close').is_null()).height:
        raise ValueError(f'Invalid ETF prices: {symbol}')
    turnover = frame['amount'].cast(pl.Float64)*1000  # Tushare fund_daily: thousand CNY.
    if turnover.is_null().any() or not turnover.is_finite().all() or turnover.min() < 0:
        raise ValueError(f'Invalid ETF turnover: {symbol}')
    return {'symbol': symbol, 'rows': frame.height, 'first_date': str(days.min()),
            'last_date': str(days.max()), 'expected_sessions': len(expected), 'missing_sessions': 0,
            'documented_suspended_dates': sorted(str(day) for day in suspended),
            'turnover_cny_min': turnover.min(), 'turnover_cny_median': turnover.median(),
            'zero_turnover_sessions': int((turnover == 0).sum())}


def run(*, output: Path, config: Path = DEFAULT_CONFIG, data_root: Path = Path('data'),
        resume: bool = False) -> dict:
    payload = config.read_bytes()
    spec = tomllib.loads(payload.decode('utf-8'))
    if spec.get('auto_trade') is not False or spec['capital_cny'] != 300000:
        raise ValueError('Require preregistered manual-only 300k portfolio')
    if output.exists() and not resume:
        raise FileExistsError('Use --resume for an existing capture; successful requests are reused')
    output.mkdir(parents=True, exist_ok=True)
    frozen = output/'config.toml'
    if frozen.exists() and frozen.read_bytes() != payload:
        raise ValueError('Frozen capture config changed')
    if not frozen.exists():
        frozen.write_bytes(payload)
    receipt_path = output/'summary.json'
    receipt = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {
        'config_sha256': hashlib.sha256(payload).hexdigest(), 'requests': {}, 'diagnostics': [],
        'auto_trade': False, 'status': 'running', 'replay_performed': False}
    receipt['status'] = 'running'

    def save():
        temporary = output/'summary.json.tmp'
        temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(receipt_path)

    save()
    connector, store = TushareConnector(), RawStore(data_root/'raw')
    events_payload = EVENTS.read_bytes()
    events_digest = hashlib.sha256(events_payload).hexdigest()
    if receipt.get('events_sha256', events_digest) != events_digest:
        raise ValueError('Frozen corporate-action inputs changed')
    receipt['events_sha256'] = events_digest
    (output/'corporate_actions.toml').write_bytes(events_payload)
    events = tomllib.loads(events_payload.decode('utf-8'))['splits']
    for event in events:
        if not event['announcement_date'] <= event['record_date'] < event['effective_date'] <= event['tradable_date']:
            raise ValueError('Corporate action is not causally dated')
    symbols = {spec['etfs']['dividend']['symbol']: spec['etfs']['dividend']['listing_date'],
               spec['etfs']['treasury']['symbol']: spec['etfs']['treasury']['listing_date'],
               spec['pessimistic']['pre2019']['stock_proxy']: dt.date(2012, 5, 28)}
    first, end = spec['pessimistic']['pre2019']['start'], spec['end']
    try:
        for symbol, listing in symbols.items():
            begin = max(first, listing)
            for table, fields in [('fund_daily', 'ts_code,trade_date,open,high,low,close,pre_close,vol,amount'),
                                  ('fund_adj', 'ts_code,trade_date,adj_factor'),
                                  ('fund_div', 'ts_code,end_date,ann_date,imp_anndate,record_date,ex_date,pay_date,div_proc,div_cash')]:
                years = range(begin.year, end.year+1) if table != 'fund_div' else [0]
                frames = []
                for year in years:
                    key = f'{symbol}/{table}/{year}'
                    prior = receipt['requests'].get(key)
                    if prior:
                        path = Path(prior['raw_path'])
                        if hashlib.sha256(path.read_bytes()).hexdigest() != prior['sha256']:
                            raise ValueError(f'Captured raw changed: {key}')
                        frame = pl.read_parquet(path)
                    else:
                        params = {'symbol': symbol, 'fields': fields}
                        if year:
                            params.update(start=max(begin, dt.date(year, 1, 1)),
                                          end=min(end, dt.date(year, 12, 31)))
                        frame = getattr(connector, f'fetch_{table}_raw')(**params)
                        raw = store.write(source='tushare', table=table, frame=frame,
                            parameters={'ts_code': symbol, 'consumer': spec['id'],
                                **{k: str(v) for k, v in params.items() if k != 'symbol'}})
                        receipt['requests'][key] = {'raw_path': str(raw.data_path),
                            'sha256': raw.checksum_sha256, 'rows': frame.height}
                        save()
                        print(json.dumps({'request': key, 'rows': frame.height}), flush=True)
                        time.sleep(1.1)  # Below the existing 60 requests/minute allowance.
                    frames.append(frame)
                merged = pl.concat(frames, how='diagonal_relaxed')
                merged.write_parquet(output/f'{symbol}_{table}.parquet')
        calendar = read_stock_paper_calendar(data_root)
        receipt['diagnostics'] = [daily_diagnostics(
            pl.read_parquet(output/f'{symbol}_fund_daily.parquet'), symbol=symbol,
            start=max(first, listing), end=end, calendar=calendar,
            suspended_dates=tuple(day for event in events if event['symbol'] == symbol
                                  for day in event['suspended_dates']))
            for symbol, listing in symbols.items()]
        receipt['corporate_actions'] = json.loads(json.dumps(events, default=str))
        receipt['adjustment_warnings'] = []
        for event in events:
            adj = pl.read_parquet(output/f'{event["symbol"]}_fund_adj.parquet').sort('trade_date')
            jump = adj.with_columns((pl.col('adj_factor')/pl.col('adj_factor').shift(1)).alias('ratio')).filter(
                pl.col('trade_date') == event['tradable_date'].strftime('%Y%m%d'))
            if jump.height != 1 or abs(jump['ratio'][0]-event['ratio']) > 1e-6:
                receipt['adjustment_warnings'].append({'symbol': event['symbol'],
                    'date': str(event['tradable_date']), 'official_split_ratio': event['ratio'],
                    'vendor_factor_ratio': jump['ratio'][0] if jump.height else None,
                    'action': 'Do not use vendor factor as the share split or unverified total-return series'})
        receipt['return_inputs_ready'] = False
        receipt.pop('error', None)
        receipt['status'] = 'captured'
        lines = ['# R1 ETF 输入采集与核对', '',
            '仅完成原始输入采集；尚未回放或注册账户结果，拆分和现金分红须由账户账本处理。', '',
            '| ETF | 行数 | 首日 | 末日 | 已公告停牌日 | 日成交额中位数（元） |',
            '|---|---:|---|---|---|---:|']
        for row in receipt['diagnostics']:
            lines.append(f"| {row['symbol']} | {row['rows']} | {row['first_date']} | {row['last_date']} | "
                f"{','.join(row['documented_suspended_dates']) or '无'} | {row['turnover_cny_median']:.2f} |")
        lines += ['', '## 公司行动与收益口径', '']
        for warning in receipt['adjustment_warnings']:
            lines.append(f"- {warning['symbol']} {warning['date']}：正式拆分比率 "
                f"{warning['official_split_ratio']}；供应商复权因子跳变比率 {warning['vendor_factor_ratio']}。"
                '不得据后者增发份额或直接当作已验证的全收益序列。')
        for event in events:
            lines.append(f"- [拆分前公告]({event['notice']})；[拆分结果]({event['result']})。"
                '保留停牌日，不补造可成交行情。')
        (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    except Exception as exc:
        receipt.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        save()
        raise
    save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    result = run(output=args.output, config=args.config, resume=args.resume)
    print(json.dumps({'status': result['status'], 'requests': len(result['requests']),
        'diagnostics': result['diagnostics'], 'return_inputs_ready': result['return_inputs_ready'],
        'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
