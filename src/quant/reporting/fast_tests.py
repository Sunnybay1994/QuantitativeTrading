"""Bounded, source-isolated fast tests and the worker evidence used by doctor."""
from __future__ import annotations

from collections import Counter
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

TIMEOUT_SECONDS = 600
SOURCE_PATHS = ('src', 'legacy', 'data/external', 'tests', 'configs', 'docs', 'scripts',
                'pyproject.toml', 'conftest.py', 'pytest.ini', 'setup.cfg', 'tox.ini', '*.md')
THREAD_VARIABLES = ('POLARS_MAX_THREADS', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                    'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS')


def _json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    for attempt in range(10):
        try:
            temporary.replace(path)
            return
        except PermissionError as exc:
            if getattr(exc, 'winerror', None) not in (5, 32, 33) or attempt == 9:
                raise
            time.sleep(.05*(attempt+1))


def _remaining(start: float) -> float:
    remaining = TIMEOUT_SECONDS-(time.monotonic()-start)
    if remaining <= 0:
        raise subprocess.TimeoutExpired('fast test budget', TIMEOUT_SECONDS)
    return remaining


def _source_files(root: Path) -> list[str]:
    names = subprocess.check_output(['git', 'ls-files', '--cached', '--others',
        '--exclude-standard', '-z', '--', *SOURCE_PATHS], cwd=root, timeout=30,
        stderr=subprocess.STDOUT)
    return sorted(set(names.decode('utf-8').split('\0'))-{''})


def _xdist_available() -> bool:
    return importlib.util.find_spec('xdist') is not None


def _snapshot(root: Path, destination: Path, start: float) -> list[dict]:
    manifest = []
    for name in _source_files(root):
        _remaining(start)
        relative = Path(name)
        if relative.anchor or relative.drive or '..' in relative.parts:
            raise ValueError('Invalid relative source path: '+name)
        source = root/relative
        if source.is_symlink() or not source.resolve().is_relative_to(root):
            raise ValueError('Source snapshot cannot follow links outside its checkout: '+name)
        if not source.is_file():
            continue
        target = destination/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        with source.open('rb') as original, target.open('wb') as copied:
            while True:
                _remaining(start)
                chunk = original.read(1024*1024)
                if not chunk:
                    break
                copied.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        manifest.append(dict(path=name, bytes=size, sha256=digest.hexdigest()))
    if (not (destination/'src/quant').is_dir() or not (destination/'tests').is_dir()
            or not (destination/'pyproject.toml').is_file()):
        raise ValueError('Fast tests require a source checkout containing src/quant, tests and pyproject.toml')
    return manifest


def _environment(snapshot: Path, output: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in list(env):
        if name.startswith('GIT_CONFIG_') or re.search('KEY|TOKEN|SECRET|PASSWORD|WEBHOOK', name, re.I):
            env.pop(name)
    for name in ('PYTEST_ADDOPTS', 'PYTHONOPTIMIZE', 'PYTEST_XDIST_WORKER', 'PYTEST_CURRENT_TEST'):
        env.pop(name, None)
    prefix = Path(sys.prefix).resolve()
    env.update(PYTHONPATH=str(snapshot/'src'), PYTHONUTF8='1', PYTHONIOENCODING='utf-8:backslashreplace',
        PYTHONDONTWRITEBYTECODE='1',
        GIT_CEILING_DIRECTORIES=str(snapshot.parent), CONDA_PREFIX=str(prefix),
        CONDA_DEFAULT_ENV='base' if prefix.name.lower() == 'miniforge3' else prefix.name,
        QUANT_PROJECT_ROOT=str(snapshot), QUANT_DATA_ROOT=str(snapshot/'data'),
        QUANT_ARTIFACTS_ROOT=str(snapshot/'artifacts'),
        QUANT_REGISTRY_ROOT=str(snapshot/'artifacts/registry/experiments.parquet'),
        QUANT_TEST_RUN_DIR=str(output))
    env.update({name: '1' for name in THREAD_VARIABLES})
    return env


def _stop_owned(process: subprocess.Popen, output: Path, log) -> None:
    if process.poll() is not None:
        return
    (output/'stopping').touch()
    if sys.platform == 'win32':
        completed = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
            stdout=log, stderr=subprocess.STDOUT, check=False, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if completed.returncode and process.poll() is None:
            raise RuntimeError('Could not stop owned fast-test process tree')
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=30)


