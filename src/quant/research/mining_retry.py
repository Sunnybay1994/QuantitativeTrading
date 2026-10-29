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
    """Archive freeze + fitness so the next N2 attempt re-pins current source bytes.

    Does not disable checksum checks: the next FullMarketInputs build re-tracks and
    freezes whatever is on disk now. Population/fitness checkpoints are cleared
    because their scores are bound to the previous source bytes.
    """
    n2 = Path(n2)
    if not n2.exists():
        return {'archived': [], 'recovery': None}
    stamp = dt.datetime.now().strftime('%Y%m%dT%H%M%S%f')
    recovery = n2 / 'stale_context_recovery'
    recovery.mkdir(parents=True, exist_ok=True)
    archived = []
    for name in ('full_context', 'fitness_cache.json', 'search_checkpoint.json',
                 'search_progress.json', 'best_so_far.json', 'expression_aliases.json'):
        path = n2 / name
        if not path.exists():
            continue
        dest = recovery / f'{path.name}.{stamp}'
        path.replace(dest)
        archived.append(str(dest))
    receipt = {
        'archived_at': dt.datetime.now().isoformat(),
        'archived': archived,
        'reason': 'Frozen GP context source changed under daily data refresh; re-freeze on next N2',
    }
    (recovery / f'invalidate_{stamp}.json').write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    return receipt


def failure_kind(errors, run):
    kinds=[]
    for step,error in errors.items():
        if error.endswith(' did not complete'):
            continue
        detail=_exception_detail(step, error, run)
        # Deliberately narrow. Definition/schema/data errors are never transient.
        # WinError 5/32/33: destination briefly locked during atomic replace / sharing.
        # Stale GP freeze: concurrent clean-bar rewrite; invalidate_stale_gp_context recovers.
        transient=bool(re.search(
            r'^(?:TimeoutError|ConnectionError|ConnectionResetError|ConnectTimeout|ReadTimeout):|'
            r'\[WinError (?:5|32|33)\]|'
            r'ValueError: Frozen GP context source (?:checksum changed|changed|disappeared):|'
            r'ValueError: Frozen GP base source inventory changed', detail))
        kinds.append('transient' if transient else 'deterministic_or_unknown')
    return 'transient' if kinds and all(k=='transient' for k in kinds) else 'deterministic_or_unknown'
