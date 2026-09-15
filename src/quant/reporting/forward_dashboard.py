"""One local HTML view of saved observation accounts; never advances an account."""
import argparse
import datetime as dt
import json
import math
from pathlib import Path
import tomllib

import polars as pl


def account_specs(settings: dict) -> list[dict]:
    b20 = Path(settings['b20']['output'])
    b32 = Path(settings['b32']['output'])
    rows = [{'account': f'b20_{cost}_{kind}', 'label': f'ETF {"策略" if kind == "strategy" else "等权基准"} · {cost}×成本',
             'root': str(b20/f'cost_{cost}'/kind), 'asset_type': 'etf'}
            for cost in ('0.5', '1', '2') for kind in ('strategy', 's0')]
    rows += [{'account': name, 'label': label, 'root': str(b32/name), 'asset_type': 'stock'}
             for name, label in [('b32_cv20_buffer75', 'B32 换手变异'),
                                 ('b32_paired_three_factor', 'B32 三因子')]]
    if settings.get('q10'):
        rows.append({'account': 'q10_sue_v2', 'label': 'Q10 SUE v2',
                     'root': settings['q10']['output'], 'asset_type': 'stock'})
    return rows


def read_account(spec: dict, as_of: dt.date) -> dict:
    row = {**spec, 'status': 'unavailable', 'history': [], 'exposures': []}
    try:
        snapshots = sorted(p for p in Path(spec['root']).glob('????-??-??/state.json')
                           if p.parent.name <= str(as_of))
        if not snapshots:
            raise ValueError('没有截至日以内的账户快照')
        snapshot = snapshots[-1].parent
        state = json.loads(snapshots[-1].read_text(encoding='utf-8'))
        if state['date'] != snapshot.name:
            raise ValueError('快照目录与账户日期不一致')
        nav = pl.read_csv(snapshot/'nav.csv', try_parse_dates=True).sort('date')
        if (nav.is_empty() or nav['date'].is_duplicated().any() or nav['date'].max() != dt.date.fromisoformat(state['date'])
                or any(nav[c].null_count() or not nav[c].is_finite().all() or (nav[c] <= 0).any()
                       for c in ('unit_nav', 'equity'))):
            raise ValueError('净值日期或数值无效')
        last = nav.row(-1, named=True)
        equity = float(last['equity'])
        holdings = []
        for symbol, holding in state['holdings'].items():
            value = holding['quantity']*holding['mark_price']
            if not math.isfinite(value) or value < 0:
                raise ValueError('持仓市值无效')
            holdings.append({'symbol': symbol, 'value': value, 'weight': value/equity})
        cash = float(state['cash'])
        receivable = sum(float(r['amount']) for r in state.get('receivables', []))
        if not math.isfinite(cash) or abs(cash+receivable+sum(h['value'] for h in holdings)-equity) > max(.01, equity*1e-8):
            raise ValueError('现金、持仓及应收与净值不平')
        gross, complete_fills = 0., True
        for source in snapshots:
            fills = source.parent/'fills.csv'
            if fills.exists():
                frame = pl.read_csv(fills)
                if frame.height:
                    if (not (frame['date'] == source.parent.name).all() or frame['notional'].null_count()
                            or not frame['notional'].is_finite().all() or (frame['notional'] < 0).any()):
                        raise ValueError('成交日期或金额无效')
                    gross += float(frame['notional'].sum())
            else:
                old = json.loads(source.read_text(encoding='utf-8'))
                if old['holdings'] or old.get('cumulative_fees', 0):
                    complete_fills = False
        high = 1.0
        history = []
        for item in nav.iter_rows(named=True):
            high = max(high, item['unit_nav'])
            history.append({'date': str(item['date']), 'nav': item['unit_nav'],
                            'drawdown': item['unit_nav']/high-1, 'equity': item['equity']})
        row.update(status='current' if snapshot.name == str(as_of) else 'stale', as_of=snapshot.name,
                   first_date=str(nav['date'].min()), equity=equity, nav=last['unit_nav'],
                   return_since_inception=last['unit_nav']-1, drawdown=history[-1]['drawdown'],
                   maximum_drawdown=min(h['drawdown'] for h in history), cash_weight=cash/equity,
                   receivable_weight=receivable/equity, holding_count=len(holdings),
                   turnover=gross/2/(sum(float(v) for v in nav['equity'])/nav.height) if complete_fills else None,
                   history=history, exposures=sorted(holdings, key=lambda h:-h['weight']),
                   source=str(snapshot.resolve()), turnover_complete=complete_fills)
    except (OSError, ValueError, KeyError, TypeError, pl.exceptions.PolarsError) as exc:
        row['error'] = str(exc)
    return row


def run(*, settings: dict, as_of: dt.date, output: Path) -> dict:
    rows = [read_account(spec, as_of) for spec in account_specs(settings)]
    result = {'as_of': str(as_of), 'generated_at': dt.datetime.now().isoformat(), 'auto_trade': False,
              'account_count': len(rows), 'current_count': sum(r['status'] == 'current' for r in rows),
              'accounts': rows, 'turnover_basis': 'half_gross_fills_over_mean_observed_daily_equity',
              'exposure_basis': 'saved_holding_market_value_over_equity', 'output': str(output)}
    result['status'] = 'complete' if result['current_count'] == len(rows) else 'incomplete'
    output.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
    temporary = output/'dashboard.json.tmp'
    temporary.write_text(payload, encoding='utf-8')
    temporary.replace(output/'dashboard.json')
    template = Path(__file__).with_name('forward_dashboard.html').read_text(encoding='utf-8')
    # JSON in a script element must not admit an HTML closing tag from source labels.
    html = template.replace('__DATA__', payload.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026'))
    temporary = output/'dashboard.html.tmp'
    temporary.write_text(html, encoding='utf-8')
    temporary.replace(output/'dashboard.html')
    return {key: value for key, value in result.items() if key != 'accounts'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/research/daily_observation_q2_sue_v2_20260912.toml'))
    parser.add_argument('--as-of', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, default=Path('artifacts/paper/monitor'))
    args = parser.parse_args()
    print(json.dumps(run(settings=tomllib.loads(args.config.read_text(encoding='utf-8')),
                        as_of=args.as_of, output=args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
