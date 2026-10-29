"""Bounded recovery of existing checkpoints; never bypass data integrity checks."""
import datetime as dt
import hashlib
from pathlib import Path
import re
import json
import tomllib

# Daily data writers may rewrite clean parquet after N2 froze source bytes.
# Preserve the frozen experiment; retrying with new bytes changes its identity.
_STALE_GP_CONTEXT = re.compile(
    r'ValueError: Frozen GP minute source (?:checksum changed|changed|inventory changed):?|'
    r'ValueError: Frozen GP context source (?:checksum changed|changed|disappeared):|'
    r'ValueError: Frozen GP base source inventory changed'
)


def admission_dependency(run, steps):
    """Recognize only a proven stale-control wait, not arbitrary N4 failures."""
    failed = {key for key, row in steps.items() if not row.get('ok')}
    if failed != {'N4'} or not all(steps.get(k, {}).get('ok') for k in ('N1', 'N2', 'N3', 'N5')):
        return None
    try:
        lines = (run/'N4/process.log').read_text(encoding='utf-8').splitlines()
        exceptions = [line for line in lines if re.match(r'^[\w.]+(?:Error|Exception):', line)]
        match = re.fullmatch(
            r'ValueError: ADMITTED controls end (\d{4}-\d{2}-\d{2}), required (\d{4}-\d{2}-\d{2}); complete monthly full-library battery before retry',
            exceptions[-1] if exceptions else '')
        if not match:
            return None
        result = json.loads((run/'N3/result.json').read_text(encoding='utf-8'))
        settings = json.loads((Path(result['batch'])/'settings.json').read_text(encoding='utf-8'))
        if str(settings['as_of']) != match[2]:
            return None
        from quant.research.nightly_steps import admission_reference
        resolved = admission_reference(settings)
        known = str(tomllib.loads((Path(resolved['reference_statistics'])/'battery.toml').read_text(encoding='utf-8'))['run']['as_of'])
        if known > match[2]:
            return None
        return {'kind': 'monthly_admission_controls', 'required_as_of': match[2],
                'available_as_of': known, 'ready': known == match[2]}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def code_fingerprint():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    # Backtest/domain changes also alter N3 cost replays, so they must trigger a probe.
    for package in ('backtest', 'data', 'domain', 'factors', 'portfolio', 'research'):
        for path in sorted((root/package).rglob('*.py')):
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _exception_detail(step: str, error: str, run: Path) -> str:
    detail = error
    if re.fullmatch(r'N[1-5]', step) and 'exit=' in error:
        path = run / step / 'process.log'
        if path.exists():
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 16384))
                lines = stream.read().decode('utf-8', errors='replace').splitlines()
            exceptions = [line for line in lines if re.match(r'^[\w.]+(?:Error|Exception):', line)]
            if exceptions:
                detail = exceptions[-1]
    return detail


def is_stale_gp_context_error(detail: str) -> bool:
    """True when frozen N2 source bytes drifted under a concurrent data writer."""
    return bool(_STALE_GP_CONTEXT.search(detail or ''))


def errors_indicate_stale_gp_context(errors: dict, run: Path) -> bool:
    """Inspect worker exit text / process.log tails for a stale GP freeze."""
    for step, error in (errors or {}).items():
        if error.endswith(' did not complete'):
            continue
        if is_stale_gp_context_error(_exception_detail(step, error, run)):
            return True
    return False


def invalidate_stale_gp_context(n2: Path) -> dict:
    """Record deterministic input invalidation without moving frozen evidence.

    A retry must restore the original bytes. Re-pinning hashes or discarding
    population/fitness inside the same batch is never a recovery operation.
    """
    n2 = Path(n2)
    receipt_path = n2/'frozen_input_failure.json'
    if receipt_path.exists():
        return json.loads(receipt_path.read_text(encoding='utf-8'))
    preserved = [str(n2/name) for name in ('full_context', 'fitness_cache.json',
        'search_checkpoint.json', 'search_progress.json', 'best_so_far.json',
        'expression_aliases.json') if (n2/name).exists()]
    manifest = n2/'full_context/source_manifest.json'
    receipt = dict(recorded_at=dt.datetime.now().isoformat(), kind='frozen_inputs_invalidated',
        error=_exception_detail('N2', 'N2 exit=1', n2.parent),
        preserved=preserved, source_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest()
            if manifest.exists() else None,
        reason='Frozen source bytes changed; original inputs and checkpoints retained',
        recovery_action='Restore original source bytes, or retire the invalid batch with evidence and start a distinct batch from stable inputs',
        strategy_result=None)
    if n2.exists():
        from quant.data.realtime_store import atomic_json
        atomic_json(receipt_path, receipt)
    return receipt


