"""User-authorized rejected Top15 observations on the existing stock PAPER ledger."""
import argparse
import copy
import datetime as dt
import json
import tomllib
from dataclasses import replace
from pathlib import Path

import polars as pl

from quant.backtest.costs import AShareCostModel
from quant.backtest.daily_account import prepare_account_actions
from quant.backtest.daily_simulator import _validate_or_empty_trades
from quant.data.refresh import SHANGHAI
from quant.data.stock_paper_inputs import read_stock_paper_calendar, read_stock_paper_inputs
from quant.execution.preposted_book import PrepostedBook
from quant.execution.q10_paper import load_forecast
from quant.execution.stock_paper import ORDER_SCHEMA, _controls, _write_snapshot, advance_stock_day
from quant.portfolio.top15_limit import targets

DEFAULT_CONFIG = Path('configs/paper/top15_limit_1pct_observation_20261106.toml')
DEFAULT_OUTPUT = Path('artifacts/paper/top15_limit_1pct_observation')


def load_book(state):
    book = PrepostedBook()
    if state.get('limit_book'):
        book.__dict__.update(copy.deepcopy(state['limit_book']))
    if book.maximum != 3 or book.awaiting:
        raise ValueError('Require settled three-session limit book')
    return book


def limit_orders(state, book, following, config, controls):
    rows = []
    cash = state['cash']
    model = AShareCostModel(**config['costs']['a_share'])
    for order in sorted(book.orders, key=lambda row: (row['side'] != 'SELL', row['symbol'])):
        if order['status'] != 'pending' or controls['halt'] or controls['sell_only'] and order['side'] == 'BUY':
            continue
        quantity = order['remaining']
        price = order['limit']
        fee = model.fee(quantity * price, following, order['side'])
        cash += quantity * price - fee if order['side'] == 'SELL' else -(quantity * price + fee)
        rows.append(dict(as_of=order['signal'], execution_date=str(following), symbol=order['symbol'],
            side=order['side'], quantity=quantity, board_lot=100, reference_price=order['signal_close'],
            estimated_fill_price=price, estimated_notional=quantity * price, estimated_fee=fee,
            cash_after=cash, limit_price=price, attempts_remaining=3-order['attempts']))
    if not rows:
        return pl.DataFrame(schema={**ORDER_SCHEMA, 'limit_price': pl.Float64, 'attempts_remaining': pl.Int64})
    return pl.from_dicts(rows)


