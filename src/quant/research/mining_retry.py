"""Bounded recovery of existing checkpoints; never bypass data integrity checks."""
import hashlib
from pathlib import Path
import re
import json
import tomllib


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


def failure_kind(errors, run):
    kinds=[]
    for step,error in errors.items():
        if error.endswith(' did not complete'):
            continue
        detail=error
        if re.fullmatch(r'N[1-5]',step) and 'exit=' in error:
            path=run/step/'process.log'
            if path.exists():
                with path.open('rb') as stream:
                    stream.seek(max(0,path.stat().st_size-16384))
                    lines=stream.read().decode('utf-8',errors='replace').splitlines()
                exceptions=[line for line in lines if re.match(r'^[\w.]+(?:Error|Exception):',line)]
                if exceptions:
                    detail=exceptions[-1]
        # Deliberately narrow. Definition/schema/data errors are never transient.
        transient=bool(re.search(r'^(?:TimeoutError|ConnectionError|ConnectionResetError|ConnectTimeout|ReadTimeout):|\[WinError (?:32|33)\]',detail))
        kinds.append('transient' if transient else 'deterministic_or_unknown')
    return 'transient' if kinds and all(k=='transient' for k in kinds) else 'deterministic_or_unknown'
