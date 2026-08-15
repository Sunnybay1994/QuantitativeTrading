"""Local-only launcher for the optional Streamlit research workbench."""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

ARTIFACT_ROOT_ENV = "QUANT_GUI_ARTIFACT_ROOT"
_LOOPBACK_ADDRESSES = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class GuiLaunchConfig:
    artifact_root: Path
    address: str
    port: int
    headless: bool


def parse_args(argv: Sequence[str] | None = None) -> GuiLaunchConfig:
    """Parse and validate the intentionally narrow local launcher surface."""
    parser = argparse.ArgumentParser(description="Launch the read-only Quant research workbench.")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path.cwd() / "artifacts",
        help="Trusted artifact root containing research/runs.",
    )
    parser.add_argument(
        "--address",
        type=_loopback_address,
        default="127.0.0.1",
        help="Loopback address only (default: 127.0.0.1).",
    )
    parser.add_argument("--port", type=_port, default=8501)
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run without opening a browser automatically (default: true).",
    )
    args = parser.parse_args(argv)
    return GuiLaunchConfig(
        artifact_root=args.artifact_root.absolute(),
        address=args.address,
        port=args.port,
        headless=args.headless,
    )


def build_streamlit_command(config: GuiLaunchConfig) -> list[str]:
    """Build a fixed-module Streamlit command without shell interpolation."""
    app_path = Path(__file__).with_name("app.py").absolute()
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        f"--server.address={config.address}",
        f"--server.port={config.port}",
        f"--server.headless={str(config.headless).lower()}",
        "--browser.gatherUsageStats=false",
        "--server.fileWatcherType=none",
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Launch Streamlit or fail clearly when the optional dependency is absent."""
    config = parse_args(argv)
    if importlib.util.find_spec("streamlit") is None:
        print(
            "Streamlit is not installed. The project GUI optional dependency is still "
            "governed by the shared pyproject.toml lock; install the approved [gui] group "
            "after that lock is released.",
            file=sys.stderr,
        )
        return 2
    child_environment = os.environ.copy()
    child_environment[ARTIFACT_ROOT_ENV] = str(config.artifact_root)
    result = subprocess.run(
        build_streamlit_command(config),
        env=child_environment,
        check=False,
    )
    return result.returncode


def _loopback_address(value: str) -> str:
    if value not in _LOOPBACK_ADDRESSES:
        raise argparse.ArgumentTypeError("address must be a loopback address")
    return value


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


__all__ = [
    "ARTIFACT_ROOT_ENV",
    "GuiLaunchConfig",
    "build_streamlit_command",
    "main",
    "parse_args",
]