def frozen_context_restored(n2: Path) -> bool:
    """Resume only when the recorded manifest and every original source match.

    Inventory changes require a separate audit; matching old files alone cannot
    prove that newly added input files have been removed from a reader's view.
    """
    try:
        receipt = json.loads((n2/'frozen_input_failure.json').read_text(encoding='utf-8'))
        error = receipt.get('error', '')
        if 'source inventory changed' in error or 'legacy minute inputs lack a frozen snapshot' in error:
            return False
        manifest = n2/'full_context/source_manifest.json'
        payload = manifest.read_bytes()
        if hashlib.sha256(payload).hexdigest() != receipt.get('source_manifest_sha256'):
            return False
        sources = json.loads(payload)
        if not isinstance(sources, dict) or not sources:
            return False
        from quant.data.gp_context_inputs import sha256
        for name, expected in sources.items():
            source = Path(name)
            if expected is None:
                if source.exists():
                    return False
            elif sha256(source) != expected:
                return False
        if 'Frozen GP minute source' in error:
            folder = n2/'full_context/minute_inputs'
            completed = folder/'completed.json'
            if not completed.exists():
                return False
            saved = json.loads(completed.read_text(encoding='utf-8'))
            from quant.data.gp_minute_snapshot import freeze
            freeze(Path(saved['data_root']),folder)
        return True
    except (OSError, ValueError, TypeError):
        return False


def failure_kind(errors, run):
    if errors_indicate_stale_gp_context(errors, run):
        return 'frozen_inputs_invalidated'
    kinds=[]
    for step,error in errors.items():
        if error.endswith(' did not complete'):
            continue
        detail=_exception_detail(step, error, run)
        # Deliberately narrow. Definition/schema/data errors are never transient.
        # WinError 5/32/33: destination briefly locked during atomic replace / sharing.
        transient=bool(re.search(
            r'^(?:TimeoutError|ConnectionError|ConnectionResetError|ConnectTimeout|ReadTimeout):|'
            r'\[WinError (?:5|32|33)\]', detail))
        kinds.append('transient' if transient else 'deterministic_or_unknown')
    return 'transient' if kinds and all(k=='transient' for k in kinds) else 'deterministic_or_unknown'


def invalidated_batch(batch: Path) -> bool:
    """Recognize an explicit, evidence-bound input retirement, never a rejection."""
    path = batch/'input_invalidation.json'
    if not path.exists():
        return False
    receipt = json.loads(path.read_text(encoding='utf-8'))
    if (receipt.get('batch') != batch.name or receipt.get('classification') != 'FROZEN_INPUTS_INVALIDATED'
            or receipt.get('strategy_result', 'missing') is not None or not receipt.get('evidence')):
        raise ValueError('Invalid batch input-invalidation receipt')
    for row in receipt['evidence']:
        source = Path(row['path'])
        if hashlib.sha256(source.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError(f'Batch input-invalidation evidence changed: {source}')
    return True


def retired_gp_result(n2: Path) -> dict | None:
    """Allow the original battery to proceed after a defective GP is retired."""
    path = n2/'computation_invalidation.json'
    if not path.exists():
        return None
    receipt = json.loads(path.read_text(encoding='utf-8'))
    if receipt.get('classification') != 'INVALID_COMPUTATION' or not receipt.get('evidence'):
        raise ValueError('Invalid GP computation retirement receipt')
    for row in receipt['evidence']:
        source = Path(row['path'])
        if hashlib.sha256(source.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError(f'GP computation retirement evidence changed: {source}')
    return dict(skipped=True,classification='INVALID_COMPUTATION',candidates=0,
                strategy_result=None,reason=receipt['reason'],receipt=str(path))
