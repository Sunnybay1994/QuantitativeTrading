"""Mine expressions on train, select on validation, then score frozen test candidates."""
import argparse
import ast
import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.genetic_factor_inputs import read_genetic_panel
from quant.factors.expressions import ExpressionEngine, evaluate_expressions
from quant.factors.library import load_library
from quant.factors.search import expression_units
from quant.research.factor_battery_statistics import monthly_ic_summary, rank_ic_by_date


def split_panel(panel: pl.DataFrame, start: dt.date, end: dt.date) -> pl.DataFrame:
    """Labels must have matured within their own split, including training."""
    return panel.filter(pl.col('trade_date').is_between(start, end)
                        & (pl.col('label_exit_date') <= end)
                        & (pl.col('label_exit_date') > pl.col('trade_date')))


def assess(panel: pl.DataFrame, candidate: dict, minimum_symbols: int) -> dict:
    values = evaluate_expressions(panel, {'score': candidate['terminal_expression']})
    values = values.join(panel.select('symbol', 'trade_date', 'label'),
                         on=['symbol', 'trade_date'], validate='1:1')
    values = values.with_columns((pl.col('score') * candidate['direction']).alias('score'))
    series = rank_ic_by_date(values, score='score', label='label',
                            minimum_symbols=minimum_symbols, minimum_paired_coverage=0.8)
    return monthly_ic_summary(series['trade_date'].to_list(), series['rank_ic'].to_list())


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str,
                               allow_nan=False), encoding='utf-8')


def run(config: Path, output: Path, data_root: Path = Path('data'),
        evaluate: bool = False, *, model_config: Path | None = None,
        measurement_config: Path | None = None) -> dict:
    from quant.factors.genetic_search import GeneticSearchConfig, search_genetic

    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    dates, search = settings['dates'], settings['genetic']
    ordered = [dates[key] for key in ('start', 'training_end', 'validation_start',
                                      'validation_end', 'test_start', 'test_end')]
    if not all(a < b for a, b in zip(ordered, ordered[1:])):
        raise ValueError('Require disjoint ordered train/validation/test dates')
    definitions = {row.id: row for row in load_library(Path(settings['library']))}
    terminals = {name: definitions[name].expr for name in settings['terminals']}
    for expression in terminals.values():
        tree = ast.parse(expression, mode='eval')
        if expression_units(tree.body) != (0, 0):
            raise ValueError('Genetic terminals must be dimensionless')
        calls = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        fields = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} - calls
        ExpressionEngine(pl.DataFrame({'symbol': ['sample'], 'trade_date': [0],
            **{field: [1.] for field in fields}})).compile(expression)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'config.toml').write_bytes(config.read_bytes())
    write_json(output / 'terminals.json', terminals)
    panel = read_genetic_panel(data_root=data_root,
        statistics=[Path(p) for p in settings['statistics']], factors=list(terminals),
        start=dates['start'], end=dates['test_end'])
    parts = [split_panel(panel, ordered[i], ordered[i + 1]) for i in (0, 2, 4)]
    if any(part.is_empty() for part in parts):
        raise ValueError('Empty research split')
    result = search_genetic(parts[0], terminals,
                           GeneticSearchConfig(training_end=dates['training_end'], **search))
    write_json(output / 'search.json', result)
    candidates = result['candidates']
    for row in candidates:
        row['validation'] = assess(parts[1], row, search['minimum_symbols'])
    selection = settings['selection']
    qualified = [row for row in candidates
                 if row['validation']['months'] >= selection['minimum_validation_months']
                 and row['validation']['mean_ic'] is not None
                 and row['validation']['mean_ic'] >= selection['minimum_validation_ic']]
    qualified.sort(key=lambda row: (-row['validation']['mean_ic'], row['expression']))
    winners = qualified[:selection['maximum_selected']]
    baseline = result.get('random_baseline', {})
    baseline_candidates = baseline.get('candidates', [])
    for row in baseline_candidates:
        row['validation'] = assess(parts[1], row, search['minimum_symbols'])
    baseline_winners = sorted([row for row in baseline_candidates
        if row['validation']['months'] >= selection['minimum_validation_months']
        and row['validation']['mean_ic'] is not None
        and row['validation']['mean_ic'] >= selection['minimum_validation_ic']],
        key=lambda row: (-row['validation']['mean_ic'], row['expression']))[
            :selection['maximum_selected']]
    # Persist the selection before touching test scores. Test never changes this list.
    write_json(output / 'frozen_selection.json', winners)
    write_json(output / 'frozen_random_selection.json', baseline_winners)
    write_json(output / 'validation.json', candidates)
    write_json(output / 'random_validation.json', baseline_candidates)
    for row in baseline_winners:
        row['test'] = assess(parts[2], row, search['minimum_symbols'])
    library = output / 'library'
    library.mkdir()
    for row in winners:
        row['test'] = assess(parts[2], row, search['minimum_symbols'])
        factor_id = 'gp_' + hashlib.sha256(row['expression'].encode()).hexdigest()[:16]
        row['factor_id'] = factor_id
        definition = dict(id=factor_id, expr=row['expression'], family='genetic_price_liquidity',
                          direction=row['direction'], source_ref=str(output / 'frozen_selection.json'))
        content = ''.join(
            f'{key} = {json.dumps(value, ensure_ascii=False)}\n'
            for key, value in definition.items())
        (library / f'{factor_id}.toml').write_text(content, encoding='utf-8')
        registered = Path(settings['library']) / f'{factor_id}.toml'
        if registered.exists():
            prior = tomllib.loads(registered.read_text(encoding='utf-8'))
            if any(prior[key] != definition[key] for key in ('id', 'expr', 'direction', 'family')):
                raise ValueError('Existing GP factor has a conflicting definition')
        else:
            registered.write_text(content, encoding='utf-8')
    summary = dict(status='RESEARCH_ONLY' if winners else 'REJECTED',
        candidates=len(candidates), selected=len(winners), winners=winners,
        random_baseline={'summary': baseline.get('summary'), 'winners': baseline_winners},
        rows_by_split=[part.height for part in parts], search=result['summary'],
        caveat='Adaptive historical research; test is held out from this run, but project history has been studied. Cost evaluation is required before paper admission.')
    write_json(output / 'summary.json', summary)
    lines = ['# 遗传编程因子挖掘', '',
             f"训练候选 {len(candidates)} 个，验证筛选 {len(winners)} 个。结论：{summary['status']}。", '',
             '| 因子 | 验证月数 | 验证 RankIC | 测试月数 | 测试 RankIC |',
             '|---|---:|---:|---:|---:|']
    for row in winners:
        val, test = row['validation'], row['test']
        lines.append(f"| {row['factor_id']} | {val['months']} | {val['mean_ic']} | {test['months']} | {test['mean_ic']} |")
    lines += ['', f"随机搜索对照：验证入选 {len(baseline_winners)} 个，"
              f"训练独立评估数 {baseline.get('summary', {}).get('unique_evaluations', 0)}。"]
    for index, row in enumerate(baseline_winners, 1):
        lines.append(f"- 随机候选 {index}：验证 RankIC {row['validation']['mean_ic']}，"
                     f"测试 RankIC {row['test']['mean_ic']}。")
    lines += ['', '下一步：将冻结候选库交给现有全历史因子评估与三档成本回放。', '',
              '关键限制：这是自适应历史研究，项目已研究过这些历史区间；须完成统一成本评估及前向观察。']
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    if evaluate and winners:
        evaluate_selected(config=config, output=output, data_root=data_root,
                          model_config=model_config, measurement_config=measurement_config)
    return summary


