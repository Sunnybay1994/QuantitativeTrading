"""R6 first observed-vintage battery intake; never manufacture historical events."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.event_family_r6_inputs import read_sources, read_monthly
from quant.factors.event_family_r6 import SIGNALS, SOURCES, compute
from quant.research.factor_battery_evaluation import score_factor_sections
from quant.research.factor_battery_statistics import rank_ic_by_date, monthly_ic_summary
from quant.research.factor_battery_screen import screen_statistics
from quant.research.factor_battery_scorecard import assemble_scorecard
from quant.research.nightly_steps import incremental_statistics


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)


def run(*, config: Path, output: Path, register=False):
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if (spec['auto_trade'] is not False or tuple(spec['signals']) != SIGNALS
            or spec['variants'] != ['raw', 'size_industry_neutral']
            or spec['cost_multipliers'] != [.5, 1., 2.]):
        raise ValueError('Use the complete frozen R6 family and original costs')
    output.mkdir(parents=True, exist_ok=False)
    frozen = digest(config)
    (output/'definition.toml').write_bytes(config.read_bytes())
    now = dt.datetime.now(dt.timezone.utc)
    events, paths, facts = read_sources(Path(spec['data_root']), now)
    (output/'source_facts.json').write_text(json.dumps(facts, indent=2), encoding='utf-8')
    cutoff = dt.datetime.combine(spec['end'], dt.time(15), dt.timezone(dt.timedelta(hours=8)))
    historical = {t: f.filter((pl.col('available_at') <= cutoff) & (pl.col('observed_at') <= cutoff))
                  if f.width else f for t, f in events.items()}
    historical_counts = {t: f.height for t, f in historical.items()}
    if any(historical_counts.values()):
        raise ValueError('Historical observable rows now exist; this zero-history intake cannot replace a full mature battery')
    report = events['report_rc']
    analyst_fields = {'org_name', 'author_name', 'quarter', 'eps', 'source_announcement_date'}
    analyst = {'native_fields_present': analyst_fields <= set(report.columns),
               'unit': 'EPS CNY/share; dimensionless relative revision', 'permission': facts['report_rc']['permissions']}
    if analyst['native_fields_present']:
        valid = report.filter(pl.col('org_name').is_not_null() & pl.col('author_name').is_not_null()
            & pl.col('quarter').str.contains(r'^\d{4}Q[1-4]$') & pl.col('eps').is_finite())
        groups = valid.group_by('ts_code', 'org_name', 'author_name', 'quarter').agg(
            pl.col('source_announcement_date').n_unique().alias('publication_dates'))
        analyst.update(valid_native_rows=valid.height, same_identity_multi_date_groups=groups.filter(
            pl.col('publication_dates') >= 2).height)
    del events
    panel, input_paths = read_monthly(Path(spec['historical_inputs']), spec['start'], spec['end'])
    settings = tomllib.loads(Path(spec['battery']).read_text(encoding='utf-8'))
    controls_path = Path(spec['control_source'])/'summary.json'
    controls = sorted({f for row in json.loads(controls_path.read_text(encoding='utf-8'))['annual_fits']
                       for f in row.get('factors', [])})
    paths += input_paths+[config, Path(spec['battery']), controls_path, Path(__file__),
        Path('src/quant/factors/event_family_r6.py'), Path('src/quant/data/event_family_r6_inputs.py')]
    manifest = {str(p): digest(p) for p in sorted(set(paths))}
    save(output/'source_manifest.json', manifest)
    save(output/'pipeline_config.json', {'family': spec['id'], 'definition_sha256': frozen,
        'battery': Path(spec['battery']).read_text(encoding='utf-8'), 'observed_at': now.isoformat(),
        'sample_cutoff': str(spec['end']), 'controls': controls, 'auto_trade': False})
    statistics, increments, costs = [], [], []
    for name in SIGNALS:
        values = compute(keys=panel, events=historical[SOURCES[name]], name=name)
        if values['value'].count():
            raise ValueError('Unexpected historical signal from post-cutoff observed data')
        scores = score_factor_sections(universe=panel.with_columns(pl.lit(True).alias('eligible')),
            values=values, direction=1, settings=settings)
        joined = scores.join(panel.select('symbol', 'trade_date', 'label_rebalance'),
                             on=['symbol', 'trade_date'], how='left', validate='1:1')
        for variant in settings['variants']:
            ic = rank_ic_by_date(joined, score=variant, label='label_rebalance',
                minimum_symbols=settings['minimum_symbols'],
                minimum_paired_coverage=settings['minimum_paired_coverage'])
            folder = output/name/variant
            folder.mkdir(parents=True)
            ic.write_parquet(folder/'monthly_ic.parquet')
            stats = monthly_ic_summary(ic['trade_date'].to_list(), ic['rank_ic'].to_list(),
                                      lag=settings['monthly_newey_west_lag'])
            statistics.append({'factor': name, 'variant': variant, **stats,
                               'group_statistics': {'long_short_sharpe': None}})
            # No finite candidate pairs: controls are identified but not fabricated or imputed.
            empty = pl.DataFrame(schema={'symbol': pl.String, 'trade_date': pl.Date, 'label': pl.Float64,
                                          'candidate': pl.Float64, **{c: pl.Float64 for c in controls}})
            incremental = incremental_statistics(empty, 'candidate', controls, 1)
            increments.append({'factor': name, 'variant': variant, 'controls': controls,
                'status': 'not_estimable_no_mature_candidate_pairs', **incremental})
            for cost in settings['portfolio']['cost_multipliers']:
                costs.append({'factor': name, 'variant': variant, 'cost_multiplier': cost,
                    'executed': False, 'cagr': None, 'sharpe': None, 'max_drawdown': None,
                    'reason': 'no_observable_historical_signal; no executable top group; not a zero-return strategy'})
    table = pl.from_dicts(statistics, infer_schema_length=None).with_columns(
        pl.col('icir', 'p_value', 'newey_west_t', 'yearly_positive_fraction').cast(pl.Float64),
        pl.col('group_statistics').cast(pl.Struct({'long_short_sharpe': pl.Float64})))
    screen = screen_statistics(table, factors=list(SIGNALS), settings=settings)
    scorecard = assemble_scorecard(screen, cost_reports=[], correlations=None, settings=settings)
    scorecard = scorecard.with_columns(pl.lit('RESEARCH_ONLY').alias('conclusion'),
        pl.lit('insufficient_observed_history_not_strategy_performance_failure').alias('r6_reason'),
        pl.lit(False).alias('factor_admitted'), pl.lit(True).alias('closed_this_round'))
    table.write_parquet(output/'statistics.parquet')
    screen.write_parquet(output/'statistical_screen.parquet')
    scorecard.write_parquet(output/'scorecard.parquet')
    pl.from_dicts(costs).write_parquet(output/'cost_plan.parquet')
    save(output/'incremental.json', increments)
    if digest(config) != frozen or any(digest(Path(p)) != value for p, value in manifest.items()):
        raise ValueError('Frozen R6 sources changed during intake')
    summary = {'family': spec['id'], 'definition_sha256': frozen, 'auto_trade': False,
        'implementation_complete': True, 'acceptance_complete': False,
        'factors': len(SIGNALS), 'variant_rows': scorecard.height, 'admitted_factors': 0,
        'qualified_months': 0, 'historical_visible_native_rows': historical_counts,
        'original_monthly_dates': panel['trade_date'].n_unique(), 'original_eligible_rows': panel.height,
        'n3': 'Original monthly scoring/statistical screen executed; no estimable history. '
              'Daily decay/group/cost execution inapplicable, not manufactured.',
        'n4': 'Control identities resolved from Q10 source fits; no finite candidate pairs; NW-t null, no estimate.',
        'analyst_native_support': analyst, 'repurchase_incremental_nw_t': None,
        'costs_requested': [.5, 1., 2.], 'costs_executed': False,
        'scorecard_path': str((output/'scorecard.parquet').resolve()),
        'cost_runs': [], 'cost_failures': [], 'pending_external_runs': [],
        'closure': 'All columns closed this round for input-history insufficiency; no rescue or historical availability backfill.'}
    save(output/'summary.json', summary)
    lines = ['# R6 事件族系首轮留存与电池回执', '',
        f'冻结定义 SHA-256：`{frozen}`；10列×原始/规模行业中性化两版本。', '',
        f"真实原电池月末 {summary['original_monthly_dates']} 个、合格股票行 {panel.height}；"
        '所有事件的真实留存均晚于该历史窗口，因此可估计月份为0。', '',
        '原月度打分/IC/统计筛选已执行；未伪造日频衰减、分组收益、N4控制值或三档成交。'
        'RESEARCH_ONLY表示输入历史不足，不是策略收益失败；原门槛不变，R6验收未完成。', '',
        '|列|版本|合格月|NW-t|增量NW-t|三档成本|本轮处理|', '|---|---|---:|---|---|---|---|']
    for row in statistics:
        lines.append(f"|{row['factor']}|{row['variant']}|{row['months']}|不可估计|不可估计|"
                     '未执行：无可执行持仓|本轮关闭，不救援|')
    lines += ['', '通过数：0/10；回购强度增量NW-t：不可估计（null，不是0）。', '',
        '分析师原生字段与同机构/作者/财期多日配对见summary.json；字段存在不等于历史覆盖足够。', '',
        '证据：source_facts.json、source_manifest.json、statistical_screen.parquet、'
        'cost_plan.parquet、incremental.json。旧数据、旧配置与股票信号均未覆盖。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    if register:
        from quant.reporting.experiment_registry import records_from_run, append_records
        records = records_from_run(output.resolve())
        for row in records:
            row.update(measurement='R6 observed-vintage history insufficiency; no executable cost results',
                       r6_qualified_months=0, r6_acceptance_complete=False,
                       r6_incremental_nw_t=None, r6_closed_this_round=True)
        total = append_records(records)
        save(output/'registration.json', {'registered_factor_versions': len(records), 'registry_rows': total})
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/research/event_family_r6_20261108.toml'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--register', action='store_true')
    print(json.dumps(run(**vars(parser.parse_args())), ensure_ascii=False))
