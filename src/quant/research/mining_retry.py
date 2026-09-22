"""Bounded recovery of existing checkpoints; never bypass data integrity checks."""
import hashlib
from pathlib import Path
import re


def code_fingerprint():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for package in ('data', 'factors', 'research'):
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
