"""Explicit fixtures for tests that must never consume production settings."""

import datetime as dt

import pytest


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
