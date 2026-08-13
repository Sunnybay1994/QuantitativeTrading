"""G9A fixed quality command and immutable evidence boundary."""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

import pytest

from quant.research.m3.config import LoadedM3Config, load_m3_config
from quant.research.m3.quality_gate import (
    CommandExecution,
    M3QualityGateError,
    _SubprocessExecutor,
    _commands,
    _quality_environment,
    run_quality_gate,
    verify_quality_artifact,
)

_CONFIG = PurePosixPath("configs/research/m3_qlib_example.toml")


class _Executor:
    def __init__(self, *, fail_at: int | None = None, drift: bool = False) -> None:
        self.fail_at = fail_at
        self.drift = drift
        self.calls: list[tuple[str, ...]] = []

    def run(
        self, *, argv: tuple[str, ...], cwd: Path, env: Mapping[str, str]
    ) -> CommandExecution:
        assert env["PYTHONHASHSEED"] == "0"
        self.calls.append(argv)
        if self.drift and len(self.calls) == 4:
            target = cwd / "src/quant/__init__.py"
            target.write_bytes(target.read_bytes() + b"\n")
        code = 1 if self.fail_at == len(self.calls) else 0
        return CommandExecution(
            code,
            f"cwd={cwd}\npython={Path(sys.executable).resolve()}\n".encode(),
            b"",
        )


def _project(tmp_path: Path) -> tuple[Path, LoadedM3Config]:
    source = Path(__file__).resolve().parents[2]
    project = tmp_path / "project"
    shutil.copytree(
        source / "src/quant",
        project / "src/quant",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    config_path = project.joinpath(*_CONFIG.parts)
    config_path.parent.mkdir(parents=True)
    shutil.copy2(source.joinpath(*_CONFIG.parts), config_path)
    shutil.copy2(source / "pyproject.toml", project / "pyproject.toml")
    (project / "artifacts/research/m3").mkdir(parents=True)
    return project, load_m3_config(config_path)


def test_quality_gate_uses_fixed_commands_publishes_and_resumes(tmp_path: Path) -> None:
    project, config = _project(tmp_path)
    executor = _Executor()

    first = run_quality_gate(
        project_root=project,
        config=config,
        config_relative=_CONFIG,
        executor=executor,
    )
    expected = tuple((sys.executable, *item.actual_tail) for item in _commands(project))
    assert tuple(executor.calls) == expected
    assert tuple(item.name for item in first.report.checks) == (
        "pytest",
        "ruff",
        "mypy",
        "import_isolation",
    )
    assert len(first.receipt.outputs) == 5
    assert len(first.receipt.inputs) > 3

    report_path = project / "artifacts/research/m3/acceptance/quality"
    roots = tuple(report_path.iterdir())
    assert len(roots) == 1
    for name in ("pytest.log", "ruff.log", "mypy.log", "import_isolation.json"):
        value = json.loads((roots[0] / name).read_text(encoding="utf-8"))
        assert "<WORKSPACE>" in value["stdout"]
        assert "<PYTHON>" in value["stdout"]
        assert str(project) not in value["stdout"]

    resumed_executor = _Executor(fail_at=1)
    second = run_quality_gate(
        project_root=project,
        config=config,
        config_relative=_CONFIG,
        executor=resumed_executor,
    )
    assert resumed_executor.calls == []
    assert second == first
    verified = verify_quality_artifact(
        root=roots[0],
        receipt_path=project
        / f"artifacts/research/m3/receipts/quality/{first.report.quality_key}.json",
        project_root=project,
        config=config,
        config_relative=_CONFIG,
        artifact_roots={"PROJECT": project},
    )
    assert verified == first


@pytest.mark.parametrize("mode", ["nonzero", "drift"])
def test_quality_gate_failure_publishes_no_artifact(
    tmp_path: Path, mode: str
) -> None:
    project, config = _project(tmp_path)
    executor = _Executor(fail_at=2 if mode == "nonzero" else None, drift=mode == "drift")

    with pytest.raises(M3QualityGateError) as caught:
        run_quality_gate(
            project_root=project,
            config=config,
            config_relative=_CONFIG,
            executor=executor,
        )

    assert str(caught.value) == "M3_QUALITY_ARTIFACT_INVALID"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert not list((project / "artifacts/research/m3").rglob("quality_report.json"))


def test_import_isolation_fixed_command_runs_in_fresh_process() -> None:
    project = Path(__file__).resolve().parents[2]
    command = _commands(project)[3]
    execution = _SubprocessExecutor().run(
        argv=(sys.executable, *command.actual_tail),
        cwd=project,
        env=_quality_environment(),
    )
    assert execution.exit_code == 0, execution.stderr.decode("utf-8", "replace")
    assert json.loads(execution.stdout)["passed"] is True
