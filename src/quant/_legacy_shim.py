"""Load implementation files that live under legacy/quant/."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[2]
_LEGACY = _ROOT / "legacy" / "quant"


def bind(name: str, destination: dict) -> ModuleType:
    """Execute legacy/quant/<suffix>.py and copy its public attrs into destination."""
    relative = Path(*name.split(".")[1:]).with_suffix(".py")
    path = _LEGACY / relative
    if not path.is_file():
        raise ImportError(f"legacy shim missing: {path}")
    # Load under a private alias so the public name can stay the thin shim module.
    alias = name + ".__legacy_impl"
    if alias in sys.modules:
        module = sys.modules[alias]
    else:
        spec = importlib.util.spec_from_file_location(alias, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load legacy shim: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        spec.loader.exec_module(module)
    for key, value in vars(module).items():
        if key.startswith("__") and key not in {"__all__", "__doc__"}:
            continue
        destination[key] = value
    return module
