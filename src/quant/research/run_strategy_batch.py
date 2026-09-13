"""Run a fixed registered strategy list or reuse its complete saved results."""
import argparse
import datetime as dt
import json
import re
import tomllib
from pathlib import Path

from quant.research.run_model_volatility_overlay import run as run_overlay
from quant.research.run_turnover_budget import run as run_budget

KINDS = {'volatility_overlay': 'overlay', 'turnover_budget': 'budgeted'}
CONCLUSIONS = {'REJECTED', 'RESEARCH_ONLY', 'PAPER_CANDIDATE'}


def saved_result(*, kind: str, config: Path, output: Path) -> dict:
    """Check existing runner artifacts, without recomputing or changing a decision."""
    if tomllib.loads((output/'config.toml').read_text(encoding='utf-8')) != tomllib.loads(config.read_text(encoding='utf-8')):
        raise ValueError('Saved strategy configuration differs from registered config')
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    research = spec if kind == 'volatility_overlay' else spec['research']
    auto_trade = spec['auto_trade'] if kind == 'volatility_overlay' else spec['policy']['auto_trade']
    if auto_trade is not False:
        raise ValueError('Only auto_trade=false research strategies are supported')
    source = Path(research['predictions'])
    for filename, original in [('model.toml', source/'model.toml'), ('battery.toml', source/'battery.toml'),
        ('measurement.toml', Path(research['return_benchmark_config']))]:
        if tomllib.loads((output/filename).read_text(encoding='utf-8')) != tomllib.loads(original.read_text(encoding='utf-8')):
            raise ValueError(f'Saved input configuration differs: {filename}')
    events = Path(spec['share_exchanges_config']) if kind == 'volatility_overlay' else Path(
        'configs/data/share_exchanges_20260912.toml')
    if tomllib.loads((output/'share_exchanges.toml').read_text(encoding='utf-8')) != tomllib.loads(events.read_text(encoding='utf-8')):
        raise ValueError('Saved share exchange configuration differs')
    model = tomllib.loads((output/'model.toml').read_text(encoding='utf-8'))
    variants = ('control', KINDS[kind])
    for variant in variants:
        for cost in (.5, 1., 2.):
            for year in range(model['walk_forward']['test_start'].year, model['walk_forward']['test_end'].year+1):
                folder = output/variant/f'cost_{cost:g}'/str(year)
                for name in ('account.json', 'nav.parquet', 'trades.parquet', 'rejections.parquet'):
                    if not (folder/name).is_file():
                        raise ValueError(f'Incomplete saved replay: {folder/name}')
    for name in ('summary.json', 'report.md'):
        if not (output/name).is_file():
            raise ValueError(f'Incomplete saved report: {name}')
    assessment = json.loads((output/'assessment.json').read_text(encoding='utf-8'))
    rows = assessment['rows']
    expected = {(variant, cost) for variant in variants for cost in (.5, 1., 2.)}
    if len(rows) != 6 or {(r['variant'], r['cost_multiplier']) for r in rows} != expected:
        raise ValueError('Saved assessment must contain all paired cost scenarios')
    if set(assessment['assessments']) != set(variants) or any(
        r['conclusion'] not in CONCLUSIONS for r in assessment['assessments'].values()):
        raise ValueError('Missing original strategy admission conclusion')
    comparison = assessment.get('control_comparison') if kind == 'volatility_overlay' else json.loads(
        (output/'control_comparison.json').read_text(encoding='utf-8'))
    key = 'cost' if kind == 'volatility_overlay' else 'cost_multiplier'
    flag = 'nav_exact' if kind == 'volatility_overlay' else 'nav_exact_equal'
    if (not comparison or len(comparison) != 3 or {r[key] for r in comparison} != {.5, 1., 2.}
            or any(r.get(flag) is not True for r in comparison)):
        raise ValueError('Saved paired control verification is incomplete')
    conclusion = assessment.get('conclusion', assessment['assessments'][KINDS[kind]]['conclusion'])
    if conclusion not in CONCLUSIONS:
        raise ValueError('Unknown original conclusion')
    return {'source_strategy_id': research['id'], 'conclusion': conclusion,
        'assessment': str(output/'assessment.json'), 'report': str(output/'report.md'),
        'rows': rows, 'admission': assessment['assessments'][KINDS[kind]],
        'execution_improvement': assessment.get('execution_improvement'),
        'risk_improvement': assessment.get('risk_improvement'), 'original_control_verification': comparison}


