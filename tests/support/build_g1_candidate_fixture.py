"""Explicitly regenerate synthetic constructor tables in a NEW directory.

python -m tests.support.build_g1_candidate_fixture --output artifacts/tmp/g1-new
"""

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import time
from pathlib import Path

import polars as pl

from quant.data.m3_g1_candidate import build_g1_candidate
from tests.unit.test_m3_g1_candidate import _build_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    out = parser.parse_args().output
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    candidate = build_g1_candidate(inputs=_build_inputs())
    metadata, frames = {}, []
    for field in dataclasses.fields(candidate):
        value = getattr(candidate, field.name)
        if isinstance(value, pl.DataFrame):
            value.write_parquet(out/(field.name+'.parquet'))
            frames.append(field.name)
        elif field.name == 'request_plan':
            metadata['request_plan_sha256'] = value.plan_sha256
        elif field.name == 'build_spec':
            metadata[field.name] = dataclasses.asdict(value)
        elif field.name == 'input_receipts':
            pl.DataFrame([dataclasses.asdict(item) for item in value]).write_parquet(
                out/'input_receipts.parquet')
        else:
            metadata[field.name] = value.isoformat() if isinstance(value, dt.date) else value
    metadata['frames'] = frames
    (out/'candidate.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    root = Path(__file__).resolve().parents[2]
    sources = ['src/quant/data/m3_g1_candidate.py', 'src/quant/data/m3_execution_facts.py',
               'tests/unit/test_m3_g1_candidate.py']
    manifest = dict(synthetic=True, generation_seconds=round(time.monotonic()-started,2),
                    eligible_symbols=candidate.eligible_keys['symbol'].n_unique(),
                    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())},
                    source_sha256={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(out)


if __name__ == '__main__':
    main()
