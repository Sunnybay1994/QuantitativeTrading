"""Load implementation files that live under legacy/quant/."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[2]
_LEGACY = _ROOT / "legacy" / "quant"


def _rebind_function(fn: types.FunctionType, globals_dict: dict, module_name: str) -> types.FunctionType:
    """Point a legacy function at the public shim globals so monkeypatches resolve."""
    rebound = types.FunctionType(
        fn.__code__,
        globals_dict,
        fn.__name__,
        fn.__defaults__,
        fn.__closure__,
    )
    rebound.__kwdefaults__ = fn.__kwdefaults__
    rebound.__annotations__ = dict(fn.__annotations__)
    rebound.__dict__.update(fn.__dict__)
    rebound.__module__ = module_name
    rebound.__qualname__ = fn.__qualname__
    rebound.__doc__ = fn.__doc__
    return rebound


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
    defined_here = str(path.resolve())
    for key, value in vars(module).items():
        if key.startswith("__") and key not in {"__all__", "__doc__"}:
            continue
        # Only rebind functions defined in this legacy file. Imported callables
        # must keep their original globals (e.g. polars as ``pl``).
        if (
            isinstance(value, types.FunctionType)
            and value.__code__.co_filename.replace("\\", "/")
            == defined_here.replace("\\", "/")
        ):
            destination[key] = _rebind_function(value, destination, name)
        else:
            destination[key] = value
    return module
