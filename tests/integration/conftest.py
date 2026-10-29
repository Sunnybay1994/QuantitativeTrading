"""Full M3 chain regressions are retained outside the daily ten-minute suite."""

from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: full M3 integration chains; run separately")


def pytest_collection_modifyitems(items):
    integration = Path(__file__).parent.resolve()
    for item in items:
        path = Path(item.path).resolve()
        if path.parent == integration and path.name.startswith("test_m3_"):
            item.add_marker(pytest.mark.slow)
