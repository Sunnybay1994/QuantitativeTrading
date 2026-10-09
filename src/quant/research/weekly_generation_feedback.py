"""Bounded definition-validation feedback; never infer predictive performance."""
from __future__ import annotations

import ast
from collections import Counter
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib


def mechanism_shape(expression: str) -> str:
    """Recognize numeric variants without changing submitted expressions."""
    class WithoutParameters(ast.NodeTransformer):
        def visit_Constant(self, node):
            return ast.Constant(value=0) if type(node.value) in (int, float) else node
    return ast.dump(WithoutParameters().visit(ast.parse(expression, mode='eval')), include_attributes=False)


def generation_feedback(root: Path, *, before_week: str, limit: int = 3, maximum_bytes: int = 12000) -> dict:
    cutoff = dt.date.fromisoformat(before_week)
    result = {'version': 'weekly_definition_feedback_v1', 'source_root': str(root.resolve()),
              'meaning': 'Definition validity and duplicate structure only; not battery rejection or alpha evidence.',
              'weeks': [], 'unavailable': [], 'detail_truncated': False}
    folders = []
    for path in root.iterdir() if root.exists() else []:
        try:
            if path.is_dir() and dt.date.fromisoformat(path.name) < cutoff:
                folders.append(path)
        except ValueError:
            continue
    for folder in sorted(folders, reverse=True):
        if len(result['weeks']) >= limit:
            break
        sources = []

        def read(name, *, toml=False):
            path = folder / name
            raw = path.read_bytes()
            sources.append({'path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest()})
            return (tomllib.loads if toml else json.loads)(raw.decode('utf-8'))

        try:
            summary = read('summary.json')
            if summary.get('completed') is not True:
                continue
            trials = read('validation.json')
            design = read('design.toml', toml=True)['search']
            if not isinstance(trials, list):
                raise ValueError('validation_not_array')
            reasons, operators, fields, structures = Counter(), Counter(), Counter(), Counter()
            examples = []
            for trial in trials:
                expression = trial.get('candidate', {}).get('expression', '')
                if trial.get('result') == 'rejected':
                    reason = str(trial.get('reason', 'unspecified'))[:160]
                    reasons[reason] += 1
                    if reasons[reason] == 1 and len(examples) < 4:
                        examples.append({'reason': reason, 'expression': expression[:1000]})
                try:
                    tree = ast.parse(expression, mode='eval')
                    structures[mechanism_shape(expression)] += 1
                    calls = {n.func.id for n in ast.walk(tree)
                             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
                    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                    operators.update(calls - set(design['operators']))
                    fields.update(names - calls - set(design['fields']))
                except (ValueError, SyntaxError, TypeError, RecursionError):
                    continue
            entry = {'week': folder.name, 'proposed_count': len(trials),
                     'locally_accepted_count': summary.get('accepted_count'),
                     'queued_count': len(summary.get('queued_ids', [])),
                     'validation_reasons': dict(reasons),
                     'unregistered_operator_candidate_counts': dict(operators),
                     'unregistered_field_candidate_counts': dict(fields),
                     'distinct_numeric_stripped_structures': len(structures),
                     'additional_same_structure_candidates': sum(n - 1 for n in structures.values()),
                     'rejected_examples': examples}
            if (folder / 'accepted.json').exists():
                accepted = read('accepted.json')
                entry['locally_accepted_count'] = len(accepted)
                entry['previously_accepted_examples'] = [
                    {'id': row['id'], 'expression': row['expr']} for row in accepted[:4]]
            if (folder / 'mechanism_deduplication.json').exists():
                entry['parameter_variant_rejections'] = len(read('mechanism_deduplication.json'))
            entry['sources'] = sources
            result['weeks'].append(entry)
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError) as exc:
            if len(result['unavailable']) < limit:
                result['unavailable'].append({'week': folder.name, 'reason': type(exc).__name__})
    # The library remains complete; keep optional feedback inside its own budget.
    def encoded_size():
        return len(json.dumps(result, ensure_ascii=False).encode('utf-8'))
    if encoded_size() > maximum_bytes:
        result['detail_truncated'] = True
        for entry in reversed(result['weeks']):
            entry.pop('rejected_examples', None)
            entry.pop('previously_accepted_examples', None)
            if encoded_size() <= maximum_bytes:
                break
    while result['weeks'] and encoded_size() > maximum_bytes:
        result['weeks'].pop()
    return result
