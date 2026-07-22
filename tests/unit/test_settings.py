from pathlib import Path

import pytest

from quant.settings import load_tushare_settings


def test_loads_token_without_exposing_it_in_repr(tmp_path: Path) -> None:
    path = tmp_path / "tushare.local.toml"
    path.write_text('[tushare]\ntoken = "secret-value"\n', encoding="utf-8")
    settings = load_tushare_settings(path)
    assert settings.token == "secret-value"
    assert "secret-value" not in repr(settings)


def test_rejects_empty_token(tmp_path: Path) -> None:
    path = tmp_path / "tushare.local.toml"
    path.write_text('[tushare]\ntoken = ""\n', encoding="utf-8")
    with pytest.raises(ValueError, match="尚未填写"):
        load_tushare_settings(path)
