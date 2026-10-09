"""Fill annual causal cost dependencies without changing the final-cutoff battery."""
import hashlib
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.realtime_store import atomic_json
from quant.research.factor_battery_cost_batch import run_cost_batch


def required_cost_factors(prefix: Path) -> list[str]:
    model = tomllib.loads((prefix/'model.toml').read_text(encoding='utf-8'))
    table = pl.read_parquet(prefix/'annual_statistical_screen.parquet')
    return sorted(set(table.filter(pl.col('statistical_pass') &
        (pl.col('variant') == model['selection']['variant']))['factor']))


def prepare_costs(output: Path, data_root: Path, completed: dict) -> list[Path]:
    """Only early-prefix qualifiers absent from the original cost run are added."""
    required = required_cost_factors(output/'prefix')
    missing = sorted(set(required)-set(completed))
    folder = output/'additional_costs'
    folder.mkdir(exist_ok=True)
    request = {'required_factors': required, 'additional_factors': missing,
        'original_runs': completed,
        'prefix_sha256': hashlib.sha256((output/'prefix/annual_statistical_screen.parquet').read_bytes()).hexdigest()}
    marker = folder/'request.json'
    if marker.exists():
        if json.loads(marker.read_text(encoding='utf-8')) != request:
            raise ValueError('Frozen annual cost dependencies changed')
    else:
        atomic_json(marker, request)
    extra = {}
    if missing:
        frozen = json.loads((output/'frozen_settings.json').read_text(encoding='utf-8'))
        result = run_cost_batch(statistics=output/'evaluation/statistics',
            screen=output/'evaluation/screen', output=folder, data_root=data_root,
            execution_snapshot=frozen['execution_snapshot'], existing_runs=[],
            workers=frozen['workers'], required_factors=missing, resume=True)
        extra = result['completed_runs']
        if result['failures'] or result['pending_external_runs'] or set(extra) != set(missing):
            raise ValueError('Annual causal cost dependencies incomplete; resume additional_costs checkpoints')
    atomic_json(folder/'dependency_receipt.json', {**request, 'completed_runs': extra,
        'status': 'complete', 'original_costs_reused': len(completed)})
    # Additional histories are read separately via cost_root by run_cost_prefixes.
    return [Path(path) for path in completed.values()]


def refresh_cached_stages(output: Path, sources: dict) -> dict:
    """Journal an append-only dependency change; preserve metrics and correlations.

    The journal is saved before renames. A retry after either rename resumes the
    same transition, while _stage retains any partially generated replacement.
    """
    normalized = {key: str(Path(path).resolve()) for key, path in sources.items()}
    token = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()[:16]
    journal = output/f'prefix_dependency_refresh_{token}.json'
    if journal.exists():
        state = json.loads(journal.read_text(encoding='utf-8'))
    else:
        summary = output/'prefix_costs/summary.json'
        if not summary.exists():
            return {}
        previous = json.loads(summary.read_text(encoding='utf-8'))['source_runs']
        previous = {key: str(Path(path).resolve()) for key, path in previous.items()}
        if previous == normalized:
            return {}
        if any(normalized.get(key) != path for key, path in previous.items()):
            raise ValueError('Annual cost recovery may only append unchanged histories')
        if (output/'predictions').exists():
            raise ValueError('Cannot replace dependencies of already published predictions')
        state = {'sources': normalized, 'archives': {name: str(output/f'{name}_before_{token}')
            for name in ('prefix_costs', 'selection') if (output/name).exists()}}
        atomic_json(journal, state)
    for name, destination in state['archives'].items():
        archive = Path(destination)
        if not archive.exists():
            (output/name).rename(archive)
    return {name: Path(path) for name, path in state['archives'].items()}
