"""Exercise real receipt validation with a fake child, never a nested full suite."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import pytest

from quant.reporting import doctor, fast_tests as fast


def test_native_timing_order_preserves_all_cases_and_equal_cost_order(tmp_path, monkeypatch):
    from types import SimpleNamespace

    previous = tmp_path/'artifacts/tests/20260101T000000'
    previous.mkdir(parents=True)
    nodes = ['tests/test_fast.py::test_one', 'tests/test_slow.py::test_b',
             'tests/test_slow.py::test_a', 'tests/test_new.py::test_new',
             'tests/test_other.py::test_tie']
    (previous/'receipt.json').write_text(json.dumps({'complete': True}))
    (previous/'collection.json').write_text(json.dumps({'nodeids': nodes}))
    _junit(previous/'tests.xml', nodes)
    tree = ET.parse(previous/'tests.xml')
    for case, seconds in zip(tree.iter('testcase'), (1, 40, 60, 0, 40)):
        case.set('time', str(seconds))
    tree.write(previous/'tests.xml')
    timings = fast._case_costs(tmp_path, time.monotonic())
    assert timings['costs']['tests/test_slow.py::test_a'] == 60
    (tmp_path/'case_costs.json').write_text(json.dumps(timings))
    monkeypatch.setenv('QUANT_TEST_RUN_DIR', str(tmp_path))
    monkeypatch.setattr(fast, '_worker', 'gw0')
    items = [SimpleNamespace(nodeid=node) for node in nodes]
    fast.pytest_collection_modifyitems(items)
    assert [item.nodeid for item in items] == [nodes[2], nodes[1], nodes[4], nodes[0], nodes[3]]
    assert sorted(item.nodeid for item in items) == sorted(nodes)


def _junit(path, nodes, failed=0, control=False):
    from _pytest.junitxml import mangle_test_address

    root = ET.Element('testsuites')
    suite = ET.SubElement(root, 'testsuite')
    for index, node in enumerate(nodes):
        names = mangle_test_address(node)
        case = ET.SubElement(suite, 'testcase', classname='.'.join(names[:-1]), name=names[-1])
        if index < failed:
            ET.SubElement(case, 'failure').text = ('intentional assertion control' if control else 'real fixture failure')
    path.write_bytes(ET.tostring(root, encoding='utf-8'))


@pytest.fixture
def child(tmp_path, monkeypatch):
    sources = ['src/quant/__init__.py', 'src/quant/reporting/fast_tests.py',
               'tests/test_fixture.py', 'pyproject.toml']
    for name in sources:
        path = tmp_path/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# isolated fixture source\n', encoding='utf-8')
    monkeypatch.setattr(fast, '_source_files', lambda root: sources)
    monkeypatch.setattr(fast, '_xdist_available', lambda: True)
    state = dict(mode='failed', control_valid=True, calls=[], stopped=[])

    class Process:
        pid = 424242

        def __init__(self, command, **kwargs):
            self.command, self.options, self.returncode = command, kwargs, None
            state['calls'].append(self)
            output = Path(kwargs['env']['QUANT_TEST_RUN_DIR'])
            junit = Path(command[command.index('--junitxml')+1])
            if 'tests' not in command:
                valid = state['control_valid']
                _junit(junit, ['_quant_assertion_control.py::test_assertions_active'],
                       failed=1 if valid else 0, control=True)
                self.returncode = 1 if valid else 0
                return
            kwargs['stdout'].write(b'partial output\nerror detail\n')
            if state['mode'] == 'timeout':
                return
            nodes = ['tests/test_fixture.py::test_a', 'tests/test_fixture.py::test_b',
                     'tests/test_fixture.py::test_c']
            workers = int(command[command.index('-n')+1])
            signature = hashlib.sha256(json.dumps(nodes, ensure_ascii=True).encode()).hexdigest()
            for index in range(workers):
                record = dict(worker=f'gw{index}', count=3, selection_sha256=signature,
                    optimize=0, assertion_mode='plain', python=sys.executable,
                    prefix=str(Path(sys.prefix).resolve()),
                    module_paths={'quant': str(Path(kwargs['cwd'])/'src/quant/__init__.py'),
                                  'quant.reporting.fast_tests': str(Path(kwargs['cwd'])/'src/quant/reporting/fast_tests.py')})
                if state['mode'] == 'wrong_selection': record['selection_sha256'] = 'wrong'
                if state['mode'] == 'optimized': record['optimize'] = 1
                if state['mode'] == 'outside_source': record['module_paths']['quant'] = str(tmp_path/'src/quant/__init__.py')
                if state['mode'] == 'missing_worker' and index == workers-1: continue
                (output/f'worker_gw{index}.json').write_text(json.dumps(record), encoding='utf-8')
            (output/'collection.json').write_text(json.dumps(dict(nodeids=nodes)), encoding='utf-8')
            if state['mode'] != 'missing_junit':
                _junit(junit, nodes[:2] if state['mode'] == 'partial_junit' else nodes,
                       failed=1 if state['mode'] in ('failed', 'junit_fail_zero_exit') else 0)
            self.returncode = 1 if state['mode'] == 'failed' else 0

        def wait(self, timeout):
            assert 0 < timeout <= 600
            if self.returncode is None:
                raise subprocess.TimeoutExpired(self.command, timeout)
            return self.returncode

        def poll(self):
            return self.returncode

    def stop(process, output, log):
        state['stopped'].append(process)
        process.returncode = 1

    monkeypatch.setattr(fast.subprocess, 'Popen', Process)
    monkeypatch.setattr(fast, '_stop_owned', stop)
    state['root'] = tmp_path
    return state


@pytest.mark.parametrize('timeout', [False, True])
def test_fast_suite_keeps_output_and_enforces_budget(child, timeout):
    child['mode'] = 'timeout' if timeout else 'failed'
    code = doctor.record_fast_tests(child['root'])
    receipt = json.loads((child['root']/'artifacts/tests/latest.json').read_text(encoding='utf-8'))
    log = Path(receipt['log'])
    assert log.is_file() and receipt['timeout_seconds'] == 600
    assert receipt['exit_code'] == code == (124 if timeout else 1)
    assert b'partial output' in log.read_bytes() and b'error detail' in log.read_bytes()
    assert not receipt['accepted_fast']
    if timeout:
        assert receipt['passed'] is None and receipt['failed'] is None and not receipt['complete']
        assert len(child['stopped']) == 1 and child['stopped'][0] is child['calls'][-1]
        assert b'timeout after 600s' in log.read_bytes()
    else:
        assert receipt['passed'] == 2 and receipt['failed'] == 1 and receipt['complete']
    for process in child['calls']:
        assert Path(process.options['cwd']) == Path(receipt['snapshot'])
        assert Path(receipt['snapshot']).is_relative_to(child['root']/'artifacts/tests')
        assert process.options['env']['QUANT_PROJECT_ROOT'] == receipt['snapshot']
    assert (child['root']/'tests/test_fixture.py').read_text() == '# isolated fixture source\n'


def test_complete_zero_exit_receipt_is_backed_by_all_selected_cases(child):
    child['mode'] = 'passed'
    assert doctor.record_fast_tests(child['root']) == 0
    receipt = json.loads((child['root']/'artifacts/tests/latest.json').read_text(encoding='utf-8'))
    assert receipt['accepted_fast'] and receipt['complete']
    assert receipt['passed'] == receipt['selected_count'] == 3
    assert receipt['failed'] == receipt['errors'] == receipt['skipped'] == 0
    assert Path(receipt['snapshot'], 'tests/test_fixture.py').is_file()


@pytest.mark.parametrize('mode', ['partial_junit', 'missing_junit', 'missing_worker',
                                  'wrong_selection', 'optimized', 'outside_source'])
def test_zero_child_exit_cannot_hide_incomplete_or_wrong_scope(child, mode):
    child['mode'] = mode
    assert doctor.record_fast_tests(child['root']) == 2
    receipt = json.loads((child['root']/'artifacts/tests/latest.json').read_text(encoding='utf-8'))
    assert not receipt['complete'] and not receipt['accepted_fast']
    assert receipt['passed'] is None and receipt['failed'] is None
    assert receipt['evidence_error']


def test_broken_assertion_control_stops_before_full_suite(child):
    child['control_valid'] = False
    assert doctor.record_fast_tests(child['root']) == 2
    assert len(child['calls']) == 1
    receipt = json.loads((child['root']/'artifacts/tests/latest.json').read_text(encoding='utf-8'))
    assert 'Assertion control' in receipt['error'] and receipt['passed'] is None


def test_zero_exit_with_real_junit_failure_is_rejected(child):
    child['mode'] = 'junit_fail_zero_exit'
    assert doctor.record_fast_tests(child['root']) == 2
    receipt = json.loads((child['root']/'artifacts/tests/latest.json').read_text(encoding='utf-8'))
    assert receipt['complete'] and receipt['passed'] == 2 and receipt['failed'] == 1
    assert not receipt['accepted_fast'] and 'contradicts' in receipt['evidence_error']


def test_missing_parallel_dependency_never_starts_child(child, monkeypatch):
    monkeypatch.setattr(fast, '_xdist_available', lambda: False)
    assert doctor.record_fast_tests(child['root']) == 2
    assert child['calls'] == []
    receipt = json.loads((child['root']/'artifacts/tests/latest.json').read_text(encoding='utf-8'))
    assert receipt['passed'] is None and not receipt['complete']
    assert 'dev dependencies' in receipt['error']


def test_source_listing_failure_keeps_native_error_and_failed_receipt(child, monkeypatch):
    def fail(root):
        raise subprocess.CalledProcessError(128, ['git', 'ls-files'], output=b'fatal: fixture source listing failed\n')
    monkeypatch.setattr(fast, '_source_files', fail)
    assert doctor.record_fast_tests(child['root']) == 2
    assert child['calls'] == []
    receipt = json.loads((child['root']/'artifacts/tests/latest.json').read_text(encoding='utf-8'))
    assert receipt['passed'] is None and not receipt['complete'] and not receipt['accepted_fast']
    assert receipt['ran_at'].endswith('+08:00')
    assert b'fatal: fixture source listing failed' in Path(receipt['log']).read_bytes()


def test_environment_is_child_only_and_does_not_inherit_half_git_config(tmp_path, monkeypatch):
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'fixture')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'fixture')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'private fixture')
    monkeypatch.setenv('PYTEST_ADDOPTS', '-k narrow_subset')
    monkeypatch.setenv('PYTHONOPTIMIZE', '1')
    monkeypatch.setenv('CONDA_PREFIX', 'wrong-runtime')
    env = fast._environment(tmp_path/'snapshot', tmp_path/'run')
    assert not any(name.startswith('GIT_CONFIG_') for name in env)
    assert 'DEEPSEEK_API_KEY' not in env and 'PYTEST_ADDOPTS' not in env and 'PYTHONOPTIMIZE' not in env
    assert env['CONDA_PREFIX'] == str(Path(sys.prefix).resolve())
    assert all(env[name] == '1' for name in fast.THREAD_VARIABLES)
    assert __import__('os').environ['DEEPSEEK_API_KEY'] == 'private fixture'
    assert __import__('os').environ['CONDA_PREFIX'] == 'wrong-runtime'


def test_source_copy_refuses_parent_traversal(tmp_path, monkeypatch):
    snapshot = tmp_path/'snapshot'
    snapshot.mkdir()
    monkeypatch.setattr(fast, '_source_files', lambda root: ['../outside.py'])
    with pytest.raises(ValueError, match='relative source path'):
        fast._snapshot(tmp_path, snapshot, time.monotonic())
    assert list(snapshot.iterdir()) == []


def test_launch_metadata_failure_still_cleans_its_owned_child(tmp_path, monkeypatch):
    process = type('Process', (), {'pid': 424242})()
    stopped = []
    monkeypatch.setattr(fast.subprocess, 'Popen', lambda *a, **kw: process)
    monkeypatch.setattr(fast, '_json', lambda *a, **kw: (_ for _ in ()).throw(OSError('fixture metadata denied')))
    monkeypatch.setattr(fast, '_stop_owned', lambda current, *a: stopped.append(current))
    with pytest.raises(OSError, match='metadata denied'):
        fast._execute(['fixture'], tmp_path, tmp_path, {}, io.BytesIO(), time.monotonic())
    assert stopped == [process]


def test_worker_failure_is_saved_before_final_junit(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(fast, '_worker', 'gw2')
    monkeypatch.setenv('QUANT_TEST_RUN_DIR', str(tmp_path))
    report = SimpleNamespace(failed=True, nodeid='tests/test_fixture.py::test_a',
                             when='call', longreprtext='AssertionError: fixture evidence')
    fast.pytest_runtest_logreport(report)
    paths = list(tmp_path.glob('failure_gw2_*.json'))
    assert len(paths) == 1
    assert json.loads(paths[0].read_text(encoding='utf-8')) == {
        'nodeid': report.nodeid, 'phase': 'call', 'traceback': report.longreprtext}
