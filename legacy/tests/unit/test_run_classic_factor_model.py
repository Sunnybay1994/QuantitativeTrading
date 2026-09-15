from __future__ import annotations

import tomllib
from copy import deepcopy
from pathlib import Path

import pytest

from quant.research.run_classic_factor_model import _validate_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT_ROOT / "configs/research/m2_classic_factor_lightgbm.toml"


def test_lightgbm_config_freezes_features_cpu_and_validation_selection() -> None:
    with CONFIG.open("rb") as stream:
        config = tomllib.load(stream)

    _validate_config(config, threads=2)

    changed = deepcopy(config)
    changed["features"]["names"].reverse()
    with pytest.raises(ValueError, match="invalid classic-factor LightGBM config"):
        _validate_config(changed, threads=2)

    changed = deepcopy(config)
    changed["model"]["lightgbm"]["device_type"] = "gpu"
    with pytest.raises(ValueError, match="invalid classic-factor LightGBM config"):
        _validate_config(changed, threads=2)

    with pytest.raises(ValueError, match="invalid classic-factor LightGBM config"):
        _validate_config(config, threads=5)
