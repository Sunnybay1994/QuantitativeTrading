"""Cooperative time-slice boundary, inherited only by scheduled workers."""
import os
import time


class SliceYield(RuntimeError):
    """The last complete unit is durable; resume the same frozen run."""


def checkpoint() -> None:
    from quant.core.capital_window import CapitalPathPause, checkpoint as capital_checkpoint
    try:
        capital_checkpoint()
    except CapitalPathPause as exc:
        raise SliceYield('Time slice yielded for capital-path priority: '+str(exc)) from exc
    deadline = os.environ.get('QUANT_SLICE_SOFT_DEADLINE')
    if deadline and time.time() >= float(deadline):
        raise SliceYield('Time slice yielded at a durable computation boundary')
