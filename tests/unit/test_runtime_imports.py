from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from quant import _is_quant_entrypoint


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_quant_help(import_root: Path, *, pytest_marker: bool) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["QUANT_RUNTIME_IMPORTS_ROOT"] = str(import_root)
    if pytest_marker:
        env["PYTEST_CURRENT_TEST"] = "test_runtime_imports (isolated child)"
    else:
        env.pop("PYTEST_CURRENT_TEST", None)
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(PROJECT_ROOT / "src"), env.get("PYTHONPATH")])
    )
    return subprocess.run(
        [sys.executable, "-m", "quant", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _shanghai_date() -> str:
    shanghai = timezone(timedelta(hours=8), name="Asia/Shanghai")
    return datetime.now(shanghai).date().isoformat()


def test_detects_quant_module_entrypoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["python", "--help"])
    monkeypatch.setattr(sys, "orig_argv", ["python", "-X", "dev", "-m", "quant.research.sample"])
    assert _is_quant_entrypoint()

    monkeypatch.setattr(sys, "orig_argv", ["python", "-m", "quant"])
    assert _is_quant_entrypoint()

    monkeypatch.setattr(sys, "orig_argv", ["python", "-m", "quantum"])
    assert not _is_quant_entrypoint()

    monkeypatch.setattr(sys, "orig_argv", ["python", "-c", "import quant"])
    assert not _is_quant_entrypoint()

    monkeypatch.setattr(sys, "orig_argv", ["python", r"C:\\Scripts\\quant.exe"])
    monkeypatch.setattr(sys, "argv", [r"C:\\Scripts\\quant.exe"])
    assert _is_quant_entrypoint()


def test_cli_exit_appends_only_imported_module_names() -> None:
    with TemporaryDirectory(prefix=".runtime_imports_test_", dir=PROJECT_ROOT / "tests") as tmp:
        import_root = Path(tmp) / "runtime_imports"
        date_before = _shanghai_date()
        result = _run_quant_help(import_root, pytest_marker=True)

        assert result.returncode == 0, result.stderr
        output_paths = list(import_root.glob("????-??-??.txt"))
        assert len(output_paths) == 1
        output_path = output_paths[0]
        assert output_path.stem in {date_before, _shanghai_date()}
        lines = output_path.read_text(encoding="utf-8").splitlines()
        assert lines
        assert all(line.startswith("quant.") for line in lines)
        assert {"quant.cli", "quant.core.runtime_imports"}.issubset(lines)
        assert "quant.__main__" not in lines
        assert "--help" not in lines
        assert all("=" not in line and " " not in line for line in lines)


def test_cli_exit_survives_logging_failure() -> None:
    with TemporaryDirectory(prefix=".runtime_imports_test_", dir=PROJECT_ROOT / "tests") as tmp:
        blocked_root = Path(tmp) / "not_a_directory"
        blocked_root.write_text("test sentinel", encoding="utf-8")
        result = _run_quant_help(blocked_root, pytest_marker=True)

        assert result.returncode == 0
        assert result.stderr == ""


def test_cli_exit_does_not_wait_for_an_occupied_log_lock() -> None:
    with TemporaryDirectory(prefix=".runtime_imports_test_", dir=PROJECT_ROOT / "tests") as tmp:
        import_root = Path(tmp) / "runtime_imports"
        import_root.mkdir()
        lock_path = import_root / ".runtime_imports.lock"
        ready_path = Path(tmp) / "lock_ready"
        env = os.environ.copy()
        env["QUANT_RUNTIME_IMPORTS_ROOT"] = str(import_root)
        env["PYTHONPATH"] = os.pathsep.join(
            filter(None, [str(PROJECT_ROOT / "src"), env.get("PYTHONPATH")])
        )
        holder_code = (
            "import pathlib, sys, time\n"
            "from quant.core.runtime_imports import _cross_process_lock\n"
            "lock_path, ready_path = map(pathlib.Path, sys.argv[1:])\n"
            "with _cross_process_lock(lock_path):\n"
            "    ready_path.write_text('ready', encoding='utf-8')\n"
            "    time.sleep(10)\n"
        )
        holder = subprocess.Popen(
            [sys.executable, "-c", holder_code, str(lock_path), str(ready_path)],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            ready_deadline = time.monotonic() + 10
            while not ready_path.exists():
                if holder.poll() is not None:
                    _, stderr = holder.communicate()
                    raise AssertionError(f"lock holder exited early: {stderr}")
                if time.monotonic() >= ready_deadline:
                    raise AssertionError("lock holder did not acquire the log lock")
                time.sleep(0.01)

            started_at = time.monotonic()
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from quant.core.runtime_imports import register_runtime_import_logger; "
                    "register_runtime_import_logger()",
                ],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            elapsed = time.monotonic() - started_at

            assert result.returncode == 0, result.stderr
            assert result.stderr == ""
            assert elapsed < 1.5
            assert holder.poll() is None
            assert not list(import_root.glob("????-??-??.txt"))
        finally:
            if holder.poll() is None:
                holder.terminate()
            holder.communicate(timeout=5)


def test_pytest_child_without_explicit_root_does_not_write() -> None:
    with TemporaryDirectory(prefix=".runtime_imports_test_", dir=PROJECT_ROOT / "tests") as tmp:
        artifacts_root = Path(tmp) / "isolated_artifacts"
        env = os.environ.copy()
        env["QUANT_ARTIFACTS_ROOT"] = str(artifacts_root)
        env.pop("QUANT_RUNTIME_IMPORTS_ROOT", None)
        env["PYTEST_CURRENT_TEST"] = "test_pytest_child_without_explicit_root_does_not_write"
        env["PYTHONPATH"] = os.pathsep.join(
            filter(None, [str(PROJECT_ROOT / "src"), env.get("PYTHONPATH")])
        )

        result = subprocess.run(
            [sys.executable, "-m", "quant", "--help"],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert not (artifacts_root / "runtime_imports").exists()


def test_ordinary_import_does_not_register_logger() -> None:
    with TemporaryDirectory(prefix=".runtime_imports_test_", dir=PROJECT_ROOT / "tests") as tmp:
        import_root = Path(tmp) / "runtime_imports"
        env = os.environ.copy()
        env["QUANT_RUNTIME_IMPORTS_ROOT"] = str(import_root)
        env.pop("PYTEST_CURRENT_TEST", None)
        env["PYTHONPATH"] = os.pathsep.join(
            filter(None, [str(PROJECT_ROOT / "src"), env.get("PYTHONPATH")])
        )
        result = subprocess.run(
            [sys.executable, "-c", "import quant; import quant.cli"],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert not import_root.exists()
