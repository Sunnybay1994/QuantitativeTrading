"""A1 zero-selection-alpha comparisons; executable ETF versus gross index reference."""
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.backtest.account_reconciliation import validate_nav
from quant.backtest.daily_account import advance
from quant.data.account_portfolio_zero_inputs import load
from quant.portfolio.account_portfolio_v1 import Allocation
from quant.research.account_portfolio_etf_baselines import market_states
from quant.research.classic_monthly_baseline import replay
from quant.reporting.account_portfolio_v1 import measure


class ETFProxyAllocation(Allocation):
    """Single ETF replaces stock selection; preserve ETF units off quarter dates."""
    def __call__(self, batch, state):
        day = batch['as_of'][0]
        equity = state['nav'][-1]['equity']
        quarter = not self.initialized or day.month in (3, 6, 9, 12)
        weights = self.weights(day) if quarter else None
        etf_value = sum(h['quantity']*h['mark_price'] for s, h in state['holdings'].items()
                        if s in self.etfs)
        stock_weight = weights[0] if quarter else (equity-etf_value-self.reserved)/equity
        template = batch.row(0, named=True)
        rows = [{**template, 'symbol': '510300.SH', 'weight': stock_weight}]
        deltas = {}
        if quarter:
            self.reserved = 0.
        for i, symbol in enumerate(self.etfs, 1):
            listed = self.spec['etfs'][('dividend', 'treasury')[i-1]]['listing_date'] <= day
            if not listed:
                if quarter:
                    self.reserved += weights[i]*equity
                continue
            held = state['holdings'].get(symbol, {})
            weight = weights[i] if quarter else held.get('quantity', 0)*held.get('mark_price', 0.)/equity
            rows.append({**template, 'symbol': symbol, 'weight': weight})
            if not quarter:
                deltas[symbol] = 0
        self.initialized = True
        return pl.from_dicts(rows, schema=batch.schema), {
            'feasible': True, 'applied': True,
            'as_of': str(day), 'quarterly_allocation': quarter,
            'leg_weights': weights, 'target_share_deltas': deltas or None}


def index_reference(*, returns, days, previous, spec, variant):
    """Fractional gross close-to-close valuation only; no tradable index security."""
    allocator = Allocation(variant=variant, spec=spec, returns=returns, etf_prices=None)
    by_date = {r['date']: r for r in returns.iter_rows(named=True)}
    values = [300000., 0., 0.]
    cash = 0.
    rows = []
    initialized = False
    for day in days:
        quarter = not initialized or previous.month in (3, 6, 9, 12) and previous.month != day.month
        if quarter:
            equity = sum(values)+cash
            weights = allocator.weights(previous)
            values = [equity*w for w in weights]
            cash = 0.
            if spec['etfs']['dividend']['listing_date'] > previous:
                cash, values[1] = values[1], 0.
            initialized = True
        if day not in by_date:
            raise ValueError(f'Missing return-index date: {day}')
        r = by_date[day]
        for i, key in enumerate(('stock', 'dividend', 'treasury')):
            if values[i]:
                value = r[key]
                if value is None or not -1 < value or not float('-inf') < value < float('inf'):
                    raise ValueError(f'Missing/nonfinite reference return: {day} {key}')
                values[i] *= 1+value
        equity = sum(values)+cash
        rows.append({'date': day, 'equity': equity, 'cash': cash,
                     'market_value': sum(values), 'receivable': 0., 'cumulative_fees': 0.,
                     'unit_nav': equity/300000.})
        previous = day
    return pl.from_dicts(rows)


