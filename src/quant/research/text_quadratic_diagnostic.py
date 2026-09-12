"""Fixed quadratic numerical-control diagnostic on saved P7 common support."""
from __future__ import annotations

import json
from pathlib import Path
import tomllib

import numpy as np
import polars as pl

from quant.research.forecast_text_incremental import _ic

CONFIG = Path('configs/research/p7_quadratic_diagnostic_20260912.toml')


def project(text: np.ndarray, continuous: np.ndarray,
            industry: np.ndarray) -> tuple[np.ndarray, int]:
    """OLS with a fixed second-order basis and no outcome input."""
    if (continuous.shape != (len(text), 3) or len(industry) != len(text)
            or not np.isfinite(text).all() or not np.isfinite(continuous).all()
            or not all(isinstance(x, str) and bool(x.strip()) for x in industry)):
        raise ValueError('Complete aligned inputs required')
    if not len(text):
        return np.empty(0), 0
    columns = [np.ones(len(text))]
    scaled = []
    for raw in continuous.T:
        scale = float(np.std(raw))
        if scale > 1e-12:
            scaled.append((raw - np.mean(raw)) / scale)
    columns.extend(scaled)
    columns.extend(x * y for i, x in enumerate(scaled) for y in scaled[i:])
    columns.extend((industry == level).astype(float) for level in np.unique(industry)[1:])
    design = np.column_stack(columns)
    coefficients, _, rank, _ = np.linalg.lstsq(design, text, rcond=None)
    residual = text - design @ coefficients
    if len(text) <= rank or np.std(residual) <= 1e-12 * max(1., float(np.std(text))):
        residual[:] = np.nan
    return residual, int(rank)


def run(support_path: Path, *, output: Path, minimum_symbols: int = 100) -> dict:
    """Reuse the primary diagnostic's paired support, with no data reads or API calls."""
    spec = tomllib.loads(CONFIG.read_text(encoding='utf-8'))
    support = pl.read_parquet(support_path)
    sue = 'pit_sue8_context_v2'
    required = {'factor', 'frequency', 'symbol', 'trade_date', 'directed_text',
                'residual_text', 'next_open_label', 'forecast_p_change_midpoint',
                sue, 'total_market_value', 'industry_l1'}
    if not required.issubset(support.columns):
        raise ValueError('Saved SUE v2 common support required')
    if support.select('factor', 'frequency', 'symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate common support')
    rows = []
    for group in support.sort('symbol').partition_by('factor', 'frequency', 'trade_date'):
        # The primary residual is null when paired coverage or rank is inadequate.
        eligible = group.height >= minimum_symbols and group['residual_text'].is_finite().fill_null(False).all()
        residual = np.full(group.height, np.nan)
        rank = None
        if eligible:
            size = group['total_market_value'].to_numpy()
            if not (size > 0).all():
                raise ValueError('Positive market value required')
            controls = np.column_stack([group['forecast_p_change_midpoint'].to_numpy(),
                                        group[sue].to_numpy(), np.log(size)])
            residual, rank = project(group['directed_text'].to_numpy(), controls,
                                     group['industry_l1'].to_numpy())
        labels = group['next_open_label'].to_numpy()
        rows.append({'factor': group['factor'][0], 'frequency': group['frequency'][0],
                     'trade_date': group['trade_date'][0], 'common_count': group.height,
                     'quadratic_rank': rank,
                     'linear_residual_ic': _ic(group['residual_text'].to_numpy(), labels) if eligible else None,
                     'quadratic_residual_ic': _ic(residual, labels) if eligible else None})
    points = pl.from_dicts(rows, schema={'factor': pl.String, 'frequency': pl.String,
        'trade_date': pl.Date, 'common_count': pl.Int64, 'quadratic_rank': pl.Int64,
        'linear_residual_ic': pl.Float64, 'quadratic_residual_ic': pl.Float64})
    output.mkdir(parents=True, exist_ok=False)
    (output / 'config.toml').write_bytes(CONFIG.read_bytes())
    points.write_parquet(output / 'paired_ic.parquet')
    result = {'scope': spec['scope'], 'interpretation': spec['interpretation'],
              'source': str(support_path), 'sections': points.height,
              'usable_quadratic_sections': points['quadratic_residual_ic'].count()}
    (output / 'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result
