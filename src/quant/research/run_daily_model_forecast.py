"""Refresh completed-session inputs and record a frozen research model forecast."""
import argparse
import datetime as dt
import json
from pathlib import Path

from quant.data.refresh import SHANGHAI, completed_date, latest_session, run_refresh
from quant.research.run_fixed_model_forecast import run_forecast


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
    refresh: dict = ({'latest_session': str(end), 'message': 'saved_data', 'intraday_errors': [],
                'input_quality': {'errors': [], 'scope': 'saved inputs; model checks its required features'}}
               if saved_data else run_refresh(to=to, data_root=data_root, artifact_root=artifact_root,
                    config=refresh_config, now=clock, intraday=intraday))
    (output/'refresh.json').write_text(json.dumps(refresh, ensure_ascii=False, indent=2), encoding='utf-8')
    if refresh['latest_session'] != str(end):
        raise ValueError('Refresh and forecast must use the same completed session')
    errors = [*refresh['intraday_errors'], *refresh['input_quality']['errors']]
    result = {'as_of': str(end), 'selection': str(selection), 'saved_data': saved_data,
              'rehearsal': rehearsal, 'auto_trade': False, 'conclusion': 'RESEARCH_ONLY',
              'input_errors': errors, 'forecast_path': None, 'prediction_stocks': 0,
              'status': 'input_errors' if errors else 'missing_model_inputs'}
    if not errors:
        folder = output/'forecast'
        forecast = run_forecast(selection=selection, as_of=end, output=folder,
                                data_root=data_root, rehearsal=rehearsal)
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
