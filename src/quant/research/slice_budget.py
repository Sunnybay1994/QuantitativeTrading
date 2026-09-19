"""Cooperative time-slice boundary, inherited only by scheduled workers."""
import os
import time


class SliceYield(RuntimeError):
    """The last complete unit is durable; resume the same frozen run."""


def checkpoint() -> None:
    deadline = os.environ.get('QUANT_SLICE_SOFT_DEADLINE')
    if deadline and time.time() >= float(deadline):
        raise SliceYield('Time slice yielded at a durable computation boundary')
