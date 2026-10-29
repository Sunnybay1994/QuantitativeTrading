import hashlib
import json
import shutil

import polars as pl
import pytest

from quant.data.m3_g1_candidate import M3G1CandidateError
from tests.support.g1_candidate_fixture import DEFAULT, load_candidate
from tests.unit.test_m3_g1_candidate import _build_inputs


@pytest.fixture(scope='module')
def inputs():
    return _build_inputs()


def _copy(tmp_path):
    folder = tmp_path/'fixture'
    shutil.copytree(DEFAULT, folder)
    return folder


def _resign(folder, name):
    path = folder/'manifest.json'
    value = json.loads(path.read_text(encoding='utf-8'))
    value['files'][name] = hashlib.sha256((folder/name).read_bytes()).hexdigest()
    path.write_text(json.dumps(value),encoding='utf-8')


def test_fixed_fixture_retains_full_population_tables_and_receipts(inputs):
    value = load_candidate(inputs)
    assert value.eligible_keys['symbol'].n_unique() == 300
    assert len(value.table_content_digests) == 14
    assert value.input_receipts and value.primary_candidate_key


def test_modified_parquet_bytes_fail_before_deserialization(inputs, tmp_path):
    folder = _copy(tmp_path)
    with (folder/'bars.parquet').open('ab') as stream:
        stream.write(b'tampered')
    with pytest.raises(ValueError,match='checksum mismatch'):
        load_candidate(inputs,folder=folder)


def test_rehashed_table_still_fails_real_candidate_identity_verification(inputs, tmp_path):
    folder = _copy(tmp_path)
    path = folder/'bars.parquet'
    pl.read_parquet(path).with_columns((pl.col('close')+1).alias('close')).write_parquet(path)
    _resign(folder,'bars.parquet')
    with pytest.raises(M3G1CandidateError):
        load_candidate(inputs,folder=folder)


def test_other_input_plan_is_not_accepted_even_with_rehashed_metadata(inputs, tmp_path):
    folder = _copy(tmp_path)
    path = folder/'candidate.json'
    value = json.loads(path.read_text(encoding='utf-8'))
    value['request_plan_sha256'] = '0'*64
    path.write_text(json.dumps(value),encoding='utf-8')
    _resign(folder,'candidate.json')
    with pytest.raises(ValueError,match='input identity mismatch'):
        load_candidate(inputs,folder=folder)


def test_rehashed_receipt_rows_still_fail_real_identity_verification(inputs, tmp_path):
    folder = _copy(tmp_path)
    path = folder/'input_receipts.parquet'
    pl.read_parquet(path).with_columns((pl.col('row_count')+1).alias('row_count')).write_parquet(path)
    _resign(folder,'input_receipts.parquet')
    with pytest.raises(M3G1CandidateError):
        load_candidate(inputs,folder=folder)
