import pytest

from quant.data.connectors.baostock_access import AccessBudget, BaoStockAccessPaused, BudgetSocket


def _slot_worker(root, cwd, *, timeout=3, hold=False):
    import os
    import subprocess
    import sys
    from pathlib import Path
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]/'src'))
    code = ('from pathlib import Path\nimport time\n'
            'from quant.data.connectors.baostock_access import session_slot\n'
            'print("ready", flush=True)\n'
            f'with session_slot(Path({str(root)!r}), timeout={timeout}):\n'
            ' print("acquired", flush=True)\n' + (' time.sleep(30)\n' if hold else ' pass\n'))
    return subprocess.Popen([sys.executable, '-c', code], cwd=cwd, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_waiting_process_acquires_after_release_from_different_cwd(tmp_path):
    from quant.data.connectors.baostock_access import session_slot
    root = tmp_path/'shared'
    other = tmp_path/'other_checkout'
    other.mkdir()
    with session_slot(root):
        child = _slot_worker(root, other)
        try:
            assert child.stdout.readline().strip() == 'ready'
            assert child.poll() is None
        except BaseException:
            child.kill()
            child.communicate()
            raise
    try:
        out, err = child.communicate(timeout=15)
        assert child.returncode == 0, err
        assert out.strip() == 'acquired'
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate()


def test_wait_timeout_does_not_acquire(tmp_path):
    from quant.data.connectors.baostock_access import session_slot
    with session_slot(tmp_path):
        child = _slot_worker(tmp_path, tmp_path, timeout=0.2)
        try:
            out, err = child.communicate(timeout=15)
            assert child.returncode != 0 and 'wait timed out' in err
            assert 'acquired' not in out
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()


def test_crashed_owner_releases_slot(tmp_path):
    from quant.data.connectors.baostock_access import session_slot
    child = _slot_worker(tmp_path, tmp_path, hold=True)
    try:
        assert child.stdout.readline().strip() == 'ready'
        assert child.stdout.readline().strip() == 'acquired'
    finally:
        child.kill()
        child.communicate(timeout=15)
    with session_slot(tmp_path, timeout=1):
        pass


def test_budget_survives_restart_counts_failures_and_rolls(tmp_path):
    now = [100000.0]
    clock = lambda: now[0]
    def sleep(seconds):
        now[0] += seconds
    first = AccessBudget(tmp_path, limit=2, clock=clock, sleep=sleep)
    class BrokenSocket:
        def send(self, data):
            raise ConnectionError('failed send')
    with pytest.raises(ConnectionError):
        BudgetSocket(BrokenSocket(), first).send(b'login')
    first.db.close()
    second = AccessBudget(tmp_path, limit=2, clock=clock, sleep=sleep)
    second.reserve()
    assert now[0] == 100001.0
    with pytest.raises(BaoStockAccessPaused, match='budget'):
        second.reserve()
    now[0] += 86400
    second.reserve()
    second.db.close()


def test_blacklist_persists_without_sending(tmp_path):
    budget = AccessBudget(tmp_path)
    budget.block()
    budget.db.close()
    budget = AccessBudget(tmp_path)
    class Socket:
        def send(self, data):
            pytest.fail('blocked requests must never reach socket')
    with pytest.raises(BaoStockAccessPaused, match='blacklist'):
        BudgetSocket(Socket(), budget).send(b'query')
    assert budget.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] == 0
    budget.db.close()


def test_session_lock_excludes_another_process(tmp_path):
    import subprocess
    import sys
    from quant.data.realtime import single_writer
    path = tmp_path / 'session.lock'
    with single_writer(path):
        result = subprocess.run([sys.executable, '-c',
            'from pathlib import Path; from quant.data.realtime import single_writer; '
            f'\nwith single_writer(Path({str(path)!r})): pass'], capture_output=True)
    assert result.returncode != 0
    with single_writer(path):
        pass


def test_connector_blacklist_blocks_next_login(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from quant.data.connectors import baostock_access
    from quant.data.connectors.baostock import BaostockConnector
    monkeypatch.setattr(baostock_access, 'ROOT', tmp_path)
    calls = []
    def login():
        calls.append('login')
        return SimpleNamespace(error_code='10001011', error_msg='blacklisted')
    client = SimpleNamespace(__name__='baostock', login=login, logout=lambda: calls.append('logout'))
    for _ in range(2):
        with pytest.raises(BaoStockAccessPaused):
            with BaostockConnector(client)._session():
                pytest.fail('blacklisted session opened')
    assert calls == ['login']


@pytest.mark.parametrize('failure', ['query', 'logout_return', 'logout_raise', 'success'])
def test_connector_closes_socket_before_releasing_session(monkeypatch, tmp_path, failure):
    from types import SimpleNamespace
    from quant.data.connectors import baostock_access
    from quant.data.connectors.baostock import BaostockConnector
    from quant.data.realtime import single_writer
    transport = pytest.importorskip('baostock.util.socketutil')
    monkeypatch.setattr(baostock_access, 'ROOT', tmp_path)
    closed = []
    peer = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(transport.SocketUtil, 'connect', lambda _: setattr(transport.context, 'default_socket', peer))
    def login():
        transport.SocketUtil().connect()
        return SimpleNamespace(error_code='0')
    def logout():
        assert failure != 'query', 'Never reuse a failed query stream for logout'
        if failure == 'logout_raise':
            raise ConnectionError('logout timeout')
        return SimpleNamespace(error_code='10002007' if failure == 'logout_return' else '0', error_msg='fixture')
    client = SimpleNamespace(__name__='baostock', login=login, logout=logout)
    def run():
        with BaostockConnector(client)._session():
            if failure == 'query':
                raise ConnectionError('query timeout')
    if failure == 'success':
        run()
    else:
        with pytest.raises((ConnectionError, RuntimeError)):
            run()
    assert closed and transport.context.default_socket is None
    with single_writer(tmp_path/'session.lock'):
        budget = AccessBudget(tmp_path)
        event = budget.db.execute('SELECT event FROM sessions ORDER BY at DESC LIMIT 1').fetchone()[0]
        assert event == ('closed' if failure == 'success' else 'failed')
        if failure != 'success':
            waits = []
            budget.sleep = waits.append
            budget.begin_session()
            assert len(waits) == 1 and 0 < waits[0] <= 60
        budget.db.close()
