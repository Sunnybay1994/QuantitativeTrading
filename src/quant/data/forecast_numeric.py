"""Daily numeric forecast inputs from the existing PIT announcement corpus."""
import ast
import tomllib
from pathlib import Path

import polars as pl

from quant.data.forecast_text_evaluation import attach_forecast_controls, read_forecast_controls

NAMES = ('forecast_p_change_midpoint', 'forecast_p_change_width')
_KEYS = ['symbol', 'publication_date', 'report_period']


def forecast_numeric_input_names(expressions: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({node.id for expression in expressions
        for node in ast.walk(ast.parse(expression, mode='eval'))
        if isinstance(node, ast.Name) and node.id in NAMES}))


def _read_ranges(source: Path, *, unique: bool = False) -> pl.DataFrame:
    frame = pl.read_parquet(source)
    if 'symbol' not in frame.columns:
        frame = frame.rename({'ts_code': 'symbol'})
    required = {*_KEYS, 'same_day_conflict', 'p_change_min', 'p_change_max'}
    if not required <= set(frame.columns):
        raise ValueError('Forecast corpus requires dated numeric ranges and conflict flags')
    if (frame.schema['symbol'] != pl.String or frame.schema['publication_date'] != pl.Date
            or frame.schema['report_period'] != pl.Date
            or frame.filter(pl.any_horizontal(pl.col(_KEYS).is_null()) | (pl.col('symbol') == '')).height
            or frame.schema['same_day_conflict'] not in (pl.Boolean, pl.Null)):
        raise ValueError('Forecast corpus requires clean publication keys and Boolean conflict flags')
    if unique:
        frame = frame.unique()
    return frame.with_columns(pl.col('p_change_min', 'p_change_max').cast(pl.Float64, strict=True),
                              pl.col('same_day_conflict').cast(pl.Boolean))


def read_forecast_numeric(source: Path) -> pl.DataFrame:
    """Keep the original event tie-break; invalid new ranges invalidate both columns.

    Values retain Tushare's percentage-point scale: 10 and 30 produce midpoint
    20 and width 20. The existing text-control implementation is not modified.
    """
    frame = _read_ranges(source, unique=True)
    bounds = frame.group_by(_KEYS).agg(pl.len().alias('_rows'),
        pl.col('same_day_conflict').fill_null(True).any().alias('_conflict'),
        pl.col('p_change_min').first(), pl.col('p_change_max').first())
    selected = read_forecast_controls(source).join(bounds, on=_KEYS, how='left', validate='1:1')
    selected = selected.with_columns((pl.col('p_change_max') - pl.col('p_change_min')).alias('_width'))
    selected = selected.with_columns(
        pl.when(pl.col('_conflict') | (pl.col('_rows') > 1)).then(pl.lit('same_day_conflict'))
        .when(pl.col('p_change_min').is_null() | pl.col('p_change_max').is_null()).then(pl.lit('missing_range'))
        .when(~pl.col('p_change_min').is_finite() | ~pl.col('p_change_max').is_finite()
              | ~pl.col('_width').is_finite()).then(pl.lit('non_finite_range'))
        .when(pl.col('p_change_min') > pl.col('p_change_max')).then(pl.lit('inverted_range'))
        .otherwise(pl.lit('valid')).alias('forecast_numeric_event_status'))
    return selected.with_columns(
        pl.when(pl.col('forecast_numeric_event_status') == 'valid').then(pl.col(NAMES[0]))
        .otherwise(None).alias(NAMES[0]),
        pl.when(pl.col('forecast_numeric_event_status') == 'valid').then(pl.col('_width'))
        .otherwise(None).alias(NAMES[1]),
    ).select(*_KEYS, *NAMES, 'forecast_numeric_event_status').sort('symbol', 'publication_date')


def attach_forecast_numeric(keys: pl.DataFrame, events: pl.DataFrame, *, max_age_days: int = 120) -> pl.DataFrame:
    """Attach same-day-close-known announcements, with strict age < max_age_days."""
    if type(max_age_days) is not int or max_age_days < 1:
        raise ValueError('Forecast numeric age must be a positive integer')
    if (not {'symbol', 'trade_date'} <= set(keys.columns) or keys.schema['symbol'] != pl.String
            or keys.schema['trade_date'] != pl.Date
            or keys.filter(pl.col('symbol').is_null() | (pl.col('symbol') == '') | pl.col('trade_date').is_null()).height):
        raise ValueError('Forecast numeric grid requires dated non-null symbol keys')
    if set(events.columns) & (set(keys.columns) - {'symbol'}):
        raise ValueError('Forecast event columns already exist in the input grid')
    if (not {*_KEYS, *NAMES, 'forecast_numeric_event_status'} <= set(events.columns)
            or events.schema['publication_date'] != pl.Date
            or events.select('symbol', 'publication_date').is_duplicated().any()):
        raise ValueError('Require unique selected numeric forecast events')
    result = attach_forecast_controls(keys, events, max_age_days=max_age_days)
    current = (pl.col('trade_date') - pl.col('forecast_publication_date')).dt.total_days() < max_age_days
    valid = current & (pl.col('forecast_numeric_event_status') == 'valid')
    return result.with_columns(
        *[pl.when(valid & pl.col(name).is_finite()).then(pl.col(name)).otherwise(None).alias(name) for name in NAMES],
        pl.when(pl.col('forecast_publication_date').is_null()).then(pl.lit('no_announcement'))
        .when(~current).then(pl.lit('expired'))
        .otherwise(pl.col('forecast_numeric_event_status')).alias('forecast_numeric_status'),
    ).sort('trade_date', 'symbol')


def read_forecast_numeric_config(data_root: Path, refresh_config: Path) -> pl.DataFrame:
    """Resolve the existing corpus path; this loader never collects remote data."""
    settings = tomllib.loads(refresh_config.read_text(encoding='utf-8'))
    source = settings.get('forecast_numeric_corpus')
    age = settings.get('forecast_numeric_max_age_days', 120)
    if not isinstance(source, str) or not source or type(age) is not int or age != 120:
        raise ValueError('Numeric forecast baseline requires a corpus and frozen 120-day expiry')
    path = Path(source)
    return read_forecast_numeric(path if path.is_absolute() else data_root/path)


def forecast_numeric_counts(source: Path) -> dict:
    """Compact source calibration; never include forecast reason text."""
    frame = _read_ranges(source)
    events = read_forecast_numeric(source)
    finite_min = pl.col('p_change_min').is_finite().fill_null(False)
    finite_max = pl.col('p_change_max').is_finite().fill_null(False)
    return {'source_rows': frame.height, 'finite_min_rows': frame.filter(finite_min).height,
        'finite_max_rows': frame.filter(finite_max).height,
        'finite_range_rows': frame.filter(finite_min & finite_max).height,
        'inverted_range_rows': frame.filter(finite_min & finite_max & (pl.col('p_change_min') > pl.col('p_change_max'))).height,
        'same_day_conflict_rows': frame.filter(pl.col('same_day_conflict').fill_null(False)).height,
        'unknown_conflict_rows': frame.filter(pl.col('same_day_conflict').is_null()).height,
        'retained_events': events.height,
        'valid_events': events.filter(pl.col('forecast_numeric_event_status') == 'valid').height,
        'event_status_counts': {row['forecast_numeric_event_status']: row['len']
            for row in events.group_by('forecast_numeric_event_status').len().sort('forecast_numeric_event_status').to_dicts()},
        'units': 'percentage_points', 'same_day_close_available': True, 'maximum_age_days_exclusive': 120}
