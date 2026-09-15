"""Narrow CLI for the production successor bridge.

Accepts only ``--request <absolute-path>``.  No env, wall-clock, retained-state,
directory discovery, research logic, Gate logic, or runtime business logic.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from quant.research.m3.successor_bridge import (
    BRIDGE_INPUT_ERROR,
    BRIDGE_RUNTIME_ERROR,
    SuccessorBridgeError,
    project_successor_bridge_result,
    run_production_successor_bridge,
    successor_bridge_result_json_bytes,
)

EXIT_SUCCESS = 0
EXIT_INPUT = 2
EXIT_RUNTIME = 3


class _UsageError(Exception):
    """Internal CLI usage failure; never carries path or argparse text."""


class _QuietParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise _UsageError from None


def main(argv: Sequence[str] | None = None) -> int:
    """Parse argv, invoke the bridge, emit one canonical JSON line or a code."""

    parser = _QuietParser(
        prog="run_successor",
        description="Run the package-owned production two-fold successor bridge.",
    )
    parser.add_argument(
        "--request",
        type=Path,
        required=True,
        help="Exact concrete absolute path to an m3-successor-bridge-request-v1 JSON file.",
    )

    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except _UsageError:
        sys.stderr.write(f"{BRIDGE_INPUT_ERROR}\n")
        return EXIT_INPUT
    except SystemExit as error:
        # ``--help`` prints help then exits 0; do not touch request IO.
        code = error.code
        if code in (0, None):
            return EXIT_SUCCESS
        sys.stderr.write(f"{BRIDGE_INPUT_ERROR}\n")
        return EXIT_INPUT

    request_path = args.request
    if type(request_path) is not type(Path()):
        sys.stderr.write(f"{BRIDGE_INPUT_ERROR}\n")
        return EXIT_INPUT

    try:
        result = run_production_successor_bridge(request_path=request_path)
        projection = project_successor_bridge_result(result)
        sys.stdout.write(successor_bridge_result_json_bytes(projection).decode("ascii"))
        sys.stdout.write("\n")
        return EXIT_SUCCESS
    except SuccessorBridgeError as error:
        sys.stderr.write(f"{error.code}\n")
        if error.code == BRIDGE_INPUT_ERROR:
            return EXIT_INPUT
        if error.code == BRIDGE_RUNTIME_ERROR:
            return EXIT_RUNTIME
        return EXIT_INPUT
    except Exception:
        sys.stderr.write(f"{BRIDGE_RUNTIME_ERROR}\n")
        return EXIT_RUNTIME


if __name__ == "__main__":
    raise SystemExit(main())
