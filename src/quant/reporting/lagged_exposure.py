"""Saved-fill attribution with actual holdings and strictly earlier control dates."""
import argparse
import copy
import datetime as dt
import json
import math
import tomllib
from pathlib import Path

import polars as pl

from quant.backtest.daily_account import capture_record_date_entitlements, prepare_account_actions
from quant.backtest.share_exchanges import apply_share_exchanges, capture_exchange_holdings, validate_exchanges
from quant.data.factor_battery_inputs import read_battery_execution
from quant.data.factor_benchmarks import read_etf_total_return
from quant.reporting.model_stratification import read_parts
from quant.reporting.stratified_signals import assign_strata, market_states


def reconstruct(*, nav: pl.DataFrame, trades: pl.DataFrame, bars: pl.DataFrame,
                dividends: pl.DataFrame, calendar: pl.DataFrame, initial: dict,
                share_exchanges: list[dict] | None = None) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Reconstruct positions from fills, reusing account entitlement handling.

    Security P&L is value change plus sale proceeds minus purchase cash plus
    dividend entitlement income minus fees. Slippage is already in fill prices.
    Missing quotes retain the account mark. A failed market-value check stops.
    """
    if nav['date'].is_duplicated().any() or bars.select('trade_date', 'symbol').is_duplicated().any():
        raise ValueError('Duplicate NAV or price keys')
    state = copy.deepcopy(initial)
    exchanges = validate_exchanges(share_exchanges or [])
    state.pop('nav', None)
    previous_equity = state['cash'] + sum(h['quantity']*h['mark_price'] for h in state['holdings'].values()) + sum(r['amount'] for r in state['receivables'])
    prices = {(r['trade_date'], r['symbol']): r['close'] for r in bars.iter_rows(named=True)}
    fills = trades.partition_by('date', as_dict=True)
    rows, checks = [], []
    for n in nav.sort('date').iter_rows(named=True):
        day = n['date']
        before = {s: h['quantity']*h['mark_price'] for s, h in state['holdings'].items()}
        prior_receivables: dict[str, float] = {}
        for r in state['receivables']:
            prior_receivables[r['symbol']] = prior_receivables.get(r['symbol'], 0.) + r['amount']
        converted = apply_share_exchanges(date=day, state=state, events=exchanges, dividends=dividends)
        prepared = prepare_account_actions(date=day, state=state, calendar=calendar, dividends=dividends, settle_cash=False)
        income = {s: -v for s, v in prior_receivables.items()}
        for r in prepared['receivables']:
            income[r['symbol']] = income.get(r['symbol'], 0.) + r['amount']
        prepared['cash'] += sum(r['amount'] for r in prepared['receivables'] if r['pay_date'] <= str(day))
        prepared['receivables'] = [r for r in prepared['receivables'] if r['pay_date'] > str(day)]
        flow: dict[str, float] = {}
        # A book-value transfer is not a sale or income. Subsequent mark P&L
        # belongs to the successor; prior-close exposure stays with predecessor.
        for event in converted:
            for symbol, sign in ((event['from_symbol'], 1), (event['to_symbol'], -1)):
                flow[symbol] = flow.get(symbol, 0.) + sign*event['predecessor_book_value']
        for f in fills.get((day,), trades.clear()).iter_rows(named=True):
            s = f['symbol']
            if f['side'] not in ('BUY', 'SELL'):
                raise ValueError('Unknown fill side')
            sign = 1 if f['side'] == 'BUY' else -1
            h = prepared['holdings'].setdefault(s, {'quantity': 0, 'mark_price': f['price']})
            h['quantity'] += sign*f['quantity']
            if h['quantity'] < 0:
                raise ValueError('Reconstructed negative holding')
            flow[s] = flow.get(s, 0.) - sign*f['notional'] - f['fee']
        for s in str(n.get('delisted_symbols') or '').split(','):
            if s:
                prepared['holdings'].pop(s, None)
        for s, h in prepared['holdings'].items():
            close = prices.get((day, s))
            if close is not None and math.isfinite(close) and close > 0:
                h['mark_price'] = close
        after = {s: h['quantity']*h['mark_price'] for s, h in prepared['holdings'].items() if h['quantity']}
        difference = sum(after.values()) - n['market_value']
        if abs(difference) > 1e-5:
            raise ValueError(f'Actual holding reconstruction does not reconcile on {day}: {difference}')
        total = 0.
        for s in sorted(before.keys() | after.keys() | flow.keys() | income.keys()):
            pnl = after.get(s, 0.)-before.get(s, 0.)+flow.get(s, 0.)+income.get(s, 0.)
            total += pnl
            rows.append({'date': day, 'symbol': s, 'prior_value': before.get(s, 0.),
                         'prior_weight': before.get(s, 0.)/previous_equity, 'pnl': pnl,
                         'contribution': pnl/previous_equity, 'close_quote_missing': (day, s) not in prices})
        residual = n['equity']-previous_equity-total
        checks.append({'date': day, 'prior_equity': previous_equity, 'equity': n['equity'],
                       'daily_return': n['equity']/previous_equity-1, 'security_pnl': total,
                       'residual_pnl': residual, 'residual_contribution': residual/previous_equity,
                       'market_value_difference': difference})
        state = {**state, **prepared, 'cash': n['cash'], 'date': str(day)}
        state['holdings'] = {s: h for s, h in state['holdings'].items() if h['quantity']}
        capture_record_date_entitlements(date=day, state=state, dividends=dividends)
        capture_exchange_holdings(date=day, state=state, events=exchanges)
        previous_equity = n['equity']
    return pl.from_dicts(rows), pl.from_dicts(checks)


def attribute(detail: pl.DataFrame, daily: pl.DataFrame, controls: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Monthly controls remain lagged even for same-day trades; missing stays unknown."""
    if controls.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate control keys')
    columns = ['size', 'industry', 'liquidity']
    joined = detail.sort('date').join_asof(
        controls.select('symbol', pl.col('trade_date').alias('control_date'), *columns).sort('control_date'),
        left_on='date', right_on='control_date', by='symbol', strategy='backward',
        allow_exact_matches=False, check_sortedness=False).with_columns(pl.col(columns).fill_null('unknown'),
            (pl.col('date')-pl.col('control_date')).dt.total_days().alias('control_age_days'))
    if joined.filter(pl.col('control_date') >= pl.col('date')).height:
        raise ValueError('Forward control exposure')
    frames = []
    for dimension in columns:
        frame = joined.group_by('date', dimension).agg(pl.col('prior_weight', 'pnl', 'contribution').sum())
        frames.append(frame.rename({dimension: 'stratum'}).with_columns(pl.lit(dimension).alias('dimension')))
    groups = pl.concat(frames)
    # Additive linked contributions telescope to the actual cumulative return.
    base = daily['prior_equity'][0]
    groups = groups.join(daily.select('date', 'prior_equity'), on='date', validate='m:1').with_columns(
        (pl.col('contribution')*pl.col('prior_equity')/base).alias('linked_contribution'))
    return joined, groups


