"""Registry publication retries the rename inside the existing writer lock."""
from pathlib import Path

import polars as pl
import pytest

from quant.reporting import experiment_registry as registry_module
from quant.reporting.leaderboard import write_leaderboard
from tests.unit.test_experiment_registry import saved_run


def test_append_and_leaderboard_publish_retry_without_recomputing_or_losing_rows(tmp_path, monkeypatch):
    registry, board = tmp_path/'registry.parquet', tmp_path/'board.md'
    old = saved_run(tmp_path/'old')
    new = saved_run(tmp_path/'new', 'PAPER_CANDIDATE')
    registry_module.register_run(old, registry, board)
    original = Path.replace
    attempts, injected = {}, set()

    def replace(source, target):
        if target == registry:
            stage = 'append' if source == registry.with_suffix('.parquet.tmp') else 'leaderboard'
            attempts[stage] = attempts.get(stage, 0) + 1
            # The complete previous table remains readable until atomic publication.
            prior = pl.read_parquet(registry)
            assert prior.height == (1 if stage == 'append' else 2)
            if stage not in injected:
                injected.add(stage)
                error = PermissionError('native destination temporarily busy')
                error.winerror = 5
                raise error
        return original(source, target)

    monkeypatch.setattr(Path, 'replace', replace)
    assert registry_module.register_run(new, registry, board) == 2
    assert injected == {'append', 'leaderboard'}
    assert all(2 <= attempts[stage] <= 10 for stage in injected)
    frame = pl.read_parquet(registry)
    expected = registry_module.records_from_run(old) + registry_module.records_from_run(new)
    protected = ['run_path', 'variant', 'conclusion'] + [
        f'{metric}_{cost}' for metric in (*registry_module.METRICS, 'excess')
        for cost in registry_module.COSTS.values()
    ]
    assert frame.select(protected).sort('run_path').equals(
        pl.from_dicts(expected, infer_schema_length=None).select(protected).sort('run_path'))
    assert 'PAPER_CANDIDATE' in board.read_text(encoding='utf-8')


@pytest.mark.parametrize('native_code', [5, 32, 33])
def test_persistent_native_denial_preserves_old_registry_and_raises(tmp_path, monkeypatch, native_code):
    destination, source = tmp_path/'registry.parquet', tmp_path/'staged.parquet'
    destination.write_bytes(b'prior registry')
    source.write_bytes(b'complete new registry')
    error = PermissionError('persistent native denial')
    error.winerror = native_code
    attempts, waits = [], []

    def replace(staged, target):
        attempts.append(staged)
        raise error

    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(registry_module.time, 'sleep', waits.append)
    with pytest.raises(PermissionError) as caught:
        registry_module._replace_registry_file(source, destination)
    assert caught.value is error
    assert len(attempts) == 10 and sum(waits) == pytest.approx(2.25)
    assert destination.read_bytes() == b'prior registry'
    assert source.read_bytes() == b'complete new registry'


def test_non_native_permission_error_is_not_hidden(tmp_path, monkeypatch):
    error = PermissionError('ACL failure')
    calls = []

    def replace(source, target):
        calls.append(source)
        raise error

    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(registry_module.time, 'sleep', lambda _: pytest.fail('must not retry'))
    with pytest.raises(PermissionError) as caught:
        registry_module._replace_registry_file(tmp_path/'stage', tmp_path/'registry')
    assert caught.value is error and len(calls) == 1


def test_failed_leaderboard_atomic_publication_keeps_prior_registry_and_reports(tmp_path, monkeypatch):
    registry, board = tmp_path/'registry.parquet', tmp_path/'board.md'
    registry_module.register_run(saved_run(tmp_path/'run'), registry, board)
    factor_board = board.with_name('排行榜_因子.md')
    before = [path.read_bytes() for path in (registry, board, factor_board)]
    original = Path.replace

    def replace(source, target):
        if target == registry:
            error = PermissionError('destination locked')
            error.winerror = 32
            raise error
        return original(source, target)

    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(registry_module.time, 'sleep', lambda _: None)
    with pytest.raises(PermissionError):
        write_leaderboard(registry, board)
    assert [path.read_bytes() for path in (registry, board, factor_board)] == before
    assert not list(tmp_path.glob('registry.parquet.*.tmp'))
