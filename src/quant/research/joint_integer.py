"""Replay the one preregistered lot/fee-aware rule against exact frozen controls."""
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.backtest.costs import AShareCostModel
from quant.data.stock_execution_inputs import stock_session_states
from quant.data.etf_paper_inputs import etf_session_states
from quant.portfolio.integer_construction import construct
from quant.portfolio.joint_allocation import allocate
from quant.research.classic_monthly_baseline import replay


def run(output, config):
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False or spec['capital'] != 100000:
        raise ValueError('Require frozen manual-only 100k experiment')
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    base = Path(spec['baseline']); q = Path('artifacts/models/q10_sue_v2_turnover_budget_05_20260912_01')
    etf = Path('artifacts/research/etf_allocation_attribution_20260922_03')
    manifest = {}
    def source(p):
        manifest[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
        return p
    def read(p): return pl.read_parquet(source(p))
    frames = {p.stem: read(p) for p in (base/'inputs').glob('*.parquet')}
    stock = read(q/'targets_budgeted.parquet').filter(pl.col('execution_date').is_between(spec['start'], spec['end']))
    fixed = read(etf/'fixed_1/targets.parquet').filter(pl.col('execution_date').is_between(spec['start'], spec['end']))
    columns = ['as_of', 'execution_date', 'symbol', 'weight', 'strategy', 'strategy_version']
    stock, fixed = stock.select(columns), fixed.select(columns)
    etf_names = set(fixed['symbol'])
    controls = read(Path('artifacts/portfolio/r4_constrained_q10_20260913_01/signal_controls.parquet'))
    predictions = read(Path('artifacts/models/q2_sue_context_v2_causal48_20260912_02/predictions/monthly_predictions.parquet'))
    settings = tomllib.loads(source(q/'battery.toml').read_text(encoding='utf-8'))
    settings['share_exchanges'] = tomllib.loads(source(q/'share_exchanges.toml').read_text(encoding='utf-8'))['share_exchanges']
    settings['portfolio']['initial_cash'] = spec['capital']
    cost_model = AShareCostModel(**settings['costs']['a_share'])
    calendar = read(etf/'calendar.parquet')
    sessions = calendar.filter((pl.col('market') == 'SH') & pl.col('is_open') &
        pl.col('date').is_between(stock['as_of'].min(), spec['end']))['date'].sort().to_list()
    inst = {r['symbol']: r for r in frames['joint_instruments'].to_dicts()}
    signal_days = stock['as_of'].unique().sort().to_list()
    price_by_day = {d: dict(frames['joint_bars'].filter(pl.col('trade_date') == d).select('symbol', 'close').iter_rows()) for d in signal_days}
    control_by_day = {d: controls.filter(pl.col('as_of') == d) for d in signal_days}
    scores_by_day = {d: dict(predictions.filter(pl.col('trade_date') == d).select('symbol', 'lightgbm').iter_rows()) for d in signal_days}
    if any(not scores_by_day[d] for d in signal_days): raise ValueError('Missing frozen predictions')
    for p in [config, Path(__file__), Path('src/quant/portfolio/integer_construction.py'),
              Path('src/quant/portfolio/joint_allocation.py'), Path('src/quant/research/joint_integer_report.py'),
              *[Path('src/quant/backtest')/f for f in ['daily_account.py', 'daily_simulator.py', 'costs.py']],
              Path('src/quant/research/classic_monthly_baseline.py')]: source(p)
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    cases = []; verifications = []
    for cost in spec['cost_multipliers']:
        scenario = copy.deepcopy(settings)
        scenario['costs']['etf'].update(slippage=0., slippage_per_share=.001)
        for model in scenario['costs'].values():
            for field in ['commission_rate', 'commission_min', 'slippage', 'slippage_per_share']:
                if field in model: model[field] *= cost
        states = stock_session_states(bars=frames['bars'], limits=frames['limits'], suspensions=frames['suspensions'],
            sessions=sessions, symbols=sorted(set(stock['symbol'])), execution_dates=sorted(stock['execution_date'].unique()),
            slippage=scenario['costs']['a_share']['slippage'])
        states.update(etf_session_states(frames['etf_bars'], read(etf/'dividends.parquet'), slippage=0., slippage_per_share=.001*cost))
        for name in ['joint_fixed', 'integer_fixed']:
            folder = output/f'{name}_{cost:g}'; folder.mkdir()
            targets = pl.concat([stock, fixed]).with_columns((pl.col('weight')*.5).alias('weight'),
                        pl.lit(name).alias('strategy'), pl.lit('joint_v1').alias('strategy_version'))
            trace = []; signal_states = {}; diagnostics = []; records = []; exposure = []; quantities = []; account = {}
            def transform(batch, state):
                raw = batch.with_columns((pl.col('weight')*2).alias('weight'))
                budgeted, info = allocate(raw, state, stock_fraction=.5, etf_symbols=etf_names)
                day = batch['as_of'][0]; execution = batch['execution_date'][0]
                signal_states[execution] = {**copy.deepcopy(state), 'nav': [copy.deepcopy(state['nav'][-1])]}
                if name == 'integer_fixed':
                    isolated = copy.deepcopy(state)
                    isolated['holdings'] = {s: h for s, h in state['holdings'].items() if s not in etf_names}
                    weights, deltas, rows, details = construct(raw=batch.filter(~pl.col('symbol').is_in(sorted(etf_names))),
                        budgeted=budgeted.filter(~pl.col('symbol').is_in(sorted(etf_names))), state=isolated,
                        market=control_by_day[day], prices=price_by_day[day], instruments=inst,
                        scores=scores_by_day[day], costs=cost_model, spec=spec)
                    budgeted = budgeted.with_columns(pl.Series('weight', [weights.get(r['symbol'], r['weight']) for r in budgeted.to_dicts()]))
                    # Same original joint policy: unavoidable retained stock has priority;
                    # cap ETF capacity rather than allowing leverage after a frozen hold.
                    capacity = max(0., min(.5, 1-sum(weights.values())))
                    etf_weights = dict(raw.filter(pl.col('symbol').is_in(sorted(etf_names))).select('symbol','weight').iter_rows())
                    budgeted = budgeted.with_columns(pl.Series('weight', [
                        etf_weights[r['symbol']]*capacity if r['symbol'] in etf_names else r['weight']
                        for r in budgeted.to_dicts()]))
                    info.update(target_share_deltas=deltas, construction=details)
                else:
                    desired = dict(batch.select('symbol', 'weight').iter_rows())
                    rows = []
                    market = {r['symbol']: r for r in control_by_day[day].to_dicts()}
                    for r in budgeted.filter(~pl.col('symbol').is_in(sorted(etf_names))).to_dicts():
                        s = r['symbol']; h = state['holdings'].get(s, {}); p = price_by_day[day].get(s)
                        lot = inst[s]['board_lot']; m = market.get(s, {})
                        rows.append(dict(symbol=s, signal_price=p, valuation_mark=p or h.get('mark_price'),
                            price_complete=p is not None, risk_complete=m.get('size') is not None,
                            industry=m.get('industry_l1'), size=m.get('size'), board_lot=lot,
                            score=scores_by_day[day].get(s), current_quantity=h.get('quantity', 0),
                            raw_weight=desired.get(s, 0.), budget_weight=r['weight'],
                            naive_integer_quantity=int(r['weight']*state['nav'][-1]['equity']/p//lot)*lot if p else None,
                            below_one_lot=bool(p and 0 < r['weight']*state['nav'][-1]['equity'] < lot*p)))
                for r in rows:
                    trace.append(dict(as_of=day, execution_date=execution, signal_equity=state['nav'][-1]['equity'], **r))
                return budgeted, info
            def observe(date, state):
                mv = {s: h['quantity']*h['mark_price'] for s, h in state['holdings'].items()}
                exposure.append(dict(date=date, stock_value=sum(v for s, v in mv.items() if s not in etf_names),
                    etf_value=sum(v for s, v in mv.items() if s in etf_names), cash=state['cash']))
                if date in signal_states:
                    for s, h in state['holdings'].items(): quantities.append(dict(date=date, symbol=s, **h))
            nav, trades, rejects = replay(bars=frames['joint_bars'], calendar=calendar, instruments=frames['joint_instruments'],
                targets=targets, dividends=frames['joint_dividends'], market_states=states, config=scenario, sessions=sessions,
                name=name, validate_once=True, account_state=account, target_constraints=transform, constraint_records=records,
                constraint_diagnostics=diagnostics, daily_observer=observe)
            nav = nav.filter(pl.col('date') >= spec['start'])
            from quant.research.joint_integer_report import finish_trace
            trace = finish_trace(trace, signal_states, nav, trades, rejects, frames['joint_bars'], calendar,
                                 frames['joint_dividends'], inst, name)
            for label, frame in [('nav', nav), ('trades', trades), ('rejections', rejects), ('targets', pl.DataFrame(records)),
                ('loss_trace', pl.from_dicts(trace, infer_schema_length=None)), ('exposure', pl.DataFrame(exposure)),
                ('execution_holdings', pl.DataFrame(quantities))]: frame.write_parquet(folder/f'{label}.parquet')
            (folder/'diagnostics.json').write_text(json.dumps(diagnostics, default=str), encoding='utf-8')
            (folder/'account.json').write_text(json.dumps(account, default=str), encoding='utf-8')
            identity = (nav['equity']-nav['cash']-nav['market_value']-nav['receivable']).abs().max()
            verification = dict(rule=name, cost=cost, equity_error=identity,
                min_cash=nav['cash'].min(), fee_error=abs(trades['fee'].sum()-nav['cumulative_fees'][-1]),
                duplicate_net_fills=trades.select('date','symbol').is_duplicated().sum())
            if name == 'joint_fixed':
                oldnav = read(base/f'{name}_{cost:g}/nav.parquet')
                oldtrades = read(base/f'{name}_{cost:g}/trades.parquet')
                verification['frozen_nav_equal'] = nav.equals(oldnav)
                verification['frozen_trades_equal'] = trades.equals(oldtrades)
                if not nav.equals(oldnav) or not trades.equals(oldtrades): raise ValueError('Control replay drift')
            if identity > 1e-6 or verification['min_cash'] < -.001 or verification['fee_error'] > 1e-6 or verification['duplicate_net_fills']:
                raise ValueError('Account verification failed')
            verifications.append(verification); cases.append(dict(rule=name, cost=cost))
            (output/'progress.json').write_text(json.dumps(dict(completed=cases), indent=2))
            (output/'verification.json').write_text(json.dumps(verifications, indent=2))
            print(json.dumps(dict(rule=name, cost=cost, status='complete')), flush=True)
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    from quant.research.joint_integer_report import report
    report(output, spec, cases)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path('configs/research/joint_integer_v1.toml'))
    args = parser.parse_args(); run(args.output, args.config)
