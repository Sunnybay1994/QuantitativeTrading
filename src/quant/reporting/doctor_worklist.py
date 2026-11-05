"""Observed November worklist facts on the existing doctor page, without admission."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import tomllib

import polars as pl

from quant.reporting.structured_coverage import describe_table

REQUIRED = {
    'account_portfolio_v1': ('fixed_40_30_30', 'inverse_volatility60'),
    'top15_limit_v1': ('limit_1pct', 'limit_3pct', 'open_full_fill'),
    'few_holdings_s2b_data_corrected_r3_v1': ('budgeted',),
}
OPTIONAL = {'account_portfolio_top15_v1': REQUIRED['account_portfolio_v1']}
TABLES = {'forecast', 'express', 'repurchase', 'stk_holdertrade', 'share_float',
          'margin_detail', 'stk_holdernumber', 'fund_share'}


def _inside(root, value):
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Worklist evidence outside project')
    return path


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _registry(root, clock):
    path = root / 'artifacts/registry/experiments.parquet'
    result = {'required_results': 6, 'verified_results': [], 'issues': []}
    if not path.is_file():
        result['issues'].append('registry missing')
        return result
    frame = pl.read_parquet(path)
    expected = {(name, variant) for name, variants in {**REQUIRED, **OPTIONAL}.items()
                for variant in variants}
    rows = [row for row in frame.to_dicts()
            if (row.get('experiment_id'), row.get('variant')) in expected]
    for key in sorted(expected):
        matches = [row for row in rows if (row['experiment_id'], row['variant']) == key]
        if not matches:
            continue
        try:
            if len(matches) != 1:
                raise ValueError('duplicate registry identity')
            row = matches[0]
            stamp = dt.datetime.fromisoformat(row['result_time'])
            if stamp.tzinfo is None or not (dt.datetime(2026, 11, 2, tzinfo=clock.tzinfo) <= stamp <= clock):
                raise ValueError('result outside observed worklist period')
            if row['level'] not in ('strategy', 'account'):
                raise ValueError('not a strategy/account result')
            if row['conclusion'] not in ('REJECTED', 'RESEARCH_ONLY', 'PAPER_CANDIDATE'):
                raise ValueError('unknown research conclusion')
            config = _inside(root, row['config_path'])
            report = _inside(root, row['report_path'])
            run = _inside(root, row['run_path'])
            if (not config.is_relative_to(run) or not report.is_relative_to(run)
                    or not report.is_file() or not report.stat().st_size):
                raise ValueError('result report/config missing from run')
            payload = config.read_bytes()
            if hashlib.sha256(payload).hexdigest() != row['config_sha256']:
                raise ValueError('registered config checksum mismatch')
            if tomllib.loads(payload.decode('utf-8'))['id'] != key[0]:
                raise ValueError('registered experiment/config mismatch')
            assessment = _json(run / 'assessment.json')
            if assessment.get('auto_trade') is not False:
                raise ValueError('assessment auto_trade invariant missing')
            costs = {r['cost_multiplier'] for r in assessment['rows'] if r.get('variant') == key[1]}
            if not {0.5, 1., 2.} <= costs:
                raise ValueError('three-cost assessment missing')
            if assessment['assessments'][key[1]]['conclusion'] != row['conclusion']:
                raise ValueError('assessment/registry conclusion mismatch')
            for cost, multiplier in (('0_5x', .5), ('1x', 1.), ('2x', 2.)):
                native = [r for r in assessment['rows']
                          if r.get('variant') == key[1] and r['cost_multiplier'] == multiplier]
                if len(native) != 1:
                    raise ValueError('ambiguous assessment cost row')
                for metric, field in (('cagr', 'cagr'), ('mdd', 'max_drawdown')):
                    value = row[f'{metric}_{cost}']
                    if type(value) not in (int, float) or not math.isfinite(value):
                        raise ValueError('three-cost registry metrics missing')
                    if not math.isclose(value, native[0][field], rel_tol=1e-12, abs_tol=1e-12):
                        raise ValueError('assessment/registry metric mismatch')
            result['verified_results'].append({
                'experiment_id': key[0], 'variant': key[1], 'conclusion': row['conclusion'],
                'report_path': str(report), 'result_time': row['result_time'],
                'config_sha256': row['config_sha256'],
            })
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result['issues'].append(f'{key[0]}/{key[1]}: {exc}')
    present = {(r['experiment_id'], r['variant']) for r in result['verified_results']}
    result['missing_required'] = [f'{name}/{variant}' for name, variants in REQUIRED.items()
                                  for variant in variants if (name, variant) not in present]
    return result


def _structured(root, clock):
    result = {'tables': {}, 'issues': []}
    for folder in sorted((root / 'artifacts/data').glob('structured_events*')):
        if not folder.is_dir() or not (folder / 'summary.json').is_file():
            continue
        try:
            receipt = _json(folder / 'summary.json')
            payload = (folder / 'config.toml').read_bytes()
            config = tomllib.loads(payload.decode('utf-8'))
            if config.get('id') not in ('structured_events_v1', 'structured_events_remaining_v1'):
                continue
            if (receipt.get('config_sha256') != hashlib.sha256(payload).hexdigest()
                    or config.get('auto_trade') is not False or config.get('evaluate_factors') is not False):
                raise ValueError('capture config invariant/checksum mismatch')
            if config['end'] > clock.date():
                raise ValueError('capture request end is in the future')
            for name, record in receipt.get('tables', {}).items():
                if name not in TABLES or name not in config['tables']:
                    continue
                adjusted = {**record, 'clean_path': str(_inside(root, record['clean_path']))}
                published = Path(adjusted['clean_path']) / 'summary.json'
                if published.stat().st_mtime > clock.timestamp():
                    raise ValueError(f'{name}: publication not yet available at observation time')
                if _json(published) != record:
                    raise ValueError(f'{name}: publication/receipt mismatch')
                actual = describe_table(name, adjusted, config['tables'][name],
                    start=config['start'], end=config['end'], data_root=root / 'data')
                if not actual.get('published'):
                    raise ValueError(f'{name}: published data files missing')
                actual['registered_end'] = str(config['end'])
                actual['capture'] = str(folder)
                actual['single_day_recovery_incomplete'] = any(
                    scope.startswith(name + '/') and split.get('complete') is not True
                    for scope, split in receipt.get('symbol_splits', {}).items())
                previous = result['tables'].get(name)
                if previous is None or actual['registered_end'] > previous['registered_end']:
                    result['tables'][name] = actual
        except (OSError, ValueError, KeyError, TypeError, pl.exceptions.PolarsError) as exc:
            result['issues'].append(f'{folder.name}: {exc}')
    result['published_table_count'] = len(result['tables'])
    result['tables_2019_to_registered_end'] = [name for name, row in result['tables'].items()
        if row.get('published') and row.get('declared_metadata_matches')
        and not row['single_day_recovery_incomplete']
        and str(row.get('first_date') or '').startswith('2019-')
        and str(row.get('last_date') or '')[:4] == row['registered_end'][:4]
        and not any(row.get(field, 1) for field in ('invalid_dates', 'null_available_at',
            'dates_outside_request', 'availability_before_observation'))
        and not row.get('missing_requested_years', [None])]
    result['tables_2019_to_registered_end'] = [name for name in result['tables_2019_to_registered_end']
        if name != 'fund_share' or result['tables'][name].get('daily_grid', {}).get('daily_grid_complete') is True]
    result['required_new_tables'] = 4
    result['scope'] = ('Published actual rows and dates only; year presence does not prove original '
                       'historical vintage, exhaustive supplier coverage, or consumer acceptance.')
    return result


def _credibility(root):
    folder = root / 'artifacts/research/q10_credibility_20261104'
    try:
        result = _json(folder / 'summary.json')
        execution = folder / 'execution_audit/summary.json'
        expected = result['provenance'].get(str(execution.relative_to(root)))
        # Receipts written by Windows retain backslashes in relative provenance keys.
        expected = expected or result['provenance'].get(str(execution.relative_to(root)).replace('/', '\\'))
        if hashlib.sha256(execution.read_bytes()).hexdigest() != expected:
            raise ValueError('R3 execution evidence checksum mismatch')
        if result['auto_trade'] is not False or not (folder / 'report.md').is_file():
            raise ValueError('R3 report/invariant missing')
        return {'report_path': str(folder / 'report.md'), 'dsr': result['dsr'],
                'conditional_excess_intervals': _json(execution)['conditional_excess_intervals'],
                'forward_evidence': result['forward_evidence'],
                'planning_incremental_excess': result['planning_incremental_excess']}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'issue': str(exc)}


def collect(root, clock):
    root = root.resolve()
    enabled = (root / 'docs/工作清单_20261102.md').is_file()
    result = {'enabled': enabled}
    if not enabled:
        return result
    if clock.tzinfo is None:
        raise ValueError('Worklist observation requires timezone-aware clock')
    try:
        registry = _registry(root, clock)
    except (OSError, ValueError, KeyError, TypeError, pl.exceptions.PolarsError) as exc:
        registry = {'required_results': 6, 'verified_results': [], 'issues': [str(exc)]}
    result.update(midterm_date='2026-11-15', final_date='2026-12-01',
        midterm_date_reached=clock.date() >= dt.date(2026, 11, 15),
        final_date_reached=clock.date() >= dt.date(2026, 12, 1),
        registry=registry, structured=_structured(root, clock), credibility=_credibility(root),
        scope='Observed progress, not full acceptance. Natural dated execution and consumers remain to verify.')
    return result


def markdown(result):
    if not result.get('enabled'):
        return []
    registry, structured, credibility = (result[key] for key in ('registry', 'structured', 'credibility'))
    lines = ['', '## 工作清单 2026-11-02：已观测进度', '',
        f"中期日期{result['midterm_date']}已到：{result['midterm_date_reached']}；"
        f"终验日期{result['final_date']}已到：{result['final_date_reached']}。",
        f"- 指定策略/账户结果：已核对{len(registry['verified_results'])}项；原要求6项，"
        f"缺少原指定项{registry.get('missing_required', ['注册表待核对'])}。",
        f"- 新结构化表：已发布{structured['published_table_count']}张，"
        f"实读2019至请求截止年份且摘要一致{len(structured['tables_2019_to_registered_end'])}张；要求至少4张。",
        '- 以下行数/日期来自实表；出现过各年份不等于原始历史版本或完整消费者验收。', '',
        '| 表 | 行数 | 最早 | 最新 | 请求截止 | 摘要一致 |', '|---|---:|---|---|---|---|']
    for name, actual in structured['tables'].items():
        lines.append(f"| {name} | {actual.get('rows', '未知')} | {actual.get('first_date')} | "
                     f"{actual.get('last_date')} | {actual['registered_end']} | {actual['declared_metadata_matches']} |")
    if credibility.get('issue'):
        lines.append(f"\nR3：{credibility['issue']}。")
    else:
        lines.append(f"\nR3 DSR：{credibility['dsr']}；规划增量超额{credibility['planning_incremental_excess']}。")
        for interval in credibility['conditional_excess_intervals']:
            lines.append(f"- {interval['declared_trials']}次口径条件年化超额区间："
                         f"{interval['conditional_annual_excess_interval_pp']} pp。")
        lines.append('条件历史区间不是未见样本外预测；当前未确立正向前证据。')
    for issue in registry['issues'] + structured['issues']:
        lines.append(f'- 待核对：{issue}')
    lines.append('\n本节只汇总进度；不宣告清单完成。11-27预演、11-30及时订单及12-01真实月报/费用产物仍须自然证据。')
    return lines
