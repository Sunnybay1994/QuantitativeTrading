"""Q10 observed months and frozen historical distribution, without invented overlap."""
import datetime as dt
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.stock_paper_inputs import read_stock_paper_calendar
from quant.reporting.paper_monthly import _nav
from quant.reporting.stock_paper_monthly import historical_months
from quant.research.factor_battery_cost_report import load_cost_history


def observed_months(nav: pl.DataFrame, calendar: pl.DataFrame) -> pl.DataFrame:
    frame = _nav(nav).with_columns(pl.col('date').dt.strftime('%Y-%m').alias('month'))
    sessions = calendar.filter('is_open')['date'].to_list()
    base, rows = 1., []
    for (month,), part in frame.partition_by('month', as_dict=True, maintain_order=True).items():
        expected = [d for d in sessions if d.strftime('%Y-%m') == month]
        observed = set(part['date'])
        complete = bool(expected) and set(expected).issubset(observed)
        value = float(part['unit_nav'][-1])
        rows.append({'month': month, 'first': part['date'][0], 'last': part['date'][-1],
            'observed_return': value/base-1, 'observed_points': part.height,
            'complete_month': complete, 'same_period_backtest_return': None})
        base = value
    return pl.from_dicts(rows, schema={'month': pl.String, 'first': pl.Date, 'last': pl.Date,
        'observed_return': pl.Float64, 'observed_points': pl.Int64, 'complete_month': pl.Boolean,
        'same_period_backtest_return': pl.Float64})


def run(*, account: Path, as_of: dt.date, backtest: Path, output: Path,
        data_root: Path = Path('data')) -> dict:
    snapshot = account/str(as_of)
    state = json.loads((snapshot/'state.json').read_text(encoding='utf-8'))
    if state['date'] != str(as_of) or state.get('auto_trade') is not False:
        raise ValueError('Require matching paper snapshot')
    calendar = read_stock_paper_calendar(data_root)
    paper = pl.read_csv(snapshot/'nav.csv', try_parse_dates=True)
    if paper['date'].max() != as_of:
        raise ValueError('Paper history must end at the requested session')
    observed = observed_months(paper, calendar)
    cutoff = tomllib.loads((backtest/'battery.toml').read_text(encoding='utf-8'))['run']['as_of']
    historical, _ = load_cost_history(backtest, 'budgeted', 1., cutoff)
    active = historical.filter(pl.col('market_value') > 0)['date'].min()
    historical = historical.filter(pl.col('date') >= active)
    last, first = historical['date'].max(), paper['date'].min()
    if not isinstance(last, dt.date) or not isinstance(first, dt.date):
        raise ValueError('Require dated histories')
    if last >= first:
        raise ValueError('Overlapping history requires an explicit same-period comparison')
    frozen = historical_months(historical.with_columns(pl.lit('q10').alias('fold')), calendar)
    output.mkdir(parents=True, exist_ok=False)
    observed.write_csv(output/'forward_monthly.csv')
    frozen.write_csv(output/'frozen_backtest_monthly.csv')
    summary = {'as_of': str(as_of), 'status': 'recorded', 'auto_trade': False,
        'historical_months': frozen.height, 'observed_months': observed.height,
        'complete_observed_months': observed.filter('complete_month').height,
        'historical_monthly_mean': frozen['return'].mean(), 'backtest': str(backtest),
        'same_period_comparison': 'unavailable_no_date_overlap', 'output': str(output)}
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    lines = ['# Q10 月度前向记录', '', f'截至 {as_of}；冻结回测1×成本历史完整月份 {frozen.height} 个。', '',
        '|月份|观察收益|记录点数|整月覆盖|同期回测|', '|---|---:|---:|---|---|']
    lines += [f"|{r['month']}|{r['observed_return']:.2%}|{r['observed_points']}|{'完整' if r['complete_month'] else '不完整'}|无重叠日期|" for r in observed.to_dicts()]
    lines += ['', '历史月度分布仅作背景，不能当作本月回测收益；初始化现金期与不完整月份不作策略有效性判定。',
        '[冻结历史月份](frozen_backtest_monthly.csv) · [前向月份](forward_monthly.csv)']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return summary
