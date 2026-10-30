"""Forward Q10 PAPER account: frozen SUE model, Top50/75 and monthly 0.5 budget."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.refresh import SHANGHAI
from quant.data.stock_paper_inputs import read_stock_paper_calendar, read_stock_paper_inputs
from quant.execution.stock_paper import (
    ORDER_SCHEMA, _controls, _write_current_orders, _write_snapshot, advance_stock_day, reference_orders,
)
from quant.portfolio.turnover_budget import budget_targets

DEFAULT_CONFIG = Path('configs/paper/q10_sue_v2_20260913.toml')
EXECUTION_READY_HOUR = 21


def _ranked_selection(scores: pl.DataFrame, state: dict, following: dt.date, strategy: str) -> pl.DataFrame:
    date = dt.date.fromisoformat(state['date'])
    if (scores.is_empty() or scores['trade_date'].unique().to_list() != [date]
            or scores['symbol'].is_duplicated().any()
            or not scores['prediction'].is_finite().all()):
        raise ValueError('Require finite unique same-date forecasts')
    ranked = scores.sort(['prediction', 'symbol'], descending=[True, False])
    if ranked.height < 100:
        raise ValueError('Require frozen minimum 100 forecast stocks')
    previous = set(state['previous_targets'])
    retained = ranked.head(75).filter(pl.col('symbol').is_in(sorted(previous)))['symbol'].to_list()
    selected = retained + ranked.filter(~pl.col('symbol').is_in(retained)).head(50-len(retained))['symbol'].to_list()
    targets = pl.from_dicts([{'as_of': date, 'execution_date': following,
        'symbol': symbol, 'weight': .02 if symbol in selected else 0.,
        'strategy': strategy, 'strategy_version': '1'}
        for symbol in sorted(previous | set(selected))])
    state['previous_targets'] = selected
    return targets


def signal_targets(scores: pl.DataFrame, state: dict, following: dt.date) -> pl.DataFrame:
    """Same Top50/Top75 scheduled-membership buffer as the frozen replay."""
    targets = _ranked_selection(scores, state, following, 'q10_sue_v2')
    return budget_targets(targets, state, budget=.5)


def size_neutral_targets(scores: pl.DataFrame, state: dict, following: dt.date, config: dict,
                        data_root: Path = Path('data')) -> pl.DataFrame:
    """A5 b0.5_k50_size_on: same names, then |z|<=0.5 size band, then the 0.5 budget."""
    from quant.research.run_constrained_portfolio import prepare_constrained_hook

    paper = config['paper']
    targets = _ranked_selection(scores, state, following, paper['name'])
    policy = dict(paper['size_on_policy'])
    transform, _, _ = prepare_constrained_hook(
        scores=scores.rename({'prediction': 'score'}).with_columns(pl.col('trade_date')),
        targets=targets, statistics=Path(paper['statistics']), policy=policy,
        score_column='score', minimum_signal_stocks=int(policy['top_k']),
        data_root=data_root,
    )
    # prepare_constrained_hook reads score_column from the original frame's trade_date partition.
    adjusted, _info = transform(targets, state)
    return budget_targets(adjusted, state, budget=.5)


def load_forecast(folder: Path, date: dt.date, selection: Path, following: dt.date) -> pl.DataFrame:
    summary = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    daily = json.loads((folder.parent/'summary.json').read_text(encoding='utf-8'))
    if (summary['as_of'] != str(date) or summary['rehearsal']
            or Path(summary['source_selection']).resolve() != selection.resolve()
            or summary.get('input_quality_as_of') != str(date)
            or daily.get('status') != 'recorded' or daily.get('input_errors') != []
            or dt.datetime.fromisoformat(summary['recorded_at']).date() >= following):
        raise ValueError('Require successful prospective same-date frozen model quality and forecast')
    return pl.read_parquet(folder/'predictions.parquet')


def run(*, config_path: Path = DEFAULT_CONFIG, data_root: Path = Path('data'),
        output: Path = Path('artifacts/paper/q10_sue_v2'), end: dt.date,
        forecast: Path | None = None, halt: bool | None = None,
        sell_only: bool | None = None) -> dict[str, Any]:
    payload = config_path.read_text(encoding='utf-8')
    config = tomllib.loads(payload)
    paper = config['paper']
    if paper['auto_trade'] is not False or end > dt.datetime.now(SHANGHAI).date():
        raise ValueError('Paper only; no future snapshots')
    clock = dt.datetime.now(SHANGHAI)
    if end == clock.date() and end != paper['inception_date'] and clock.hour < EXECUTION_READY_HOUR:
        raise ValueError('Wait for completed daily execution inputs after 21:00 Shanghai')
    assessment = json.loads(Path(config['research']['assessment']).read_text(encoding='utf-8'))['assessments']['budgeted']
    shadow = bool(paper.get('shadow'))
    if not shadow and (assessment['conclusion'] != 'PAPER_CANDIDATE' or not all(assessment['checks'].values())):
        raise ValueError('Q10 must satisfy the registered admission criteria')
    output.mkdir(parents=True, exist_ok=True)
    frozen = output/'config.toml'
    if frozen.exists() and frozen.read_text(encoding='utf-8') != payload:
        raise ValueError('Frozen Q10 paper configuration changed')
    if not frozen.exists():
        frozen.write_text(payload, encoding='utf-8')
    controls = _controls(output, paper, halt, sell_only)
    config['paper'].update(enabled=not controls['halt'], sell_only=controls['sell_only'])
    snapshots = sorted(output.glob('????-??-??/state.json'))
    if not snapshots:
        date = paper['inception_date']
        if end < date:
            raise ValueError('Date precedes account inception')
        state = {'date': str(date), 'inception_date': str(date), 'started_with_cash': True,
            'cash': paper['initial_cash'], 'holdings': {}, 'pending': [], 'previous_targets': [],
            'receivables': [], 'restricted_shares': [], 'cumulative_fees': 0.,
            'nav': [{'date': str(date), 'unit_nav': 1., 'equity': paper['initial_cash'],
                     'cash': paper['initial_cash'], 'market_value': 0., 'receivable': 0.}],
            'auto_trade': False, 'conclusion': 'SHADOW' if shadow else 'PAPER_CANDIDATE',
            'shadow': shadow, 'counts_toward_account_limit': not shadow}
        _write_snapshot(output/str(date), state, pl.DataFrame(schema=ORDER_SCHEMA), None, None)
    else:
        state = json.loads(snapshots[-1].read_text(encoding='utf-8'))
    last = dt.date.fromisoformat(state['date'])
    if end < last:
        raise ValueError('Cannot rewind Q10 account')
    sessions = sorted(read_stock_paper_calendar(data_root).filter(pl.col('is_open'))['date'].unique().to_list())
    orders = pl.DataFrame(schema=ORDER_SCHEMA)
    for date in [day for day in sessions if last < day <= end]:
        following = next((day for day in sessions if day > date), None)
        if following is None:
            raise ValueError('Refresh exchange calendar before advancing')
        due = date.month != following.month
        scores = None
        if due:
            candidates = ([forecast] if forecast else []) + sorted(Path(config['model']['forecast_root']).glob('**/model/forecast'))
            matches = [p for p in candidates if p is not None and (p/'summary.json').exists()
                       and json.loads((p/'summary.json').read_text(encoding='utf-8')).get('as_of') == str(date)]
            if not matches:
                raise ValueError(f'Missing prospective month-end forecast: {date}')
            scores = load_forecast(matches[0], date, Path(config['model']['selection']), following)
        symbols = set(state['holdings']) | {row['symbol'] for row in state['pending']}
        symbols |= {row['symbol'] for row in state['receivables']}
        if scores is not None:
            symbols |= set(scores['symbol'])
        result, inputs = None, None
        if symbols:
            inputs = read_stock_paper_inputs(data_root, config, sorted(symbols), date)
            state, result = advance_stock_day(date=date, state=state, inputs=inputs, config=config)
        else:
            state['date'] = str(date)
            state['nav'].append({**state['nav'][-1], 'date': str(date)})
        state['date'] = str(date)
        state['pending'] = []
        if scores is not None:
            if shadow and paper.get('construction') == 'b0.5_k50_size_on':
                pending = size_neutral_targets(scores, state, following, config, data_root=data_root)
            else:
                pending = signal_targets(scores, state, following)
            state['pending'] = json.loads(pending.write_json())
        state['recorded_at'] = dt.datetime.now(SHANGHAI).isoformat()
        state.update(auto_trade=False, conclusion='SHADOW' if shadow else 'PAPER_CANDIDATE',
                     counts_toward_account_limit=not shadow)
        state['controls_at_snapshot'] = dict(controls)
        orders = reference_orders(state, inputs, config) if inputs else pl.DataFrame(schema=ORDER_SCHEMA)
        _write_snapshot(output/str(date), state, orders, result, None)
    if state['pending'] and not orders.height:
        orders = pl.read_csv(output/state['date']/'orders.csv')
        if controls['halt']:
            orders = orders.clear()
        elif controls['sell_only']:
            orders = orders.filter(pl.col('side') == 'SELL')
    _write_current_orders(output, orders, controls,
        f"{'规模中性影子' if shadow else 'Q10 SUE v2'}：{state['date']} 订单参考")
    summary = {'as_of': state['date'], 'conclusion': 'SHADOW' if shadow else 'PAPER_CANDIDATE',
        'shadow': shadow, 'counts_toward_account_limit': not shadow, 'auto_trade': False,
        'cash': state['cash'], 'positions': len(state['holdings']), 'equity': state['nav'][-1]['equity'],
        'controls': controls, 'reference_orders': orders.height, 'output': str(output)}
    (output/'latest_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    title = '规模中性影子账户' if shadow else 'Q10 第二模拟账户'
    (output/'report.md').write_text(f"# {title}\n\n{state['date']}；权益 {summary['equity']:.2f} 元；"
        f"持仓 {summary['positions']} 只；参考订单 {orders.height} 笔。\n\n月末收盘信号，下一交易日模拟成交；auto_trade=false。\n", encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--to', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--halt', action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument('--sell-only', action=argparse.BooleanOptionalAction, default=None)
    args = parser.parse_args()
    print(json.dumps(run(config_path=args.config, end=args.to, halt=args.halt, sell_only=args.sell_only)))


if __name__ == '__main__':
    main()
