"""Refresh completed-session inputs and record a frozen research model forecast."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.daily_input_quality import run_quality
from quant.data.factor_panels import panel_complete, read_coverage
from quant.data.model_forward_inputs import read_forward_values
from quant.data.refresh import SHANGHAI, completed_date, latest_session, refresh_factor_selection, run_refresh
from quant.factors.library import load_library
from quant.research.run_fixed_model_forecast import run_forecast


def model_factor_requirements(*, selection: Path, refresh_config: Path, as_of: dt.date) -> dict:
    """Resolve the same causal annual fit used by the frozen forecast entry point."""
    config = tomllib.loads((selection/'config.toml').read_text(encoding='utf-8'))
    source = Path(config['research']['predictions'])
    fits = json.loads((source/'summary.json').read_text(encoding='utf-8'))['annual_fits']
    available = [fit for fit in fits if fit.get('refit_close') and fit['refit_close'] <= str(as_of)]
    if not available:
        raise ValueError('No trained model existed at this signal date')
    fit = max(available, key=lambda row: row['refit_close'])
    if (as_of.year > fit['test_year'] or fit['last_known_exit'] > fit['refit_close']
            or fit['training_months'] < config['selection']['minimum_training_months']):
        raise ValueError('Require a causal annual model with sufficient history; refresh the annual fit')
    factors = fit['factors']
    if (not isinstance(factors, list) or not factors or len(factors) != len(set(factors))
            or any(not isinstance(factor, str) or not factor for factor in factors)):
        raise ValueError('Frozen annual fit requires distinct nonempty factor IDs')
    settings = tomllib.loads(refresh_config.read_text(encoding='utf-8'))['factors']
    selected = refresh_factor_selection(settings)
    refreshed = {definition.id for definition in load_library(Path(settings['library']), selected)}
    excluded = settings.get('excluded_factors', [])
    return {'prediction_source': str(source), 'refit_close': fit['refit_close'],
        'test_year': fit['test_year'], 'required_factors': factors,
        'refresh_selection': selected, 'excluded_factors': excluded,
        'required_excluded': sorted(set(factors) & set(excluded)),
        'required_outside_refresh_selection': sorted(set(factors) - refreshed)}


def check_model_factor_date(*, data_root: Path, factors: list[str], as_of: dt.date) -> tuple[list[dict], list[str]]:
    """Check coverage and actual same-date rows; a computed null is not stale data."""
    evidence, errors = [], []
    for factor in factors:
        row: dict[str, Any] = {'factor': factor, 'as_of': str(as_of), 'coverage_start': None, 'coverage_end': None,
               'coverage_complete': False, 'actual_rows': None, 'finite_rows': None, 'null_rows': None,
               'status': 'missing_computation'}
        try:
            coverage = read_coverage(data_root, factor, as_of.year)
            complete = panel_complete(data_root, factor, as_of.year, as_of, as_of)
            row.update(coverage_start=coverage.get('start'), coverage_end=coverage.get('end'),
                       coverage_complete=complete)
            if not complete:
                errors.append(f'{factor}: computation coverage does not include {as_of}')
            else:
                # The data reader applies an exact equality filter before collecting.
                frame = read_forward_values(data_root=data_root, factors=[factor], as_of=as_of)[factor]
                if (not {'symbol', 'trade_date', 'value'} <= set(frame.columns)
                        or frame.schema['trade_date'] != pl.Date or frame.schema['symbol'] != pl.String
                        or frame.filter(pl.col('trade_date').is_null() | (pl.col('trade_date') != as_of)
                                        | pl.col('symbol').is_null() | (pl.col('symbol') == '')).height
                        or frame.select('symbol', 'trade_date').is_duplicated().any()):
                    raise ValueError('Invalid same-date factor keys')
                values = frame['value'].cast(pl.Float64)
                row.update(actual_rows=frame.height, finite_rows=values.is_finite().fill_null(False).sum(),
                           null_rows=values.null_count())
                if frame.is_empty():
                    errors.append(f'{factor}: no actual factor rows for {as_of}, despite coverage metadata')
                else:
                    row['status'] = 'computed_with_values' if row['finite_rows'] else 'computed_without_finite_values'
        except (OSError, ValueError, TypeError, KeyError, pl.exceptions.PolarsError) as exc:
            errors.append(f'{factor}: cannot verify signal-date factor inputs: {type(exc).__name__}: {exc}')
            row['status'] = 'invalid_computation_evidence'
        evidence.append(row)
    return evidence, errors


def check_saved_input_quality(*, data_root: Path, config: Path, end: dt.date, output: Path) -> dict:
    """Run the refresh quality checks on local inputs with the same scope and thresholds."""
    try:
        settings = tomllib.loads(config.read_text(encoding='utf-8'))
        quality = settings.get('quality', {})
        if not quality.get('enabled', False):
            raise ValueError('Saved-data prediction requires enabled local input quality checks')
        definitions = load_library(Path(settings['factors']['library']),
                                   refresh_factor_selection(settings['factors']))
        battery = tomllib.loads(Path(quality['battery_config']).read_text(encoding='utf-8'))
        return run_quality(data_root=data_root, config=config, end=end,
            factors=[{'id': row.id, 'family': row.family} for row in definitions], financials={},
            output=output, lookback_sessions=quality.get('lookback_sessions', 5),
            minimum_symbols=battery['minimum_symbols'])
    except (OSError, ValueError, TypeError, KeyError, pl.exceptions.PolarsError) as exc:
        return {'as_of': str(end), 'errors': [
            f'Cannot complete saved-data input quality checks: {type(exc).__name__}: {exc}'],
            'message': 'local_input_quality_failed'}


def run_daily(*, to: str, selection: Path, output: Path, data_root: Path,
              refresh_config: Path, artifact_root: Path, saved_data: bool = False,
              intraday: bool = True, rehearsal: bool = False, now: dt.datetime | None = None) -> dict:
    """One dated invocation; preserve forecasts and never change account positions."""
    if output.exists():
        raise FileExistsError('Use a new daily record directory')
    clock = now or dt.datetime.now(SHANGHAI)
    end = latest_session(data_root=data_root, through=completed_date(to, clock), refresh_calendar=not saved_data)
    decision = json.loads((selection/'selection.json').read_text(encoding='utf-8'))
    if end < dt.date.fromisoformat(decision['forward_start']) and not rehearsal:
        raise ValueError('Pre-forward records require explicit rehearsal')
    if decision['conclusion'] != 'RESEARCH_ONLY' or decision['auto_trade'] is not False:
        raise ValueError('Require the frozen research-only selection')
    output.mkdir(parents=True, exist_ok=False)
    requirements, requirement_errors = None, []
    try:
        requirements = model_factor_requirements(selection=selection, refresh_config=refresh_config, as_of=end)
        if requirements['required_outside_refresh_selection']:
            requirement_errors.append('Frozen model requires factors outside the refresh selection: '
                + ', '.join(requirements['required_outside_refresh_selection']))
        if requirements['required_excluded']:
            requirement_errors.append('Frozen model requires explicitly excluded factors: '
                + ', '.join(requirements['required_excluded']))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        requirement_errors.append(f'Cannot resolve frozen model factor requirements: {type(exc).__name__}: {exc}')
    if requirement_errors:
        refresh: dict = {'latest_session': str(end), 'message': 'model_factor_requirements_failed',
            'intraday_errors': [], 'input_quality': {'errors': [], 'message': 'skipped: model requirements failed'}}
    elif saved_data:
        refresh = {'latest_session': str(end), 'message': 'saved_data', 'intraday_errors': [],
            'input_quality': check_saved_input_quality(data_root=data_root, config=refresh_config,
                end=end, output=output/'input_quality')}
    else:
        refresh = run_refresh(to=to, data_root=data_root, artifact_root=artifact_root,
            config=refresh_config, now=clock, intraday=intraday)
    (output/'refresh.json').write_text(json.dumps(refresh, ensure_ascii=False, indent=2), encoding='utf-8')
    if refresh['latest_session'] != str(end):
        raise ValueError('Refresh and forecast must use the same completed session')
    errors = [*requirement_errors, *refresh['intraday_errors'], *refresh['input_quality']['errors']]
    evidence: list[dict] = []
    if not errors and requirements is not None:
        evidence, factor_errors = check_model_factor_date(data_root=data_root,
            factors=requirements['required_factors'], as_of=end)
        errors.extend(factor_errors)
    result = {'as_of': str(end), 'selection': str(selection), 'saved_data': saved_data,
              'rehearsal': rehearsal, 'auto_trade': False, 'conclusion': 'RESEARCH_ONLY',
              'input_errors': errors, 'forecast_path': None, 'prediction_stocks': 0,
              'factor_health': refresh['input_quality'].get('factor_health'),
              'model_factor_requirements': requirements, 'model_factor_inputs': evidence,
              'status': 'input_errors' if errors else 'missing_model_inputs'}
    if not errors:
        folder = output/'forecast'
        quality_args = ({'input_quality': refresh['input_quality']}
                        if decision.get('requires_local_quality') else {})
        forecast = run_forecast(selection=selection, as_of=end, output=folder,
                                data_root=data_root, rehearsal=rehearsal, **quality_args)
        result.update(forecast_path=str(folder), prediction_stocks=forecast['prediction_stocks'],
                      status='recorded' if forecast['prediction_stocks'] else 'missing_model_inputs')
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--to', default='today')
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--refresh-config', type=Path, default=Path('configs/data/refresh.toml'))
    parser.add_argument('--artifact-root', type=Path, default=Path('artifacts'))
    parser.add_argument('--saved-data', action='store_true', help='Use already published inputs without refreshing providers')
    parser.add_argument('--intraday', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--rehearsal', action='store_true')
    args = parser.parse_args()
    result = run_daily(to=args.to, selection=args.selection, output=args.output, data_root=args.data_root,
        refresh_config=args.refresh_config, artifact_root=args.artifact_root, saved_data=args.saved_data,
        intraday=args.intraday, rehearsal=args.rehearsal)
    print(json.dumps(result, ensure_ascii=False))
    if result['status'] != 'recorded':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