def evaluate_selected(*, config: Path, output: Path, data_root: Path,
                      model_config: Path | None = None, measurement_config: Path | None = None) -> dict:
    """Feed the frozen library to the existing compute/statistics/cost pipeline."""
    if (model_config is None) != (measurement_config is None):
        raise ValueError("Supply model_config and measurement_config together")
    from quant.factors.compute import run as compute
    from quant.research.run_factor_pipeline import run_pipeline

    if config.read_bytes() != (output / 'config.toml').read_bytes():
        raise ValueError('Evaluation requires the frozen mining configuration')
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    evaluation, dates = settings['evaluation'], settings['dates']
    library = output / 'library'
    compute(data_root=data_root, refresh_config=Path(evaluation['refresh_config']),
            library=library, selected='all', start=dates['start'], end=dates['test_end'],
            artifact_root=output / 'compute')
    result = run_pipeline(config=Path(evaluation['battery_config']), library=library,
        as_of=dates['test_end'], output=output / 'evaluation', data_root=data_root,
        execution_snapshot=evaluation['execution_snapshot'], workers=evaluation['workers'],
        resume=(output / 'evaluation').exists(),
        return_benchmark_config=Path(evaluation['return_benchmark_config']))
    if model_config is not None:
        from quant.research.follow_factor_models import follow_factor_models, next_model_output
        if measurement_config is None:
            raise ValueError('Model continuation requires explicit measurement_config')
        result['models'] = follow_factor_models(evaluation=output/'evaluation', model_config=model_config,
            measurement_config=measurement_config, output=next_model_output(output), data_root=data_root)
    write_json(output / 'evaluation_result.json', result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--evaluate', action='store_true',
                        help='Continue into existing full-history statistics and cost evaluation')
    parser.add_argument('--evaluate-only', action='store_true',
                        help='Evaluate an existing frozen mining run without repeating search/test')
    parser.add_argument('--model-config', type=Path)
    parser.add_argument('--measurement-config', type=Path)
    args = parser.parse_args()
    if (args.model_config is None) != (args.measurement_config is None):
        parser.error('--model-config and --measurement-config must be supplied together')
    if args.model_config is not None and not (args.evaluate or args.evaluate_only):
        parser.error('Model continuation requires --evaluate or --evaluate-only')
    if args.evaluate_only:
        result = evaluate_selected(config=args.config, output=args.output, data_root=args.data_root,
                                   model_config=args.model_config, measurement_config=args.measurement_config)
    else:
        result = run(args.config, args.output, args.data_root, args.evaluate,
                     model_config=args.model_config, measurement_config=args.measurement_config)
    print(json.dumps(result, default=str))


if __name__ == '__main__':
    main()
