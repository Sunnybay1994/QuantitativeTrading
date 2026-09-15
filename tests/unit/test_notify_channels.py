import json

from quant.core.paths import project_paths
from quant.notify import send


def test_notify_without_channels_writes_outbox(monkeypatch, tmp_path):
    (tmp_path / "src" / "quant").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='quant'\n")
    monkeypatch.setenv("QUANT_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_ARTIFACTS_ROOT", str(tmp_path / "artifacts"))
    project_paths.cache_clear()
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "notify.toml").write_text("[notify]\nenabled=true\nchannels=[]\n")
    results = send("hello", "world", config_path=tmp_path / "configs" / "notify.toml")
    assert results[0].channel == "outbox" and results[0].ok
    lines = (tmp_path / "artifacts" / "notify" / "outbox.jsonl").read_text(encoding="utf-8").strip()
    payload = json.loads(lines)
    assert payload["title"] == "hello"
    project_paths.cache_clear()


def test_wecom_https_only(monkeypatch, tmp_path):
    (tmp_path / "src" / "quant").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='quant'\n")
    monkeypatch.setenv("QUANT_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_ARTIFACTS_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("WECOM_WEBHOOK", "http://example.invalid/hook")
    project_paths.cache_clear()
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "notify.toml").write_text(
        '[notify]\nenabled=true\nchannels=["wecom"]\n'
    )
    results = send("t", "b", config_path=tmp_path / "configs" / "notify.toml")
    assert any(item.channel == "wecom" and not item.ok for item in results)
    project_paths.cache_clear()
