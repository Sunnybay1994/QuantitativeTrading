from pathlib import Path

import pytest

from quant.settings import load_tushare_settings, resolve_data_root


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


def test_resolves_shared_data_root_outside_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "worktree"
    shared = tmp_path / "shared" / "data"
    project.mkdir()
    shared.mkdir(parents=True)
    monkeypatch.setenv("QUANT_DATA_ROOT", str(shared))

    assert resolve_data_root(base=project) == shared.resolve()


def test_explicit_data_root_wins_over_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "worktree"
    environment = tmp_path / "environment"
    explicit = tmp_path / "explicit"
    for path in (project, environment, explicit):
        path.mkdir()
    monkeypatch.setenv("QUANT_DATA_ROOT", str(environment))

    assert resolve_data_root(explicit, base=project) == explicit.resolve()
