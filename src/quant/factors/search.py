"""Expand a finite, versioned expression grid into the existing factor library."""
import ast
import itertools
import json
import re
import string
import tomllib
from pathlib import Path

import polars as pl

from quant.factors.expressions import ExpressionEngine, required_history
from quant.factors.library import FactorDefinition, load_library


def canonical(expression: str) -> str:
    return ast.dump(ast.parse(expression, mode="eval"), include_attributes=False)


def expression_units(node: ast.AST) -> tuple[int, int]:
    """Price/share-volume exponents for this batch's small, fixed template vocabulary."""
    if isinstance(node, ast.Constant):
        return (0, 0)
    if isinstance(node, ast.Name):
        units = {'adj_close': (1, 0), 'adj_high': (1, 0), 'adj_low': (1, 0), 'volume': (0, 1),
                 'turnover_rate': (0, 0),
                 'amihud_illiquidity_monthly_calendar80_v1': (-1, -1),
                 'free_float_turnover_level_monthly_calendar80_v1': (0, 0),
                 'free_float_turnover_abnormal_12m_calendar80_v1': (0, 0)}
        if node.id not in units:
            raise ValueError('Field units are not registered')
        return units[node.id]
    if isinstance(node, ast.UnaryOp):
        return expression_units(node.operand)
    if isinstance(node, ast.BinOp):
        left, right = expression_units(node.left), expression_units(node.right)
        if isinstance(node.op, (ast.Add, ast.Sub)) and left == right:
            return left
        if isinstance(node.op, ast.Mult):
            return (left[0]+right[0], left[1]+right[1])
        if isinstance(node.op, ast.Div):
            return (left[0]-right[0], left[1]-right[1])
        raise ValueError('Incompatible units or unregistered arithmetic')
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in ('delay', 'ts_mean', 'ts_std', 'ts_std0'):
            return expression_units(node.args[0])
        if node.func.id == 'ts_corr':
            for argument in node.args[:-1]:
                expression_units(argument)
            return (0, 0)
    raise ValueError('Operator units are not registered')


def expand(settings: dict, existing: list[FactorDefinition]) -> tuple[list[FactorDefinition], list[dict]]:
    """No adaptive feedback, generated Python, unbounded grid or silently dropped attempt."""
    budget = settings['search']
    if not 1 <= budget['maximum_candidates'] <= 50:
        raise ValueError('Candidate budget must be between one and fifty')
    candidates, trials = [], []
    seen = {canonical(row.expr): row.id for row in existing}
    identifiers = {row.id: row for row in existing}
    allowed_fields, allowed_operators = set(budget['fields']), set(budget['operators'])
    total = 0
    for template in settings['templates']:
        parameters = template.get('parameters', {})
        if any(not values or any(type(value) is not int or value < 1 for value in values)
               for values in parameters.values()):
            raise ValueError('Template grids require positive integer values')
        keys = sorted(parameters)
        expected = {name for _, name, _, _ in string.Formatter().parse(template['expr']) if name}
        if expected != set(keys):
            raise ValueError('Template parameters must exactly match its expression slots')
        count = 1
        for values in parameters.values():
            count *= len(values)
        total += count
    if total > budget['maximum_candidates']:
        raise ValueError('Expanded grid exceeds the registered candidate budget')
    for template in settings['templates']:
        parameters = template.get('parameters', {})
        keys = sorted(parameters)
        for values in itertools.product(*(parameters[key] for key in keys)):
            params = dict(zip(keys, values, strict=True))
            factor_id = template['id'] + ''.join(f'_{key}{params[key]}' for key in keys)
            expression = template['expr'].format(**params)
            trial = {'factor': factor_id, 'expression': expression, 'parameters': params}
            try:
                if (not re.fullmatch(r'[a-z][a-z0-9_]*', factor_id)
                        or type(template['direction']) is not int or template['direction'] not in (-1, 1)):
                    raise ValueError('Invalid factor identity or direction')
                tree = ast.parse(expression, mode='eval')
                def depth(node):
                    return 1 + max((depth(child) for child in ast.iter_child_nodes(node)), default=0)
                if depth(tree) > budget['maximum_depth']:
                    raise ValueError('Expression depth exceeds the registered limit')
                calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Name)}
                fields = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} - calls
                if not fields <= allowed_fields or not calls <= allowed_operators:
                    raise ValueError('Expression uses an unregistered field or operator')
                history = required_history(expression)
                if 'maximum_history' in budget and history > budget['maximum_history']:
                    raise ValueError('Expression history exceeds the registered limit')
                # Validate operator arity and supported syntax before allocating historical panels.
                engine = ExpressionEngine(pl.DataFrame({'symbol': ['sample'], 'trade_date': [0],
                                                       **{field: [1.0] for field in fields}}))
                engine.compile(expression)
                expression_units(tree.body)
                definition = FactorDefinition(factor_id, expression, template['family'],
                                              template['direction'], template['source_ref'])
                key = canonical(expression)
                if factor_id in identifiers:
                    if identifiers[factor_id] != definition:
                        raise ValueError('Existing factor ID has a different definition')
                elif key in seen:
                    trials.append({**trial, 'result': 'duplicate_expression', 'duplicate_of': seen[key]})
                    continue
                candidates.append(definition)
                identifiers[factor_id], seen[key] = definition, factor_id
                trials.append({**trial, 'result': 'registered'})
            except (ValueError, SyntaxError, IndexError, TypeError, RecursionError) as exc:
                trials.append({**trial, 'result': 'invalid_expression', 'reason': str(exc)})
    if len({row.id for row in candidates}) != len(candidates):
        raise ValueError('Grid generated duplicate factor IDs')
    return candidates, trials


def prepare(*, config: Path, library: Path, output: Path, allow_fixture: bool = False) -> dict:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    if settings.get('candidate_generation', {}).get('synthetic_fixture') and not allow_fixture:
        raise ValueError('Synthetic candidate fixtures cannot enter the research evaluation pipeline')
    output.mkdir(parents=True, exist_ok=True)
    frozen = output/'search.toml'
    if frozen.is_file() and frozen.read_bytes() != config.read_bytes():
        raise ValueError('Changed search configuration requires a new run directory')
    definitions, trials = expand(settings, load_library(library))
    frozen.write_bytes(config.read_bytes())
    batch = output/'library'
    batch.mkdir(exist_ok=True)
    for row in definitions:
        content = ''.join(f'{key} = {json.dumps(value, ensure_ascii=False)}\n' for key, value in vars(row).items())
        for root in (library, batch):
            path = root/f'{row.id}.toml'
            if path.is_file() and tomllib.loads(path.read_text(encoding='utf-8')) != vars(row):
                raise ValueError('Existing factor file has different contents')
            if not path.is_file():
                path.write_text(content, encoding='utf-8')
    result = {'attempts': trials, 'attempt_count': len(trials), 'registered_count': len(definitions),
              'factors': [row.id for row in definitions], 'batch_library': str(batch)}
    (output/'trials.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
