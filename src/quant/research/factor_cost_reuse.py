"""Publish standalone report histories for exactly equivalent battery signals."""
import hashlib
import json
import shutil
import tomllib
from pathlib import Path

import polars as pl

from quant.research.factor_cost_duplicates import audit_duplicates


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_digest(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest()


def prepare_plan(statistics: Path, output: Path, factors: list[str], data_root: Path,
                 snapshot: str) -> dict:
    plan = audit_duplicates(statistics, factors)
    settings = tomllib.loads((statistics/'battery.toml').read_text(encoding='utf-8'))
    refresh = settings.get('data', {}).get('refresh_config')
    plan.update(execution_reuse_enabled=True, data_root=str(data_root.resolve()),
                execution_snapshot=snapshot,
                refresh_sha256=digest(Path(refresh)) if refresh else None,
                share_exchanges_sha256=text_digest(Path('configs/data/share_exchanges_20260912.toml')))
    path = output/'reuse_plan.json'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != plan:
            raise ValueError('Frozen replay reuse inputs changed; retain this batch')
    else:
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(plan, indent=2), encoding='utf-8')
        temporary.replace(path)
    return plan


def validate_published(output: Path, plan: dict) -> dict:
    receipt = json.loads((output/'reuse.json').read_text(encoding='utf-8'))
    factor = output.name
    if (receipt['factor'] != factor or receipt['representative'] != plan['aliases'].get(factor)
            or receipt['fingerprint'] != plan['fingerprints'][factor]
            or receipt['execution_snapshot'] != plan['execution_snapshot']):
        raise ValueError('Published reused history differs from frozen equivalence plan')
    if any(digest(output/name) != checksum for name, checksum in receipt['files'].items()):
        raise ValueError('Published reused history is incomplete or changed')
    return receipt


def publish_alias(source: Path, output: Path, *, factor: str, representative: str,
                  statistics: Path, plan: dict) -> dict:
    """Never expose a partial alias as complete; staging can be rebuilt on resume."""
    if output.exists():
        return validate_published(output, plan)
    config = (statistics/'battery.toml').read_bytes()
    saved = tomllib.loads((source/'battery.toml').read_text(encoding='utf-8'))
    selection = saved.pop('cost_replay')
    summary = json.loads((source/'summary.json').read_text(encoding='utf-8'))
    replay = json.loads((source/'replay_config.json').read_text(encoding='utf-8'))
    if (saved != tomllib.loads(config.decode('utf-8')) or selection['factor'] != representative
            or selection['execution_snapshot'] != plan['execution_snapshot']
            or summary['factor'] != representative
            or summary['execution_snapshot'] != plan['execution_snapshot']
            or replay['data_root'] != plan['data_root'] or replay['snapshot'] != plan['execution_snapshot']
            or text_digest(source/'share_exchanges.toml') != plan['share_exchanges_sha256']):
        raise ValueError('Representative execution context differs from frozen reuse plan')
    from quant.research.factor_battery_cost_report import load_cost_history
    for row in summary['rows']:
        load_cost_history(source, row['variant'], row['cost_multiplier'], saved['run']['as_of'])
    if not summary['rows']:
        raise ValueError('Representative has no completed histories')
    keys = [(row['variant'], row['cost_multiplier']) for row in summary['rows']]
    expected = {(variant, cost) for variant, _ in keys for cost in saved['portfolio']['cost_multipliers']}
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError('Representative cost scenarios are incomplete')
    stage = output.parent/'reuse_staging'/factor
    stage.mkdir(parents=True, exist_ok=True)
    config += ('\n[cost_replay]\nfactor = '+json.dumps(factor)+'\nexecution_snapshot = '
               +json.dumps(plan['execution_snapshot'])+'\nempty_top_group = "cash_after_first_valid_group"\n').encode()
    (stage/'battery.toml').write_bytes(config)
    shutil.copyfile(source/'share_exchanges.toml', stage/'share_exchanges.toml')
    files = [*source.glob('targets_*.parquet'), *source.glob('*/*/*/*.parquet')]
    names = {f'battery_{representative}_{variant}': f'battery_{factor}_{variant}'
             for variant in saved['variants']}
    for path in files:
        frame = pl.read_parquet(path)
        if 'strategy' in frame.columns:
            frame = frame.with_columns(pl.col('strategy').replace_strict(names))
        target = stage/path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(target)
    # These are report histories, not invented account checkpoints.
    result = {**summary, 'factor': factor, 'seconds': 0.,
              'rows': [{**row, 'factor': factor} for row in summary['rows']],
              'reused_from': str(source.resolve())}
    (stage/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    receipt = {'factor': factor, 'representative': representative,
               'fingerprint': plan['fingerprints'][factor],
               'execution_snapshot': plan['execution_snapshot'], 'source': str(source.resolve()),
               'saved_variant_cost_replays': len(summary['rows']),
               'files': {p.relative_to(stage).as_posix(): digest(p)
                         for p in stage.rglob('*') if p.is_file() and p.name != 'reuse.json'}}
    (stage/'reuse.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    # Same-volume directory rename publishes all report evidence together.
    stage.rename(output)
    return receipt
