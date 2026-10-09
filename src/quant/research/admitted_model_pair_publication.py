"""Publish an already-written paired-account year after transient Windows locks."""
from pathlib import Path
import time


REQUIRED = ('account.json', 'nav.parquet', 'trades.parquet', 'rejections.parquet',
            'orders.parquet', 'holdings.parquet', 'exposure.parquet')
DELAYS = (.1, .3, 1.)


def publish_completed_year(stage: Path, target: Path) -> None:
    """Retry only the rename, at most four times; never replace or recompute a year."""
    stage, target = stage.resolve(), target.resolve()
    if (stage.parent != target.parent or len(target.name) != 4 or not target.name.isdigit()
            or not stage.name.startswith('.'+target.name+'-')):
        raise ValueError('Year publication requires sibling staging and year directories')
    if not stage.is_dir() or any(not (stage/name).is_file() for name in REQUIRED):
        raise ValueError('Year publication requires every completed account artifact')
    for attempt in range(len(DELAYS)+1):
        if target.exists():
            raise FileExistsError('Completed year must not be replaced: '+str(target))
        try:
            stage.rename(target)
            return
        except PermissionError:
            # A scanner can briefly hold a just-written Windows directory. Keep
            # its complete contents and retry publication, never account work.
            if attempt == len(DELAYS) or target.exists() or not stage.is_dir():
                raise
            time.sleep(DELAYS[attempt])
