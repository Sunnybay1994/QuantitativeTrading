"""Content-addressed reuse of complete equal-weight benchmark accounts."""
import ast
import hashlib
import io
import json
import shutil
import tomllib
import uuid
from pathlib import Path

# These independent read-only market / ETF paper entry points are not imported
# by the stock cost replay. Retain the full remaining account/data packages.
INDEPENDENT_MODULES = {
    'execution/b16_forward.py', 'execution/b16_forward_service.py',
    'execution/etf_quote_paper.py', 'data/market_snapshot.py',
    'data/market_clock_baseline.py',
}


def stock_replay_sources(code_root: Path) -> set[Path]:
    """Conservative import closure, including function-local imports and packages."""
    pending = ['quant.research.factor_battery_costs', 'quant.research.factor_battery_benchmarks']
    seen, paths = set(), set()
    while pending:
        module = pending.pop()
        if module in seen or not module.startswith('quant'):
            continue
        seen.add(module)
        relative = module.split('.')[1:]
        path = code_root.joinpath(*relative).with_suffix('.py') if relative else code_root/'__init__.py'
        if not path.is_file():
            path = code_root.joinpath(*relative)/'__init__.py'
        if not path.is_file():
            continue  # a symbol imported from its parent module, not a submodule
        paths.add(path)
        pending += ['.'.join(module.split('.')[:n]) for n in range(1,len(module.split('.')))]
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if isinstance(node, ast.Import):
                pending += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ''
                if node.level:
                    package = module.split('.') if path.name=='__init__.py' else module.split('.')[:-1]
                    base = '.'.join(package[:len(package)-node.level+1] + ([base] if base else []))
                pending.append(base)
                pending += [base+'.'+alias.name for alias in node.names if alias.name!='*']
            elif isinstance(node, ast.Call) and node.args and (
                isinstance(node.func,ast.Name) and node.func.id=='__import__' or
                isinstance(node.func,ast.Attribute) and node.func.attr=='import_module'):
                if isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):
                    pending.append(node.args[0].value)
    return paths


def digest(path: Path) -> str:
    before = path.stat()
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Benchmark input changed while fingerprinting')
    return value.hexdigest()


def context(*, settings: dict, plans: dict, sessions: tuple, data_root: Path, snapshot: str) -> dict:
    """Hash content, never trust snapshot names, mtimes or path identity alone.

    Whole source partitions are conservative: irrelevant changed rows may cause
    a cache miss, but cannot make different execution inputs collide.
    """
    refresh = Path(settings['data']['refresh_config'])
    spec = tomllib.loads(refresh.read_text(encoding='utf-8'))
    files = [refresh, *sorted((data_root/'clean/stock_execution'/snapshot).glob('*.parquet'))]
    required = {'instruments.parquet', 'limits.parquet', 'suspensions.parquet', 'dividends.parquet'}
    if not required <= {p.name for p in files}:
        raise ValueError('Benchmark cache requires complete execution inputs')
    for market in ('SH', 'SZ'):
        files.append(data_root/f'clean/trade_calendar/market={market}/data.parquet')
    history = data_root/'clean/tushare_bulk/snapshots'/spec['stock_snapshot']/'bar_1d/asset=stock'
    bars = sorted(history.glob('year=*/*.parquet'))
    if not bars:
        raise ValueError('Benchmark cache requires historical bars')
    files.extend(bars)
    for folder in sorted((data_root/'clean/tushare_incremental').glob('date=*')):
        if folder.name[5:] <= str(settings['run']['as_of']):
            # Include membership of complete increments as well as their bars.
            files.extend(sorted(folder.glob('*.parquet')))
    if settings.get('execution', {}).get('retry_zero_target_exits'):
        root = data_root/'clean/factor_execution'/settings['execution']['daily_limits_snapshot']
        extra = sorted(root.rglob('*.parquet'))
        if not extra:
            raise ValueError('Benchmark cache lacks daily exit limits')
        files.extend(extra)
    files.append(data_root/'clean/factor_benchmarks'/settings['data']['csi800_snapshot']/'members.parquet')
    # Invalidate execution code, without making a dashboard edit invalidate an
    # interrupted account. This deliberately covers entire account packages.
    code_root = Path(__file__).resolve().parents[1]
    dependencies = stock_replay_sources(code_root)
    if any((code_root/name) in dependencies for name in INDEPENDENT_MODULES):
        raise ValueError('An excluded independent module became a stock replay dependency')
    for package in ('backtest', 'core', 'portfolio', 'execution', 'data'):
        files.extend(p for p in sorted((code_root/package).rglob('*.py'))
                     if p.relative_to(code_root).as_posix() not in INDEPENDENT_MODULES)
    for name in ('classic_monthly_baseline', 'run_s1_walk_forward', 'factor_cost_checkpoint',
                 'factor_battery_costs', 'factor_battery_benchmarks', 'benchmark_reuse'):
        files.append(code_root/'research'/f'{name}.py')
    targets = {}
    for key, (name, frame) in sorted(plans.items()):
        buffer = io.BytesIO()
        frame.write_ipc(buffer)
        targets[key] = {'name': name, 'sha256': hashlib.sha256(buffer.getvalue()).hexdigest()}
    return {'version': 2, 'settings': json.loads(json.dumps(settings, default=str)),
            'sessions': [str(day) for day in sessions], 'targets': targets,
            'files': {str(p.resolve()): digest(p) for p in sorted(set(files))}}