def run(*, root: Path, panel: Path, index: Path, resume=False):
    spec = tomllib.loads((root/'config.toml').read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or spec['fixed_weights'] != [.4, .3, .3]:
        raise ValueError('Require frozen manual-only A1 allocation')
    output = root/'zero_alpha'
    output.mkdir(exist_ok=resume)
    if (output/'summary.json').exists():
        raise FileExistsError('Completed zero-alpha report must not be overwritten')
    inputs, events, reference, _ = load(panel, index)
    paths = [root/'config.toml', panel/'corporate_actions.toml', index, Path(__file__),
             Path('src/quant/data/account_portfolio_zero_inputs.py')]
    paths.extend(panel.glob('*.parquet'))
    manifest = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    manifest_path = output/'manifest.json'
    if resume:
        saved = json.loads(manifest_path.read_text(encoding='utf-8'))
        for name, digest in saved.items():
            if name != str(Path(__file__)) and manifest.get(name) != digest:
                raise ValueError(f'Zero-alpha frozen input changed: {name}')
        (output/'resume_code.json').write_text(json.dumps({
            'original_code_sha256': saved[str(Path(__file__))],
            'current_code_sha256': manifest[str(Path(__file__))],
            'reason': 'Reuse validated completed ETF ledgers; finish gross reference metrics/report'}, indent=2))
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    calendar = inputs['calendar']
    all_days = sorted(calendar.filter(pl.col('is_open'))['date'].unique())
    days = [d for d in all_days if spec['start'] <= d <= spec['end']]
    previous = max(d for d in all_days if d < days[0])
    following = dict(zip(all_days, all_days[1:]))
    signals = [previous]+[a for a, b in zip(days, days[1:]) if a.month != b.month]
    targets = pl.from_dicts([dict(as_of=d, execution_date=following[d], symbol='510300.SH',
        weight=1., strategy='a1_zero_alpha', strategy_version='1') for d in signals])
    wide = inputs['economic_prices'].pivot(on='symbol', index='trade_date', values='total_return_price').sort('trade_date')
    etf_returns = wide.select(pl.col('trade_date').alias('date'),
        pl.col('510300.SH').pct_change().alias('stock'),
        pl.col('512890.SH').pct_change().alias('dividend'),
        pl.col('511010.SH').pct_change().alias('treasury'))
    base = tomllib.loads(Path(spec['stock_source'], 'battery.toml').read_text(encoding='utf-8'))
    rows = []
    for cost in spec['cost_multipliers']:
        settings = copy.deepcopy(base)
        settings['portfolio']['initial_cash'] = spec['capital_cny']
        settings['costs']['etf'] = {k: v for k, v in spec['costs']['etf'].items() if k != 'stamp_tax'}
        settings['costs']['etf']['effective_from'] = dt.date(2014, 1, 1)
        for model in settings['costs'].values():
            for key in ('commission_rate', 'commission_min', 'slippage', 'slippage_per_share'):
                if key in model:
                    model[key] *= cost
        for variant in spec['variants']:
            folder = output/'510300_proxy'/variant/f'cost_{cost:g}'
            if resume and all((folder/f'{name}.parquet').exists() for name in ('nav', 'trades', 'rejections')):
                check = validate_nav(pl.read_parquet(folder/'nav.parquet'), label=str(folder))
                rows.append({'scenario': '510300_executable_proxy', 'variant': variant,
                             'cost_multiplier': cost, **measure(folder), 'reconciliation': check})
                continue
            folder.mkdir(parents=True, exist_ok=resume)
            allocator = ETFProxyAllocation(variant=variant, spec=spec, returns=etf_returns,
                                           etf_prices=None, proxy=True)
            state, _ = advance(date=previous,
                state={'cash': 300000., 'holdings': {}, 'receivables': [], 'pending': [],
                       'nav': [], 'inception_date': str(previous), 'started_with_cash': True},
                bars=inputs['bars'].head(0), calendar=calendar,
                instruments=inputs['instruments'], market_states={},
                dividends=inputs['dividends'].head(0), config={
                    'paper': {'name': 'a1_zero_alpha', 'initial_cash': 300000., 'auto_trade': False},
                    'costs': settings['costs']})
            nav, trades, rejections = replay(bars=inputs['bars'], calendar=calendar,
                instruments=inputs['instruments'], targets=targets, dividends=inputs['dividends'],
                market_states=market_states(inputs['bars'], inputs['reference_prices'], events, cost),
                config=settings, sessions=days, name='a1_zero_alpha', validate_once=True,
                account_state=state, target_constraints=allocator)
            check = validate_nav(nav, label=str(folder))
            for name, frame in (('nav', nav), ('trades', trades), ('rejections', rejections)):
                frame.write_parquet(folder/f'{name}.parquet')
            rows.append({'scenario': '510300_executable_proxy', 'variant': variant,
                         'cost_multiplier': cost, **measure(folder), 'reconciliation': check})
            print(json.dumps({'scenario': '510300', 'variant': variant, 'cost': cost, 'status': 'saved'}), flush=True)
    # Index series is a gross nontradable reference, not an ETF or an executable account.
    if 'index_name' not in reference.columns:
        raise ValueError('Return index requires explicit index_name')
    market = reference.filter(pl.col('index_name') == 'all_market_equal_weight')
    market = market.select(pl.col('trade_date').alias('date'), pl.col('daily_return').alias('market'))
    combined = etf_returns.join(market, on='date', how='left').with_columns(pl.col('market').alias('stock'))
    for variant in spec['variants']:
        folder = output/'all_market_gross_reference'/variant
        folder.mkdir(parents=True, exist_ok=resume)
        nav = index_reference(returns=combined, days=days, previous=previous, spec=spec, variant=variant)
        nav.write_parquet(folder/'nav.parquet')
        # Empty typed fills make the lack of execution costs explicit in metrics.
        pl.DataFrame(schema={'date': pl.Date, 'symbol': pl.String,
                             'notional': pl.Float64}).write_parquet(folder/'trades.parquet')
        rows.append({'scenario': 'all_market_nontradable_gross_reference', 'variant': variant,
                     'cost_multiplier': None, **measure(folder)})
    result: dict = {'status': 'complete', 'rows': rows, 'auto_trade': False, 'index_source': str(index),
        'scope': 'Diagnostic only; not a guaranteed lower bound or admission evidence',
        'reference_limitations': 'All-market index and ETF economic legs use fractional gross close-to-close returns; '
            'zero fees/slippage/lots, no actual orders, and quarter transfers at prior close; '
            'there is no executable all-market ETF or claimed cost-adjusted result.',
        'proxy_scope': '510300 integer-share shared daily account; monthly reinvestment, quarterly allocation; '
            'unchanged symbols/weights/costs, not evidence that selection alpha is zero in reality.'}
    (output/'summary.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    lines = ['# A1 零超额情景', '', result['scope'], '', result['proxy_scope'], '',
             result['reference_limitations'], '',
             '|场景|组合|成本|年化|最大回撤|最差年收益|', '|---|---|---:|---:|---:|---:|']
    for r in rows:
        cost_label = '不适用（毛收益）' if r['cost_multiplier'] is None else str(r['cost_multiplier'])
        lines.append(f"|{r['scenario']}|{r['variant']}|{cost_label}|{r['cagr']:.2%}|"
                     f"{r['max_drawdown']:.2%}|{r['worst_year']['return']:.2%}|")
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--panel', type=Path, required=True)
    p.add_argument('--index', type=Path, required=True)
    p.add_argument('--resume', action='store_true')
    args = p.parse_args()
    run(root=args.root, panel=args.panel, index=args.index, resume=args.resume)
