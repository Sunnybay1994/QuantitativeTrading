"""Read frozen A1 panel and nontradable equal-weight return-index reference."""
import json
from pathlib import Path
import tomllib

import polars as pl


def load(panel: Path, index: Path):
    metadata = json.loads((panel/'summary.json').read_text(encoding='utf-8'))
    products = {p.stem: pl.read_parquet(p) for p in panel.glob('*.parquet')}
    events = tomllib.loads((panel/'corporate_actions.toml').read_text(encoding='utf-8'))['splits']
    reference = pl.read_parquet(index)
    return products, events, reference, metadata
