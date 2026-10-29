"""Fixed synthetic G1 tables for constructor tests; never mock identity verification."""

import datetime as dt
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import polars as pl

from quant.data.m3_g1_candidate import G1Candidate, G1ReceiptProjectionV1, _TABLE_ATTRS

DEFAULT = Path(__file__).resolve().parents[1]/'fixtures/g1_candidate'


def load_candidate(inputs, *, folder=DEFAULT):
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    names = {'candidate.json', 'input_receipts.parquet'} | {name+'.parquet' for name in _TABLE_ATTRS.values()}
    if set(manifest['files']) != names or manifest['synthetic'] is not True:
        raise ValueError('Synthetic G1 fixture inventory mismatch')
    for name in sorted(names):
        if hashlib.sha256((folder/name).read_bytes()).hexdigest() != manifest['files'][name]:
            raise ValueError('Synthetic G1 fixture checksum mismatch: '+name)
    value = json.loads((folder/'candidate.json').read_text(encoding='utf-8'))
    if (value.pop('build_spec') != asdict(inputs.build_spec)
            or value.pop('request_plan_sha256') != inputs.request_plan.plan_sha256):
        raise ValueError('Synthetic G1 fixture input identity mismatch; regenerate explicitly')
    frames = value.pop('frames')
    if set(frames) != set(_TABLE_ATTRS.values()) or len(frames) != len(set(frames)):
        raise ValueError('Synthetic G1 fixture table inventory mismatch')
    for name in frames:
        value[name] = pl.read_parquet(folder/(name+'.parquet'))
    for name in ('signal_start', 'signal_end', 'history_start', 'history_end'):
        value[name] = dt.date.fromisoformat(value[name])
    receipts = pl.read_parquet(folder/'input_receipts.parquet').to_dicts()
    value['input_receipts'] = tuple(G1ReceiptProjectionV1(
        **{**row, 'columns': tuple(row['columns'])}) for row in receipts)
    value['table_content_digests'] = tuple(tuple(row) for row in value['table_content_digests'])
    # Real constructor recomputes table/required-key identity and checks every receipt.
    return G1Candidate(build_spec=inputs.build_spec, request_plan=inputs.request_plan, **value)