def run(*, config: Path, output: Path, data_root: Path = Path('data')) -> dict:
    content = config.read_bytes()
    spec = tomllib.loads(content.decode('utf-8'))
    if spec['auto_trade'] is not False or spec['evidence'] != 'retrospective_registered_rules_no_selection':
        raise ValueError('Batch must remain retrospective research without strategy selection')
    jobs = spec['strategies']
    ids = [job['id'] for job in jobs]
    if (not jobs or len(ids) != len(set(ids))
            or any(not re.fullmatch(r'[a-zA-Z0-9_-]+', value) for value in ids)):
        raise ValueError('Require a nonempty fixed list with unique safe ids')
    output.mkdir(parents=True, exist_ok=False)
    (output/'config.toml').write_bytes(content)
    result = {'batch_id': spec['id'], 'recorded_at': dt.datetime.now().astimezone().isoformat(),
        'evidence': spec['evidence'], 'auto_trade': False, 'selection_performed': False,
        'status': 'running', 'items': []}

    def save() -> None:
        temporary = output/'summary.json.tmp'
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(output/'summary.json')
        failures = [row for row in result['items'] if row['status'] == 'failed']
        (output/'failures.json').write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    for job in jobs:
        item = {'id': job['id'], 'kind': job.get('kind'), 'config': job.get('config'), 'status': 'running'}
        result['items'].append(item)
        save()
        try:
            if job['kind'] not in KINDS or set(job) != {'id', 'kind', 'config', 'existing_output'}:
                raise ValueError('Only fixed whitelisted strategy kinds and arguments are supported')
            registered = Path(job['config'])
            existing = job['existing_output']
            destination = Path(existing) if existing else output/'runs'/job['id']
            item['output'] = str(destination)
            if not existing:
                if job['kind'] == 'volatility_overlay':
                    run_overlay(config=registered, output=destination, data_root=data_root)
                else:
                    run_budget(config=registered, output=destination, data_root=data_root)
            item.update(saved_result(kind=job['kind'], config=registered, output=destination))
            from quant.reporting.experiment_registry import register_run
            register_run(destination)
            item['status'] = 'reused' if existing else 'ran'
        except Exception as exc:
            item.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        save()
    result['status'] = 'partial' if any(i['status'] == 'failed' for i in result['items']) else 'complete'
    result['counts'] = {status: sum(i['status'] == status for i in result['items'])
                        for status in ('reused', 'ran', 'failed')}
    save()
    lines = ['# 已注册策略批次结论索引', '', '历史回顾性汇总；保留原准入结论，不新增策略择优或改动阈值。', '',
        '|注册项|类型|处理|原结论|结果|', '|---|---|---|---|---|']
    for item in result['items']:
        detail = item.get('error') or f"[原报告]({Path(item['report']).resolve().as_posix()})"
        lines.append(f"|{item['id']}|{item['kind']}|{item['status']}|{item.get('conclusion', '未取得')}|{detail}|")
    lines += ['', '|注册项|方案|成本|首次持仓|同窗年化|Sharpe|最大回撤|实际年换手|', '|---|---|---:|---|---:|---:|---:|---:|']
    for item in result['items']:
        for row in item.get('rows', []):
            values = [row.get(k) for k in ('active_start', 'cagr', 'sharpe', 'max_drawdown', 'annualized_one_way_turnover')]
            lines.append(f"|{item['id']}|{row['variant']}|{row['cost_multiplier']}|"+'|'.join(
                '不可用' if value is None else str(value) for value in values)+'|')
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    result = run(**vars(parser.parse_args()))
    print(json.dumps({'status': result['status'], 'counts': result['counts']}))
    if result['status'] != 'complete':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
