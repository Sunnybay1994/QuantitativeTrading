"""Full integration chains are retained outside the daily ten-minute suite."""

import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path(tmp_path, request):
    """Preserve the formal bootstrap's real filesystem topology in the isolated runner."""
    run_dir = os.environ.get('QUANT_TEST_RUN_DIR')
    if request.node.path.name != 'test_paper_formal_bootstrap.py' or not run_dir:
        return tmp_path
    from quant.execution import paper_runtime

    output = Path(run_dir).resolve()
    if (output/'snapshot').resolve() != paper_runtime._actual_project_root().resolve():
        return tmp_path
    target = output/'formal_bootstrap_tmp'/tmp_path.parent.name/tmp_path.name
    if target.exists() or not target.resolve().is_relative_to(output):
        raise ValueError('Formal bootstrap scratch directory must be new and within this run')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    return target


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: file-backed complete-chain regressions; run separately")


def pytest_collection_modifyitems(items):
    integration = Path(__file__).parent.resolve()
    canonical = {}
    for item in items:
        path = Path(item.path)
        if not (path.name.startswith('test_m3_') or path.name == 'test_paper_formal_bootstrap.py'):
            continue
        if path not in canonical:
            canonical[path] = path.resolve()
        path = canonical[path]
        if path.parent == integration and path.name.startswith("test_m3_"):
            item.add_marker(pytest.mark.slow)
        if path.parent == integration and path.name == 'test_paper_formal_bootstrap.py':
            name = getattr(item, 'originalname', None) or item.name.split('[', 1)[0]
            if name in {
                'test_public_fresh_bootstrap_reopen_and_identity_closure',
                'test_public_partial_root_and_closing_state_reject_reopen',
                'test_public_closed_barrier_rejects_reopen_with_zero_initializer',
                'test_config_bytes_are_not_crlf_normalized',
            }:
                item.add_marker(pytest.mark.slow)
