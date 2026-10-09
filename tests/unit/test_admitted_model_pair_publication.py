from pathlib import Path

import pytest

from quant.research import admitted_model_pair_publication as publication


def prepared(tmp_path):
    stage = tmp_path/'.2023-ready'
    stage.mkdir()
    for name in publication.REQUIRED:
        (stage/name).write_bytes(('saved '+name).encode())
    return stage, tmp_path/'2023'


def test_transient_lock_retries_only_publication_and_preserves_exact_bytes(tmp_path, monkeypatch):
    stage, target = prepared(tmp_path)
    original = {p.name: p.read_bytes() for p in stage.iterdir()}
    rename = Path.rename
    calls, delays = [], []
    def locked(self, destination):
        calls.append((self, destination))
        if len(calls) < 3:
            raise PermissionError('Windows scanner has the directory open')
        return rename(self, destination)
    monkeypatch.setattr(Path, 'rename', locked)
    monkeypatch.setattr(publication.time, 'sleep', delays.append)
    publication.publish_completed_year(stage, target)
    assert calls == [(stage.resolve(), target.resolve())]*3
    assert delays == [.1, .3]
    assert not stage.exists()
    assert {p.name: p.read_bytes() for p in target.iterdir()} == original


def test_persistent_denial_keeps_staging_after_bounded_attempts(tmp_path, monkeypatch):
    stage, target = prepared(tmp_path)
    calls, delays = [], []
    def denied(self, destination):
        calls.append(self)
        raise PermissionError('Persistent denial')
    monkeypatch.setattr(Path, 'rename', denied)
    monkeypatch.setattr(publication.time, 'sleep', delays.append)
    with pytest.raises(PermissionError, match='Persistent'):
        publication.publish_completed_year(stage, target)
    assert len(calls) == 4 and delays == [.1, .3, 1.]
    assert stage.is_dir() and not target.exists()
    assert all((stage/name).is_file() for name in publication.REQUIRED)


def test_existing_completed_year_is_never_replaced(tmp_path, monkeypatch):
    stage, target = prepared(tmp_path)
    target.mkdir(); (target/'account.json').write_text('original completed state')
    monkeypatch.setattr(Path, 'rename', lambda *_: pytest.fail('Must not try replacing target'))
    with pytest.raises(FileExistsError):
        publication.publish_completed_year(stage, target)
    assert (target/'account.json').read_text() == 'original completed state'
    assert stage.is_dir()


def test_concurrent_completed_target_stops_retry_and_retains_staging(tmp_path, monkeypatch):
    stage, target = prepared(tmp_path)
    def concurrent(self, destination):
        target.mkdir()
        (target/'account.json').write_text('other publisher')
        raise PermissionError('Destination appeared')
    monkeypatch.setattr(Path, 'rename', concurrent)
    monkeypatch.setattr(publication.time, 'sleep', lambda _: pytest.fail('Do not retry over another target'))
    with pytest.raises(PermissionError, match='appeared'):
        publication.publish_completed_year(stage, target)
    assert stage.is_dir() and (target/'account.json').read_text() == 'other publisher'


def test_non_permission_error_is_not_retried(tmp_path, monkeypatch):
    stage, target = prepared(tmp_path)
    def broken(*_):
        raise OSError('Disk problem')
    monkeypatch.setattr(Path, 'rename', broken)
    monkeypatch.setattr(publication.time, 'sleep', lambda _: pytest.fail('Not a transient permission failure'))
    with pytest.raises(OSError, match='Disk'):
        publication.publish_completed_year(stage, target)
    assert stage.is_dir()


def test_incomplete_year_cannot_publish(tmp_path, monkeypatch):
    stage, target = prepared(tmp_path)
    (stage/'orders.parquet').unlink()
    monkeypatch.setattr(Path, 'rename', lambda *_: pytest.fail('Incomplete stage must not publish'))
    with pytest.raises(ValueError, match='every completed'):
        publication.publish_completed_year(stage, target)


def test_cross_parent_publication_is_rejected(tmp_path):
    stage, _ = prepared(tmp_path)
    with pytest.raises(ValueError, match='sibling'):
        publication.publish_completed_year(stage, tmp_path/'other'/'2023')