def run(*, config: Path, output: Path, data_root: Path) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False:
        raise ValueError('Diagnostic cannot trade')
    source = Path(spec['source'])
    folder = source/f"replay/{spec['method']}_top50/cost_1"
    replay = json.loads((source/'replay/replay_config.json').read_text(encoding='utf-8'))
    nav = read_parts(folder, 'nav', ['date', 'equity', 'market_value', 'cash', 'delisted_symbols']).sort('date')
    first = nav.filter(pl.col('market_value') > 0)['date'].min()
    if first is None:
        raise ValueError('No actual stock holdings to attribute')
    nav = nav.filter(pl.col('date') >= first)
    start, end = nav['date'][0], nav['date'][-1]
    initial = json.loads((folder/str(start.year-1)/'account.json').read_text(encoding='utf-8'))['account']
    if initial['holdings'] or dt.date.fromisoformat(initial['date']) >= start:
        raise ValueError('Require saved cash-only prior-year account')
    trades = read_parts(folder, 'trades', ['date', 'symbol', 'side', 'quantity', 'price', 'notional', 'fee']).filter(pl.col('date') >= start)
    exchanges = replay['settings'].get('share_exchanges', [])
    exchanges = [{**e, **{k: dt.date.fromisoformat(e[k]) for k in
        ('announcement_date', 'record_date', 'effective_date', 'tradable_date')}} for e in exchanges]
    symbols = sorted(set(trades['symbol'].to_list()) | {e['to_symbol'] for e in exchanges})
    inputs = read_battery_execution(data_root=data_root, refresh_config=Path(replay['settings']['data']['refresh_config']),
        snapshot=replay['snapshot'], start=start, end=end, symbols=symbols, include_all_dividends=True)
    dividends = inputs['dividends'].with_columns((pl.col('div_cash')*(1-replay['settings']['portfolio']['stock_dividend_withholding'])).alias('div_cash'))
    detail, daily = reconstruct(nav=nav, trades=trades, bars=inputs['bars'], dividends=dividends,
                                calendar=inputs['calendar'], initial=initial, share_exchanges=exchanges)
    signal_dates = pl.concat([pl.read_parquet(p).select('trade_date').unique()
        for p in sorted(Path(spec['statistics']).glob('inputs/*/monthly_labels.parquet'))])['trade_date'].unique().to_list()
    raw = pl.concat([pl.read_parquet(p).filter(pl.col('trade_date').is_in(signal_dates)).select('symbol', 'trade_date', 'eligible', 'amount20', 'total_market_value', 'industry_l1')
                     for p in sorted(Path(spec['statistics']).glob('inputs/*/universe.parquet'))], how='vertical_relaxed')
    controls, thresholds = assign_strata(raw, quantiles=spec['quantiles'], minimum_months=12)
    detail, groups = attribute(detail, daily, controls)
    prices = read_etf_total_return(data_root=data_root, snapshot=replay['settings']['data']['etf_total_return_snapshot'], end=end)
    daily = daily.join(market_states(prices), on='date', how='left', validate='1:1')
    window = daily.filter(pl.col('date').is_between(spec['stress_start'], spec['stress_end']))
    if window.is_empty():
        raise ValueError('Empty diagnostic stress window')
    stress_groups = groups.filter(pl.col('date').is_between(spec['stress_start'], spec['stress_end'])).group_by('dimension', 'stratum').agg(
        (pl.col('pnl').sum()/window['prior_equity'][0]).alias('linked_contribution'),
        (pl.col('prior_weight').sum()/window.height).alias('mean_prior_weight'))
    summary = {'sessions': daily.height, 'security_rows': detail.height,
        'first': str(start), 'last': str(end), 'cumulative_return': daily['equity'][-1]/daily['prior_equity'][0]-1,
        'maximum_absolute_residual_cny': daily['residual_pnl'].abs().max(),
        'maximum_market_value_difference_cny': daily['market_value_difference'].abs().max(),
        'unknown_industry_rows': detail.filter(pl.col('industry') == 'unknown').height,
        'maximum_unknown_industry_weight': groups.filter((pl.col('dimension') == 'industry') & (pl.col('stratum') == 'unknown'))['prior_weight'].max(),
        'stress_return': window['equity'][-1]/window['prior_equity'][0]-1,
        'stress_residual_contribution': window['residual_pnl'].sum()/window['prior_equity'][0],
        'conclusion': 'RESEARCH_ONLY'}
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    detail.write_parquet(output/'security_daily.parquet')
    daily.write_parquet(output/'daily_reconciliation.parquet')
    groups.write_parquet(output/'daily_strata.parquet')
    groups.filter(pl.col('stratum') == 'unknown').write_csv(output/'unknown_exposures.csv')
    thresholds.write_csv(output/'thresholds.csv')
    groups.group_by('dimension', 'stratum').agg(pl.col('linked_contribution').sum(),
        (pl.col('prior_weight').sum()/daily.height).alias('mean_prior_weight')).write_csv(output/'strata_summary.csv')
    stress_groups.write_csv(output/'stress_strata.csv')
    states = []
    for dimension in ('trend', 'volatility'):
        states.append(daily.with_columns(pl.col(dimension).fill_null('unknown')).group_by(dimension).agg(
            pl.len().alias('sessions'), ((pl.col('equity')-pl.col('prior_equity')).sum()/daily['prior_equity'][0]).alias('linked_contribution'))
            .rename({dimension: 'stratum'}).with_columns(pl.lit(dimension).alias('dimension')))
    pl.concat(states).write_csv(output/'market_state_contributions.csv')
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (output/'report.md').write_text(f"# 滞后持仓归因\n\n{start} 至 {end}，{daily.height} 个交易日，累计收益 {summary['cumulative_return']:.2%}。\n\n"
        f"每日损益残差最大 {summary['maximum_absolute_residual_cny']:.6f} 元；市值重建差最大 {summary['maximum_market_value_difference_cny']:.6f} 元。\n\n"
        f"预先指定压力窗口 {spec['stress_start']} 至 {spec['stress_end']} 收益 {summary['stress_return']:.2%}，分组见 stress_strata.csv。\n\n"
        "规模、行业、流动性分别是独立分组，不能跨维度相加。分组贡献按期初资本链接；控制变量严格取交易日前最近已保存截面，缺失保留 unknown。\n\n"
        "这是会计损益分组归因，尚未进行市场/行业/风格收益回归，不能把分组损失解释成因果风险溢价。\n", encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(run(config=args.config, output=args.output, data_root=args.data_root), ensure_ascii=False))


if __name__ == '__main__':
    main()
