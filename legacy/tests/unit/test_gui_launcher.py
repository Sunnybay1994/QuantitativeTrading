import importlib.machinery
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant.gui import launcher


def test_missing_streamlit_returns_stable_nonzero_without_starting_process(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(launcher.importlib.util, "find_spec", lambda _name: None)
    called = False

    def _unexpected_run(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(launcher.subprocess, "run", _unexpected_run)

    assert launcher.main([]) == 2
    assert not called
    assert "Streamlit" in capsys.readouterr().err


def test_launcher_uses_fixed_app_and_passes_artifact_root_via_child_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        launcher.importlib.util,
        "find_spec",
        lambda _name: importlib.machinery.ModuleSpec("streamlit", loader=None),
    )
    captured: dict[str, object] = {}

    def _record_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(launcher.subprocess, "run", _record_run)

    result = launcher.main(
        [
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--port",
            "8765",
            "--no-headless",
        ]
    )

    assert result == 7
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:4] == [launcher.sys.executable, "-m", "streamlit", "run"]
    assert command[4].endswith("quant\\gui\\app.py") or command[4].endswith("quant/gui/app.py")
    assert "--server.address=127.0.0.1" in command
    assert "--server.port=8765" in command
    assert "--server.headless=false" in command
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert environment[launcher.ARTIFACT_ROOT_ENV] == str((tmp_path / "artifacts").absolute())
    assert captured["check"] is False


def test_launcher_rejects_non_loopback_address() -> None:
    with pytest.raises(SystemExit):
        launcher.parse_args(["--address", "0.0.0.0"])


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_launcher_rejects_invalid_port(port: str) -> None:
    with pytest.raises(SystemExit):
        launcher.parse_args(["--port", port])
