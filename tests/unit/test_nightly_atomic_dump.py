"""Atomic research summary publication survives bounded native Windows contention."""
import json
import os
from pathlib import Path

import pytest

from quant.research import nightly_steps


@pytest.mark.parametrize('native_code', [5, 32, 33])
def test_dump_retries_only_native_contention_without_partial_publication(tmp_path, monkeypatch, native_code):
    destination = tmp_path/'summary.json'
    destination.write_text('{"old": true}', encoding='utf-8')
    original = Path.replace
    attempts, sleeps = [], []

    def replace(source, target):
        attempts.append(source)
        assert json.loads(source.read_text(encoding='utf-8')) == {'state': '完整'}
        assert json.loads(destination.read_text()) == {'old': True}
        if len(attempts) <= 3:
            error = PermissionError('Windows sharing contention')
            error.winerror = native_code
            raise error
        return original(source, target)

    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(nightly_steps.time, 'sleep', sleeps.append)
    nightly_steps.dump(destination, {'state': '完整'})
    # The real final replace can encounter additional native reader contention.
    assert 4 <= len(attempts) <= 10
    assert len(sleeps) == len(attempts) - 1
    assert sleeps[:3] == pytest.approx([0.05, 0.1, 0.15])
    assert json.loads(destination.read_text(encoding='utf-8')) == {'state': '完整'}
    assert not destination.with_suffix('.json.tmp').exists()


def test_dump_persistent_denial_is_bounded_and_preserves_both_payloads(tmp_path, monkeypatch):
    destination = tmp_path/'summary.json'
    destination.write_text('{"old": true}', encoding='utf-8')
    error = PermissionError('persistent access denial')
    error.winerror = 5
    attempts, sleeps = [], []

    def replace(source, target):
        attempts.append(source)
        raise error

    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(nightly_steps.time, 'sleep', sleeps.append)
    with pytest.raises(PermissionError) as caught:
        nightly_steps.dump(destination, {'new': True})
    assert caught.value is error
    assert len(attempts) == 10 and len(sleeps) == 9
    assert sum(sleeps) == pytest.approx(2.25)
    assert json.loads(destination.read_text()) == {'old': True}
    assert json.loads(destination.with_suffix('.json.tmp').read_text()) == {'new': True}


@pytest.mark.parametrize('error', [PermissionError('not native'), FileNotFoundError('missing parent')])
def test_dump_unrelated_errors_propagate_immediately(tmp_path, monkeypatch, error):
    attempts = []

    def replace(source, target):
        attempts.append(source)
        raise error

    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr(nightly_steps.time, 'sleep', lambda _: pytest.fail('must not retry'))
    with pytest.raises(type(error)) as caught:
        nightly_steps.dump(tmp_path/'summary.json', {'new': True})
    assert caught.value is error
    assert len(attempts) == 1


def test_dump_nonfinite_values_never_replace_prior_summary(tmp_path):
    destination = tmp_path/'summary.json'
    destination.write_text('{"old": true}', encoding='utf-8')
    with pytest.raises(ValueError):
        nightly_steps.dump(destination, {'score': float('nan')})
    assert json.loads(destination.read_text()) == {'old': True}
    assert not destination.with_suffix('.json.tmp').exists()


@pytest.mark.skipif(os.name != 'nt', reason='native Windows sharing handle')
def test_dump_recovers_after_real_windows_reader_releases_delete_denial(tmp_path, monkeypatch):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
    destination = tmp_path/'summary.json'
    destination.write_text('{"old": true}', encoding='utf-8')
    # Open a genuine reader with read/write sharing but without FILE_SHARE_DELETE.
    handle = create(str(destination), 0x80000000, 3, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    original = Path.replace
    errors = []
    released = False

    def replace(source, target):
        nonlocal released
        try:
            return original(source, target)
        except PermissionError as exc:
            errors.append(exc.winerror)
            assert json.loads(destination.read_text()) == {'old': True}
            if not released:
                assert close(handle)
                released = True
            raise

    monkeypatch.setattr(Path, 'replace', replace)
    try:
        nightly_steps.dump(destination, {'new': True})
    finally:
        if not released:
            close(handle)
    assert 1 <= len(errors) <= 9 and all(code in (5, 32, 33) for code in errors)
    assert json.loads(destination.read_text()) == {'new': True}
    assert not destination.with_suffix('.json.tmp').exists()