def _execute(command: list[str], snapshot: Path, output: Path, env: dict,
             log, start: float) -> int:
    _remaining(start)
    options = ({'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32'
               else {'start_new_session': True})
    process = subprocess.Popen(command, cwd=snapshot, env=env, stdout=log,
                               stderr=subprocess.STDOUT, **options)
    try:
        _json(output/'running.json', dict(pid=process.pid, command=command,
              started_at=dt.datetime.now(dt.timezone.utc).isoformat()))
        return process.wait(timeout=_remaining(start))
    except BaseException:
        _stop_owned(process, output, log)
        raise


def _assertion_control(snapshot: Path, output: Path, env: dict, log, start: float) -> None:
    control = snapshot/'_quant_assertion_control.py'
    control.write_text("def test_assertions_active():\n    assert False, 'intentional assertion control'\n",
                       encoding='utf-8')
    command = [sys.executable, '-m', 'pytest', str(control), '-q', '--assert=plain',
               '-c', str(snapshot/'pyproject.toml'),
               '-o', 'addopts=', '--junitxml', str(output/'assertion_control.xml'),
               '--basetemp', str(output/'control_tmp')]
    code = _execute(command, snapshot, output, env, log, start)
    cases = list(ET.parse(output/'assertion_control.xml').iter('testcase'))
    if (code != 1 or len(cases) != 1 or cases[0].get('classname') != control.stem
            or cases[0].get('name') != 'test_assertions_active' or cases[0].find('failure') is None
            or 'intentional assertion control' not in ET.tostring(cases[0], encoding='unicode')):
        raise ValueError('Assertion control did not produce its one intentional failure')
    _json(output/'assertion_control.json', dict(expected_failure_verified=True, exit_code=code))


def _evidence(output: Path, snapshot: Path, workers: int) -> dict:
    from _pytest.junitxml import mangle_test_address

    collection = json.loads((output/'collection.json').read_text(encoding='utf-8'))
    nodes = collection['nodeids']
    if not nodes or len(nodes) != len(set(nodes)):
        raise ValueError('Missing or duplicate selected test identities')
    digest = hashlib.sha256(json.dumps(nodes, ensure_ascii=True).encode()).hexdigest()
    records = [json.loads(path.read_text(encoding='utf-8')) for path in output.glob('worker_gw*.json')]
    if (len(records) != workers
            or {record['worker'] for record in records} != {f'gw{i}' for i in range(workers)}):
        raise ValueError('Missing worker collection evidence')
    for record in records:
        if (record['count'] != len(nodes) or record['selection_sha256'] != digest
                or record['optimize'] != 0 or record['assertion_mode'] != 'plain'
                or record['python'] != sys.executable
                or record['prefix'] != str(Path(sys.prefix).resolve())):
            raise ValueError('Worker selection, runtime or assertion evidence differs')
        if (not all(record['module_paths'].get(name) for name in ('quant', 'quant.reporting.fast_tests'))
                or any(not Path(value).is_relative_to(snapshot)
                       for value in record['module_paths'].values() if value)):
            raise ValueError('Worker imported project code outside its source snapshot')
    def identity(node):
        names = mangle_test_address(node)
        return ('.'.join(names[:-1]), names[-1])
    cases = list(ET.parse(output/'tests.xml').iter('testcase'))
    if Counter((case.get('classname'), case.get('name')) for case in cases) != Counter(map(identity, nodes)):
        raise ValueError('JUnit does not contain every selected test exactly once')
    errors = sum(case.find('error') is not None for case in cases)
    failed = sum(case.find('failure') is not None for case in cases)
    skipped = sum(case.find('skipped') is not None for case in cases)
    passed = sum(all(case.find(tag) is None for tag in ('failure', 'error', 'skipped')) for case in cases)
    return dict(complete=True, selected_count=len(nodes), passed=passed,
                failed=failed, errors=errors, skipped=skipped, selection_sha256=digest)


def run(root: Path) -> int:
    """The official budget is always 600s, including copying and assertion control."""
    root = root.resolve()
    started, clock = dt.datetime.now(ZoneInfo('Asia/Shanghai')), time.monotonic()
    output = root/'artifacts/tests'/started.strftime('%Y%m%dT%H%M%S_%f')
    output.mkdir(parents=True, exist_ok=False)
    snapshot, log_path = output/'snapshot', output/'pytest.log'
    snapshot.mkdir()
    workers = min(12, os.cpu_count() or 1)
    payload = dict(ran_at=started.isoformat(), command='pytest -m "not slow"',
        timeout_seconds=TIMEOUT_SECONDS, workers=workers, complete=False, accepted_fast=False,
        passed=None, failed=None, errors=None, skipped=None, selected_count=None,
        log=str(log_path), snapshot=str(snapshot), junit=str(output/'tests.xml'))
    code = 2
    with log_path.open('wb') as log:
        try:
            if not _xdist_available():
                raise RuntimeError('pytest-xdist is required; install the project dev dependencies')
            manifest = _snapshot(root, snapshot, clock)
            _json(output/'source_manifest.json', manifest)
            env = _environment(snapshot, output)
            _assertion_control(snapshot, output, env, log, clock)
            command = [sys.executable, '-m', 'pytest', 'tests', '-q', '-m', 'not slow',
                '-c', str(snapshot/'pyproject.toml'),
                '-o', 'addopts=', '--assert=plain', '-n', str(workers), '--dist=worksteal',
                '--max-worker-restart=0', '-p', 'quant.reporting.fast_tests', '--tb=short',
                '--basetemp', str(output/'pytest_tmp'), '--junitxml', str(output/'tests.xml')]
            payload['argv'] = command
            code = _execute(command, snapshot, output, env, log, clock)
            try:
                payload.update(_evidence(output, snapshot, workers))
                if code == 0 and (payload['failed'] or payload['errors']):
                    code = 2
                    payload['evidence_error'] = 'Zero child exit contradicts JUnit failures'
            except (OSError, ValueError, TypeError, KeyError, ET.ParseError) as exc:
                payload['evidence_error'] = str(exc)
                if code == 0:
                    code = 2
        except subprocess.TimeoutExpired:
            code = 124
            log.write(f'\ntimeout after {TIMEOUT_SECONDS}s\n'.encode())
        except Exception as exc:
            code = 2
            payload['error'] = str(exc)
            log.write(('\n'+traceback.format_exc()).encode('utf-8', errors='replace'))
            if isinstance(exc, subprocess.CalledProcessError) and exc.output:
                detail = exc.output
                log.write(detail if isinstance(detail, bytes) else detail.encode('utf-8', errors='replace'))
    elapsed = round(time.monotonic()-clock, 2)
    if code == 0 and elapsed > TIMEOUT_SECONDS:
        code = 124
    payload.update(exit_code=code, duration_seconds=elapsed)
    payload['accepted_fast'] = bool(payload['complete'] and code == 0
        and payload['failed'] == 0 and payload['errors'] == 0
        and payload['duration_seconds'] <= TIMEOUT_SECONDS)
    _json(output/'receipt.json', payload)
    _json(output.parent/'latest.json', payload)
    return code


# Loaded only by the child pytest command, from the copied source tree.
_worker = None


def pytest_runtest_logreport(report):
    # Persist failures immediately: a later timeout may prevent final JUnit.
    if _worker is None or not report.failed:
        return
    identity = hashlib.sha256((report.nodeid+'\0'+report.when).encode()).hexdigest()[:16]
    _json(Path(os.environ['QUANT_TEST_RUN_DIR'])/f'failure_{_worker}_{identity}.json',
          dict(nodeid=report.nodeid, phase=report.when, traceback=report.longreprtext))


def pytest_configure(config):
    global _worker
    _worker = getattr(config, 'workerinput', {}).get('workerid')
    if sys.flags.optimize != 0:
        raise RuntimeError('Python optimization disables test assertions')


def pytest_collection_finish(session):
    if _worker is None:
        return
    output = Path(os.environ['QUANT_TEST_RUN_DIR'])
    nodes = [item.nodeid for item in session.items]
    paths = {name: getattr(module, '__file__', None) for name, module in sys.modules.items()
             if name in {'quant', 'quant.reporting.fast_tests', 'tests.full_chain_cases'}
             or (name.startswith('tests.') and name.endswith('.conftest'))}
    record = dict(worker=_worker, count=len(nodes), python=sys.executable,
        prefix=str(Path(sys.prefix).resolve()), dont_write_bytecode=sys.dont_write_bytecode,
        optimize=sys.flags.optimize, assertion_mode=getattr(session.config.option, 'assertmode', None),
        selection_sha256=hashlib.sha256(json.dumps(nodes, ensure_ascii=True).encode()).hexdigest(),
        module_paths=paths)
    _json(output/f'worker_{_worker}.json', record)
    if _worker == 'gw0':
        _json(output/'collection.json', dict(nodeids=nodes))
