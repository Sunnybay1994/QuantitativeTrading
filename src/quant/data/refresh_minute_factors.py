"""Maintain minute-dependent factors outside the daily account refresh path."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path

from quant.data.refresh import (SHANGHAI, completed_date, latest_session, refresh_factor_selection,
                                refresh_factors)
from quant.data.refresh_progress import RefreshProgress
from quant.factors.library import load_library
from quant.research.factor_intraday import minute_input_names


def run(*, config: Path, data_root: Path, artifact_root: Path, output: Path,
        to: str = 'today', collect: bool = False, now: dt.datetime | None = None) -> dict:
    """Reconcile a bounded recent interval even after a partial collector response."""
    if output.exists():
        raise FileExistsError('Use a new minute-factor record directory')
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    factor_settings = settings['factors']
    if not factor_settings.get('enabled', False):
        raise ValueError('Minute factor maintenance requires factor computation enabled')
    definitions = load_library(Path(factor_settings['library']), refresh_factor_selection(factor_settings))
    names = sorted(row.id for row in definitions if minute_input_names((row.expr,)))
    if not names:
        raise ValueError('No minute-dependent factors in configured library')
    days = settings.get('intraday', {}).get('stock_lookback_days', 7)
    if type(days) is not int or days < 1:
        raise ValueError('Minute refresh lookback must be positive calendar days')
    through = completed_date(to, now or dt.datetime.now(SHANGHAI))
    end = latest_session(data_root=data_root, through=through, refresh_calendar=collect)
    start = end - dt.timedelta(days=days - 1)
    output.mkdir(parents=True, exist_ok=False)
    progress = RefreshProgress(output/'progress.json')
    result = {'as_of': str(end), 'start': str(start), 'factor_ids': names,
              'status': 'running', 'auto_trade': False, 'collection_requested': collect,
              'coverage_claim': 'Computation may contain nulls; this is not full-market minute coverage'}
    try:
        minutes: dict = {}
        if collect:
            from quant.data.intraday import refresh_intraday

            minutes = progress.run('minutes', refresh_intraday, data_root=data_root, end=end,
                refresh_config=config, required_stocks_only=True, stock_from=start, progress=progress.update)
        result['minutes'] = minutes
        if minutes.get('stock_alternate_from'):
            start = min(start, dt.date.fromisoformat(minutes['stock_alternate_from']))
        result['rebuild_start'] = str(start)
        # A prior run may have materialized nulls before late minute bars arrived.
        # The existing engine loads rolling warmup before this bounded rebuild.
        result['factors'] = progress.run('factors', refresh_factors, data_root=data_root,
            artifact_root=artifact_root, config=config, end=end,
            settings={**factor_settings, 'selected': ','.join(names), 'excluded_factors': [], 'start': str(start)},
            minute_start=start)
        result['status'] = 'partial' if minutes.get('errors') else 'computed'
    except Exception as exc:
        result.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/data/refresh_q2_sue_v2_model_20260912.toml'))
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--artifact-root', type=Path, default=Path('artifacts'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--to', default='today')
    parser.add_argument('--collect', action='store_true')
    args = parser.parse_args()
    stamp = dt.datetime.now().strftime('%Y%m%dT%H%M%S%f')
    result = run(config=args.config, data_root=args.data_root, artifact_root=args.artifact_root,
        output=args.output or args.artifact_root/'minute_refresh'/'factors'/stamp,
        to=args.to, collect=args.collect)
    print(json.dumps(result, ensure_ascii=False, default=str))
    if result['status'] != 'computed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