def key(context: dict) -> str:
    return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()


def require_compatible_resume(inputs: Path, current: dict) -> None:
    """A scoped migration receipt binds the preserved old manifest to this context.

    Never mint a receipt implicitly or accept changed data/targets by replacing
    the old manifest. A changed retained dependency also changes the bound key.
    """
    original = json.loads(inputs.read_text(encoding='utf-8'))
    if original == current:
        return
    receipt = inputs.with_name('benchmark_scope_compatibility.json')
    if receipt.exists():
        proof = json.loads(receipt.read_text(encoding='utf-8'))
        if (proof.get('original_manifest_sha256') == digest(inputs)
                and proof.get('compatible_context_key') == key(current)
                and proof.get('all_retained_data_settings_sessions_targets_equal') is True):
            return
    raise ValueError('Frozen benchmark execution content changed; compatible scope receipt absent or stale')


def lookup(root: Path, context: dict, output: Path) -> dict | None:
    entry = root/f'{key(context)}.json'
    if not entry.exists() or output.exists():
        return None
    try:
        receipt = json.loads(entry.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(receipt, dict) or receipt.get('context') != context:
        return None
    if not isinstance(receipt.get('source'), str) or not isinstance(receipt.get('files'), dict):
        return None
    source = Path(receipt['source'])
    if not receipt['files'] or 'summary.json' not in receipt['files']:
        return None
    for name, checksum in receipt['files'].items():
        path = (source/name).resolve()
        if not path.is_relative_to(source.resolve()) or not path.is_file() or digest(path) != checksum:
            return None
    stage = output.with_name(output.name+'_reuse_'+uuid.uuid4().hex)
    stage.mkdir(parents=True)
    for name in receipt['files']:
        dest = stage/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source/name, dest)
        if digest(dest) != receipt['files'][name]:
            raise ValueError('Benchmark source changed during copy')
    result = json.loads((stage/'summary.json').read_text(encoding='utf-8'))
    (stage/'benchmark_reuse.json').write_text(json.dumps({'key': key(context),
        'source': str(source), 'reused': True, 'saved_variant_cost_replays': len(result['rows'])}, indent=2), encoding='utf-8')
    stage.rename(output)
    return result


def publish(root: Path, context: dict, output: Path, plans: dict, settings: dict) -> None:
    from quant.research.factor_battery_cost_report import load_cost_history
    result = json.loads((output/'summary.json').read_text(encoding='utf-8'))
    expected = {(variant, cost) for variant in plans for cost in settings['portfolio']['cost_multipliers']}
    actual = [(row['variant'], row['cost_multiplier']) for row in result['rows']]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError('Incomplete benchmark scenarios cannot be cached')
    for variant, cost in expected:
        load_cost_history(output, variant, cost, settings['run']['as_of'])
    files = {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob('*'))
             if p.is_file() and not any(part.startswith('.') for part in p.relative_to(output).parts)
             and p.name != 'benchmark_reuse.json'}
    root.mkdir(parents=True, exist_ok=True)
    receipt = {'context': context, 'source': str(output.resolve()), 'files': files}
    temporary = root/f'{key(context)}.{uuid.uuid4().hex}.tmp'
    temporary.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    temporary.replace(root/f'{key(context)}.json')
    (output/'benchmark_reuse.json').write_text(json.dumps({'key': key(context),
        'reused': False, 'saved_variant_cost_replays': 0}), encoding='utf-8')
