"""Read-only lagged state diagnostics across frozen mechanisms; no selection or trading."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

DIMENSIONS = ['market_state', 'liquidity_state', 'sentiment_state', 'volatility_state']


def holding_window(nav, trades):
    """Keep first-entry P&L and later cash, using saved position/trade evidence."""
    if nav[['position_count', 'market_value']].isna().any().any():
        raise ValueError('Missing position evidence')
    held = (nav.position_count > 0) | (nav.market_value > 0)
    buys = trades.loc[(trades.side == 'BUY') & (trades.quantity > 0), 'date']
    first_buy = buys.min() if len(buys) else pd.NaT
    candidates = nav.index[held | nav.index.isin(buys)]
    if not len(candidates):
        raise ValueError('Account has no verified holding')
    first = candidates.min()
    if pd.isna(first_buy) or first_buy != first:
        raise ValueError('First holding lacks matching initial BUY evidence')
    result = nav.copy()
    # The liquidation day still has exposure even with no closing position.
    result['holding_exposure'] = held | held.shift(1, fill_value=False) | nav.index.isin(
        trades.loc[trades.quantity > 0, 'date'])
    audit = dict(first_holding=str(first.date()), first_buy=str(first_buy.date()),
                 excluded_prefix_rows=int((nav.index < first).sum()),
                 retained_cash_rows=int((~result.loc[first:, 'holding_exposure']).sum()),
                 evidence='position_count/market_value plus actual BUY; prior-close NAV retained as return anchor')
    return result.loc[first:].copy(), audit


def event_metrics(frame):
    if not frame.holding_exposure.any():
        return dict(applicable=False, reason='no_holding_exposure', event_return=None, max_drawdown=None)
    wealth = np.r_[1., (1+frame['return']).cumprod().to_numpy()]
    return dict(applicable=True, reason=None, event_return=float(wealth[-1]-1),
                max_drawdown=float((wealth/np.maximum.accumulate(wealth)-1).min()))


def align_states(returns, states):
    if states['effective_date'].duplicated().any() or not (states.effective_date > states.trade_date).all():
        raise ValueError('Require unique next-session state dates')
    return returns.join(states.set_index('effective_date')[DIMENSIONS], how='left').fillna(
        {name: 'unknown' for name in DIMENSIONS})


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    manifest = {}

    def read(path):
        manifest[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return pl.read_parquet(path).to_pandas()

    def account(folder):
        paths = sorted(folder.glob('*/nav.parquet')) or list(folder.glob('nav.parquet'))
        if not paths:
            raise ValueError(f'No saved account: {folder}')
        nav = pd.concat([read(p) for p in paths]).sort_values('date').set_index('date')
        if nav.index.duplicated().any() or (nav.equity <= 0).any():
            raise ValueError('Invalid frozen account dates or equity')
        nav['return'] = nav.equity.pct_change(fill_method=None)
        nav['cash_fraction'] = nav.cash / nav.equity
        trades = [p.with_name('trades.parquet') for p in paths]
        if all(p.exists() for p in trades):
            trade = pd.concat([read(p) for p in trades])
            totals = trade.groupby('date')[['notional', 'fee', 'slippage_cost']].sum()
            for field in totals:
                nav[field + '_fraction'] = totals[field].reindex(nav.index, fill_value=0) / nav.equity.shift(1)
        else:
            raise ValueError('Missing saved trades for holding-period verification')
        return holding_window(nav, trade)

    root = Path('artifacts/research/market_indicators_20260922_02')
    states = read(root/'market_states.parquet')
    benchmark = read(root/'benchmark.parquet').set_index('date').unit_nav.pct_change(fill_method=None)
    battery = Path('artifacts/factors/nightly_batches/6b35e47b1f0dcf04/evaluation')
    # No verified fully invested equal-weight return index in this frozen input
    # contract. An integer-lot account is not an index; never substitute it.
    sources = {
        'Q10': Path('artifacts/models/q10_sue_v2_turnover_budget_05_20260912_01/budgeted'),
        'pressure_raw': battery/'costs/pressure_reversal_high_amount_v1/raw',
        'pressure_neutral': battery/'costs/pressure_reversal_high_amount_v1/size_industry_neutral',
    }
    allocation = Path('artifacts/research/etf_allocation_attribution_20260922_03')
    panels, slices, episodes, exposures, holding_audits = [], [], [], [], []
    for cost in (.5, 1., 2.):
        folders = {name: folder/f'cost_{cost:g}' for name, folder in sources.items()}
        folders.update({f'ETF_{rule}': allocation/f'{rule}_{cost:g}' for rule in ('fixed', 'dynamic')})
        for name, folder in folders.items():
            nav, audit = account(folder)
            holding_audits.append(dict(strategy=name, cost=cost, **audit))
            frame = align_states(nav, states)
            frame['market_return'] = benchmark.reindex(frame.index)
            frame['equal_weight_minus_market_proxy'] = np.nan
            frame['strategy'], frame['cost'] = name, cost
            frame['year'] = frame.index.year
            panels.append(frame.reset_index())
            for dimension in DIMENSIONS:
                for (year, state), selected in frame.groupby(['year', dimension]):
                    slices.append(dict(strategy=name, cost=cost, year=year, dimension=dimension,
                        state=state, sessions=int(selected['return'].count()),
                        mean_daily_bps=selected['return'].mean()*10000,
                        cash_fraction=selected.cash_fraction.mean(),
                        gross_traded_equity=selected.get('notional_fraction', pd.Series(dtype=float)).sum(min_count=1),
                        fee_equity=selected.get('fee_fraction', pd.Series(dtype=float)).sum(min_count=1),
                        slippage_equity=selected.get('slippage_cost_fraction', pd.Series(dtype=float)).sum(min_count=1)))
                # Event boundaries are defined on the full state calendar, before strategy filtering.
                ordered = states.set_index('effective_date')[dimension]
                groups = ordered.ne(ordered.shift()).cumsum()
                for _, event in ordered.groupby(groups):
                    if not event.index.isin(frame.index).all():
                        continue
                    r = frame.loc[event.index, 'return']
                    if r.isna().any():
                        continue
                    episodes.append(dict(strategy=name, cost=cost, dimension=dimension,
                        state=event.iloc[0], start=str(event.index[0].date()), end=str(event.index[-1].date()),
                        sessions=len(r), **event_metrics(frame.loc[event.index])))
            for year, selected in frame.groupby('year'):
                sample = selected[['return', 'market_return']].dropna()
                beta = [None, None]
                if len(sample) >= 60:
                    x = np.column_stack([np.ones(len(sample)), sample.iloc[:, 1:].to_numpy()])
                    if np.linalg.matrix_rank(x) == 2:
                        beta = np.linalg.lstsq(x, sample['return'].to_numpy(), rcond=None)[0].tolist()
                exposures.append(dict(strategy=name, cost=cost, year=year, sessions=len(sample),
                    daily_intercept=beta[0], market_beta=beta[1], size_proxy_beta=None,
                    size_proxy_status='unavailable_verified_return_index_not_in_frozen_inputs'))
    pd.concat(panels).to_csv(output/'daily_panel.csv', index=False)
    pd.DataFrame(slices).to_csv(output/'annual_state_slices.csv', index=False)
    pd.DataFrame(episodes).to_csv(output/'continuous_events.csv', index=False)
    pd.DataFrame(exposures).to_csv(output/'annual_exposure.csv', index=False)
    pd.DataFrame(holding_audits).to_csv(output/'holding_period_audit.csv', index=False)
    monthly = read(Path('artifacts/research/q7_sue_v2_incremental_ic_20260912_01/monthly_incremental_ic.parquet'))
    # Monthly factor signals are formed after this close and executed next session.
    monthly = monthly.merge(states[['trade_date', 'effective_date', *DIMENSIONS]], on='trade_date', how='left', validate='m:1')
    monthly.to_csv(output/'monthly_state_ic.csv', index=False)
    ic_rows = []
    monthly['year'] = monthly.trade_date.dt.year
    for dimension in DIMENSIONS:
        for keys, selected in monthly.fillna({dimension: 'unknown'}).groupby(['factor', 'year', dimension]):
            ic_rows.append(dict(factor=keys[0], year=keys[1], dimension=dimension, state=keys[2],
                months=len(selected), raw_rank_ic=selected.raw_rank_ic.mean(), partial_rank_ic=selected.partial_rank_ic.mean()))
    pd.DataFrame(ic_rows).to_csv(output/'monthly_ic_by_year_state.csv', index=False)
    manifest[str(Path(__file__))] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (output/'source_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    result = dict(status='complete', auto_trade=False, changes_positions=False, historical_is_development=True,
                  account_cost_pairs=15, annual_slices=len(slices), continuous_events=len(episodes),
                  monthly_factor_rows=len(monthly), missing=['full-market live quotes', 'net-order fixed-combination replay',
                  'factor-family mapping beyond existing Q7 inputs', 'original historical available_at',
                  'verified equal-weight return index for size proxy'])
    (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (output/'report.md').write_text('# 滞后市场状态跨机制诊断\n\n'
        '复用冻结Q10、压力反转原始/中性化、ETF固定/动态账户；三档成本。无重跑、无状态择优或仓位切换。\n\n'
        + pd.DataFrame([result]).drop(columns=['missing']).to_markdown(index=False)
        + '\n\nannual_state_slices.csv：各年各状态日均收益、现金、交易额与费用占净值比。非连续状态不算年化收益或夏普。'
        '\n\ncontinuous_events.csv：原完整状态日历定义的连续事件；只保留账户完整覆盖事件，不拼接缺日。'
        '\n\nannual_exposure.csv：仅保留事后年度市场beta；规模代理留空，冻结输入未核实合格等权收益指数，禁止用低仓位整手账户替代。不是因果归因或可交易超额。'
        '\n\nmonthly_state_ic.csv / monthly_ic_by_year_state.csv：接既有Q7月度原始与增量IC，使用信号收盘状态和下一日生效日期；不将稀疏状态月份当连续时间检验。'
        '\n\nholding_period_audit.csv：原始持仓数量/市值与BUY成交交叉确认首持，剔除首持前现金前缀，首持后现金保留；收益在截断前计算，保留首持日损益。没有任何持仓暴露的事件标不适用，收益及回撤留空。原账户首条净值若无前日锚点，收益留空。ETF短样本、各账户区间不同，不能据切片排名挑选赢家。'
        '\n\n尚未完成：固定跨机制组合净订单回放与真实全市场盘中字段。历史重建不证明当时可获得；本报告不构成准入。\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(run(parser.parse_args().output)))
