"""Publish a bounded recovery batch from existing same-day raw, preserving old clean."""
import argparse
import json
import math
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.daily_basic_field_recovery import recover_daily_basic_fields


def _version(value: str) -> str:
    if (not value or value in ('.', '..')
            or any(not c.isascii() or not (c.isalnum() or c in '_.-') for c in value)):
        raise ValueError('Use a plain new field-recovery version name')
    return value


def _raw_path(value: str, data_root: Path) -> Path:
    root = data_root.resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = (root.parent / candidate if candidate.parts and candidate.parts[0] == root.name
                     else root / candidate)
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root / 'raw') or not candidate.is_file():
        raise ValueError('Recovery source must be an existing file inside data/raw')
    return candidate


def publish_field_recovery(*, config: Path, data_root: Path) -> dict[str, Any]:
    """Recover each requested key independently; failed keys stay quarantined."""
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    version = _version(settings['version'])
    output = data_root / 'clean/daily_basic_field_recovery' / version
    if output.exists():
        raise FileExistsError('Choose a new field-recovery version; existing clean is preserved')
    plan = pl.read_parquet(Path(settings['keys_file']))
    required = {'symbol', 'as_of', 'raw_path', 'daily_raw_path', 'adjustment_raw_path'}
    if not required <= set(plan.columns):
        raise ValueError('Recovery keys need symbol, as_of and all three raw source paths')
    if (plan.height != settings['expected_rows'] or not 0 < plan.height <= 100
            or plan.select('symbol', 'as_of').is_duplicated().any()
            or plan.select(pl.any_horizontal(pl.col('symbol', 'as_of').is_null()).any()).item()
            or plan.schema['as_of'] != pl.Date):
        raise ValueError('Require the exact bounded batch with unique dated keys')
    cache: dict[Path, pl.DataFrame] = {}
    recovered, quarantined = [], []
    for row in plan.sort('as_of', 'symbol').iter_rows(named=True):
        try:
            tables = {}
            for name, field in [('daily', 'daily_raw_path'), ('adjustment', 'adjustment_raw_path'),
                                ('basic', 'raw_path')]:
                path = _raw_path(row[field], data_root)
                if path not in cache:
                    cache[path] = pl.read_parquet(path)
                tables[name] = cache[path].filter(pl.col('ts_code') == row['symbol'])
            result = recover_daily_basic_fields(**tables, date=row['as_of'])
            if result.height != 1 or result['symbol'].item() != row['symbol']:
                raise ValueError('Recovered row does not match the requested key')
            if 'signal_close' in row:
                close = row['signal_close']
                if close is None or not math.isfinite(close) or abs(result['close'].item() - close) > 1e-8:
                    raise ValueError('Recovered close differs from the frozen signal close')
            recovered.append(result.with_columns(
                pl.lit(row['raw_path']).alias('raw_basic_path'),
                pl.lit(row['daily_raw_path']).alias('raw_daily_path'),
                pl.lit(row['adjustment_raw_path']).alias('raw_adjustment_path')))
        except (ValueError, TypeError) as exc:
            quarantined.append({'symbol': row['symbol'], 'trade_date': row['as_of'],
                'quality_reason': str(exc), 'raw_basic_path': row['raw_path']})
    output.mkdir(parents=True, exist_ok=False)
    data = pl.concat(recovered) if recovered else None
    if data is not None:
        data.sort('trade_date', 'symbol').write_parquet(output / 'data.parquet')
    rejected = pl.DataFrame(quarantined, schema={'symbol': pl.String, 'trade_date': pl.Date,
        'quality_reason': pl.String, 'raw_basic_path': pl.String})
    rejected.write_parquet(output / 'quarantined.parquet')
    full = int(data['daily_basic_schema_valid'].sum()) if data is not None else 0
    summary = {'version': version, 'requested_rows': plan.height,
        'recovered_rows': data.height if data is not None else 0, 'full_schema_rows': full,
        'supplement_only_rows': data.height-full if data is not None else 0,
        'quarantined_rows': rejected.height, 'keys_file': settings['keys_file'],
        'source_dates': 'strictly same day, matching raw stock keys and closing prices',
        'market_value_check': 'raw total_mv * 10000 versus close * total_share * 10000; tolerance 1ppm',
        'usage': 'Rows with daily_basic_schema_valid=false are partial supplements, not DailyBasic1dSchema rows',
        'output': str(output)}
    (output / 'config.toml').write_bytes(config.read_bytes())
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


def read_field_recovery(*, data_root: Path, version: str, full_schema_only: bool = True) -> pl.DataFrame:
    """Read explicit recovery data with quality/provenance columns retained."""
    frame = pl.read_parquet(data_root / 'clean/daily_basic_field_recovery' / _version(version) / 'data.parquet')
    return frame.filter(pl.col('daily_basic_schema_valid')) if full_schema_only else frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    args = parser.parse_args()
    print(json.dumps(publish_field_recovery(config=args.config, data_root=args.data_root), ensure_ascii=False))


if __name__ == '__main__':
    main()
