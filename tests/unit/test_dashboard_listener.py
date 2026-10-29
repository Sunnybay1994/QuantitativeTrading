"""Exercise launcher checks without starting a service or touching production logs."""

from pathlib import Path
import socket
import subprocess
import sys
import uuid

import pytest


def _check(tmp_path, port):
    scripts = tmp_path/'scripts'
    scripts.mkdir()
    script = scripts/'run_research_dashboard.ps1'
    source = Path('scripts/run_research_dashboard.ps1').read_text(encoding='utf-8')
    source = source.replace('Local\\QuantitativeTrading-ResearchDashboard',
                            'Local\\Dashboard-Test-'+uuid.uuid4().hex)
    script.write_text(source, encoding='ascii')
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-File',
                             str(script), '-CheckOnly', '-Port', str(port)],
                            capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=30)
    assert not (tmp_path/'artifacts').exists()
    return result


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows launcher')
def test_check_only_reports_existing_listener_without_starting_duplicate(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = _check(tmp_path, port)
    assert result.returncode == 0
    assert f'Port {port} is already occupied' in result.stdout
    assert 'Ready to start' not in result.stdout


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows exclusive socket binding')
def test_check_only_rejects_bound_nonlistening_port(tmp_path):
    # Reproduces the proxy collision: connect fails, but the port is not free.
    with socket.socket() as reserved:
        reserved.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        reserved.bind(('127.0.0.1', 0))
        result = _check(tmp_path, reserved.getsockname()[1])
    assert result.returncode != 0
    assert 'Ready to start' not in result.stdout
    assert result.stderr


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows launcher')
def test_check_only_releases_free_port_and_does_not_start_service(tmp_path):
    with socket.socket() as temporary:
        temporary.bind(('127.0.0.1', 0))
        port = temporary.getsockname()[1]
    result = _check(tmp_path, port)
    assert result.returncode == 0
    assert f'Ready to start local dashboard on port {port}' in result.stdout
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
