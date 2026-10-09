"""Compatibility shim — implementation lives in legacy/."""
from quant._legacy_shim import bind

bind(__name__, globals())
