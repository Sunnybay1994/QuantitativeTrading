"""Explicit fixtures for tests that must never consume production settings."""

import datetime as dt
from pathlib import Path

import pytest

from tests.full_chain_cases import FULL_CHAIN_CASES


def pytest_configure(config):
    config.addinivalue_line('markers', 'slow: file-backed complete-chain regressions; run separately')


def pytest_collection_modifyitems(items):
    unit = Path(__file__).parent.resolve()
    canonical = {}
    for item in items:
        path = Path(item.path)
        cases = FULL_CHAIN_CASES.get(path.name, ())
        if not cases:
            continue
        if path not in canonical:
            canonical[path] = path.resolve()
        name = getattr(item, 'originalname', None) or item.name.split('[', 1)[0]
        if canonical[path].parent == unit and name in cases:
            item.add_marker(pytest.mark.slow)


@pytest.fixture
def diagnosis_config(tmp_path):
    """Synthetic prices and a current date for fake-client tests, not a live price check."""
    path = tmp_path / "diagnosis_fixture.toml"
    path.write_text(
        'model="deepseek-flash"\nmodel_epoch="fake-client-test"\n'
        f'pricing_checked={dt.date.today().isoformat()}\n'
        'input_usd_per_million=0.30\noutput_usd_per_million=1.20\n'
        'max_tokens=2048\nmax_input_bytes=60000\nmax_attempts=2\n',
        encoding="utf-8",
    )
    return path
