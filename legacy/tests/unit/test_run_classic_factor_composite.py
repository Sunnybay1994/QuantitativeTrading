from __future__ import annotations

import tomllib
from copy import deepcopy
from pathlib import Path

import pytest

from quant.research.run_classic_factor_composite import _validate_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT_ROOT / "configs/research/m2_classic_factor_composite.toml"
MARKET_RISK_CONFIG = (
    PROJECT_ROOT / "configs/research/m2_classic_factor_composite_market_risk.toml"
)


def test_composite_config_freezes_components_and_risk_control() -> None:
    with CONFIG.open("rb") as stream:
        config = tomllib.load(stream)

    _validate_config(config, threads=2)

    changed = deepcopy(config)
    changed["risk_control"]["annualized_volatility"] = 0.13
    with pytest.raises(ValueError, match="invalid classic-factor composite config"):
        _validate_config(changed, threads=2)


def test_market_risk_config_freezes_benchmark_and_zero_cash_gate() -> None:
    with MARKET_RISK_CONFIG.open("rb") as stream:
        config = tomllib.load(stream)

    _validate_config(config, threads=2)

    changed = deepcopy(config)
    changed["risk_control"]["benchmark"] = "510500.SH"
    with pytest.raises(ValueError, match="invalid classic-factor composite config"):
        _validate_config(changed, threads=2)

    changed = deepcopy(config)
    changed["risk_control"]["require_zero_cash_period_fraction"] = False
    with pytest.raises(ValueError, match="invalid classic-factor composite config"):
        _validate_config(changed, threads=2)

    changed = deepcopy(config)
    changed["factors"]["names"].reverse()
    with pytest.raises(ValueError, match="invalid classic-factor composite config"):
        _validate_config(changed, threads=2)