def save(output, state, book, orders, result, controls):
    state.update(auto_trade=False, conclusion='REJECTED', research_conclusion='REJECTED',
                 observation_only=True, shadow=True, counts_toward_account_limit=False,
                 limit_book=copy.deepcopy(book.__dict__), controls_at_snapshot=dict(controls))
    _write_snapshot(output/state['date'], state, orders, result, None)
    fills = output/state['date']/'fills.csv'
    if result is None and state.get('daily_trade_count') == 0 and not fills.exists():
        _validate_or_empty_trades([]).write_csv(fills)
    orders.write_csv(output/'latest_orders.csv')
    lines = ['# Top15·30万元·1%限价：仅观察，REJECTED', '',
        f"记录日 {state['date']}；净值 {state['nav'][-1]['unit_nav']:.6f}；"
        f"权益 {state['nav'][-1]['equity']:.2f}元；持仓 {len(state['holdings'])}只。", '',
        '未通过策略准入；auto_trade=false。月末收盘信号，下一交易日起最多尝试3个交易日。',
        '限价锚定原信号收盘；仅模拟撮合，不提交券商、不推送委托。现金初始化不代表已完成当日行情观测。',
        '表内为原剩余股数及限价报价；账本另计原滑点和手续费，实际受现金、整手与成交量约束，不能保证全额成交。', '',
        '|执行日|证券|方向|剩余股数|限价|剩余尝试日|', '|---|---|---|---:|---:|---:|']
    lines.extend(f"|{r['execution_date']}|{r['symbol']}|{r['side']}|{r['quantity']}|"
                 f"{r['limit_price']:.2f}|{r['attempts_remaining']}|" for r in orders.iter_rows(named=True))
    if orders.is_empty():
        lines.append('\n暂无待模拟委托；不补做账户建立前的过期信号。')
    text = '\n'.join(lines)+'\n'
    for path in (output/'latest_orders.md', output/'report.md', output/state['date']/'orders.md'):
        path.write_text(text, encoding='utf-8')
    summary = dict(as_of=state['date'], conclusion='REJECTED', research_conclusion='REJECTED',
        observation_only=True, shadow=True, counts_toward_account_limit=False, auto_trade=False,
        cash=state['cash'], equity=state['nav'][-1]['equity'], positions=len(state['holdings']),
        reference_orders=orders.height, controls=controls, output=str(output), phase=state.get('phase'))
    summary['rehearsal'] = bool(state.get('rehearsal'))
    (output/'latest_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def run(*, config_path=DEFAULT_CONFIG, data_root=Path('data'), output=DEFAULT_OUTPUT,
        end, forecast=None, as_month_end=False):
    payload = Path(config_path).read_text(encoding='utf-8')
    config = tomllib.loads(payload)
    paper = config['paper']
    assessment = json.loads(Path(config['research']['assessment']).read_text(encoding='utf-8'))
    if (paper['auto_trade'] is not False or paper.get('observation_only') is not True
            or paper.get('shadow') is not True or paper.get('counts_toward_account_limit') is not False
            or paper['initial_cash'] != 300000 or config['research']['conclusion'] != 'REJECTED'
            or config['research']['variant'] != 'limit_1pct'
            or assessment['assessments']['limit_1pct']['conclusion'] != 'REJECTED'):
        raise ValueError('Require user-authorized 300k REJECTED observation; no admission promotion')
    now = dt.datetime.now(SHANGHAI)
    if end > now.date() or end < paper['inception_date']:
        raise ValueError('Account observations require actual dates on/after inception')
    if end == now.date() and end > paper['inception_date'] and now.hour < 21:
        raise ValueError('Wait for completed daily execution inputs after 21:00 Shanghai')
    if as_month_end and 'rehearsal' not in Path(output).resolve().parts:
        raise ValueError('Forced monthly signals require an isolated rehearsal')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    frozen = output/'config.toml'
    if frozen.exists() and frozen.read_text(encoding='utf-8') != payload:
        raise ValueError('Frozen observation configuration changed')
    if not frozen.exists():
        frozen.write_text(payload, encoding='utf-8')
    controls = _controls(output, paper, None, None)
    config['paper'].update(enabled=not controls['halt'], sell_only=controls['sell_only'])
    snapshots = sorted(output.glob('????-??-??/state.json'))
    if snapshots:
        state = json.loads(snapshots[-1].read_text(encoding='utf-8'))
    else:
        day = str(paper['inception_date'])
        state = dict(date=day, inception_date=day, started_with_cash=True, cash=300000., holdings={},
            pending=[], previous_targets=[], receivables=[], restricted_shares=[], cumulative_fees=0.,
            daily_trade_count=0,
            phase='cash_initialization', registered_at=now.isoformat(),
            nav=[dict(date=day, unit_nav=1., equity=300000., cash=300000., market_value=0., receivable=0.)])
    last = dt.date.fromisoformat(state['date'])
    if state.get('phase') == 'cash_initialization':
        state.setdefault('daily_trade_count', 0)
    if end < last:
        raise ValueError('Cannot rewind observation account')
    calendar = read_stock_paper_calendar(data_root)
    sessions = sorted(calendar.filter(pl.col('is_open'))['date'].unique().to_list())
    if as_month_end and (last >= end or end not in sessions):
        raise ValueError('Rehearsal requires an open session after the preceding snapshot')
    book = load_book(state)
    orders = limit_orders(state, book, next(d for d in sessions if d > last), config, controls)
    result = None
    for day in [d for d in sessions if last < d <= end]:
        result = None
        following = next(d for d in sessions if d > day)
        due = day.month != following.month or as_month_end and day == end
        scores = None
        if due:
            candidates = ([Path(forecast)] if forecast else []) + sorted(
                Path(config['model']['forecast_root']).glob('**/model/forecast'))
            matches = [p for p in candidates if (p/'summary.json').exists()
                and json.loads((p/'summary.json').read_text())['as_of'] == str(day)]
            if not matches:
                raise ValueError(f'Missing prospective monthly forecast: {day}')
            scores = load_forecast(matches[0], day, Path(config['model']['selection']), following)
        symbols = set(state['holdings']) | {o['symbol'] for o in book.orders if o['status'] == 'pending'}
        symbols |= {r['symbol'] for r in state['receivables']}
        if scores is not None:
            symbols |= set(scores['symbol'])
        inputs = None
        if symbols:
            gross_config = copy.deepcopy(config)
            gross_config['portfolio']['stock_dividend_withholding'] = 0.
            inputs = read_stock_paper_inputs(data_root, gross_config, sorted(symbols), day)
            book.apply_actions(day, inputs.dividends)
            inputs = replace(inputs, dividends=inputs.dividends.with_columns((pl.col('div_cash') *
                (1-config['portfolio']['stock_dividend_withholding'])).alias('div_cash')))
            removed = set(inputs.instruments.filter(pl.col('delist_date') < day)['symbol'])
            for order in book.orders:
                if order['symbol'] in removed and order['status'] == 'pending':
                    order['status'] = 'delisted'
            prepared = prepare_account_actions(date=day, state=state, calendar=inputs.calendar,
                                                dividends=inputs.dividends)
            fixed, limits = book.attempt(day, holdings=prepared['holdings'])
            state['pending'] = []
            selected = list(state['previous_targets'])
            state, result = advance_stock_day(date=day, state=state, inputs=inputs, config=config,
                                               scheduled_orders=fixed, preposted_limits=limits)
            state['previous_targets'] = selected
            book.settle(result.trades)
        else:
            state['date'] = str(day)
            state['nav'].append({**state['nav'][-1], 'date': str(day)})
        state['date'] = str(day)
        state['daily_trade_count'] = result.trades.height if result is not None else 0
        state['pending'] = []
        if scores is not None:
            closes = dict(inputs.bars.filter(pl.col('trade_date') == day).select('symbol', 'close').iter_rows())
            for symbol, holding in state['holdings'].items():
                closes.setdefault(symbol, holding['mark_price'])
            target, selected = targets(scores=scores, previous=state['previous_targets'], closes=closes,
                equity=state['nav'][-1]['equity'], execution_date=following)
            book.replace(signal=day, targets=target, holdings=state['holdings'],
                         equity=state['nav'][-1]['equity'], closes=closes, offset=.01)
            state['pending'] = json.loads(target.write_json())
            state['previous_targets'] = selected
        state['phase'] = 'rehearsal' if as_month_end else 'daily_observation'
        if as_month_end:
            state['rehearsal'] = True
        state['recorded_at'] = dt.datetime.now(SHANGHAI).isoformat()
        orders = limit_orders(state, book, following, config, controls)
        save(output, state, book, orders, result, controls)
    return save(output, state, book, orders, result, controls)


def observe_from_daily(spec, *, end, data_root, forecast=None):
    """A rejected observation failure never blocks admitted accounts or sends orders."""
    try:
        config = tomllib.loads(Path(spec['config']).read_text(encoding='utf-8'))
        if end < config['paper']['inception_date']:
            return dict(status='not_started', inception=str(config['paper']['inception_date']))
        result = run(config_path=Path(spec['config']), output=Path(spec['output']),
                     data_root=data_root, end=end, forecast=forecast)
        return dict(status='complete', result=result)
    except Exception as exc:
        return dict(status='failed', error=f'{type(exc).__name__}: {exc}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--to', type=dt.date.fromisoformat, required=True)
    parser.add_argument('--forecast', type=Path)
    parser.add_argument('--as-month-end', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(config_path=args.config, output=args.output, end=args.to,
        forecast=args.forecast, as_month_end=args.as_month_end), ensure_ascii=False))


if __name__ == '__main__':
    main()
