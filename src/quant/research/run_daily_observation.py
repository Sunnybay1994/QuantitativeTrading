"""Refresh and record independent research forecasts and frozen observation accounts."""
import argparse
import datetime as dt
import json
import tomllib
from pathlib import Path
from typing import Any, Callable

from quant.data.refresh import SHANGHAI, completed_date, latest_session
from quant.execution.cross_asset_forward import run as run_b20
from quant.execution.stock_paper import run as run_b32
from quant.execution.daily_observation_risk import DEFAULT_CONFIG, run as run_risk
from quant.reporting.rolling_signal_monitor import DEFAULT_CONFIG as MONITOR_CONFIG, run as run_monitor
from quant.reporting.stock_paper_monthly import ACCOUNTS, run as run_monthly
from quant.research.run_daily_model_forecast import run_daily


def _overlap(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def run(*, config: Path, output: Path, to: str = 'today', saved_data: bool = False,
        rehearsal: bool = False, account_root: Path | None = None,
        b20_output: Path | None = None, b32_output: Path | None = None,
        now: dt.datetime | None = None) -> dict[str, Any]:
    """Continue independent components; only monthly reporting depends on B32 success."""
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    if settings['auto_trade'] is not False:
        raise ValueError('Observation requires auto_trade=false')
    defaults = [Path(settings[k]['output']).resolve() for k in ('b20', 'b32')]
    root = account_root.resolve() if account_root else None
    if rehearsal and root is None:
        raise ValueError('Rehearsal requires an isolated --account-root')
    accounts = [
        (override or (root / name if root else default)).resolve()
        for override, name, default in zip((b20_output, b32_output), ('b20', 'b32'), defaults)
    ]
    if _overlap(*accounts) or any(_overlap(output.resolve(), p) for p in accounts):
        raise ValueError('Record and account directories must be separate')
    if rehearsal and any(
        root not in p.parents or any(_overlap(p, default) for default in defaults)
        for p in accounts
    ):
        raise ValueError('Rehearsal accounts must stay below account-root, outside production')
    if output.exists():
        raise FileExistsError('Use a new daily summary directory')
    clock = now or dt.datetime.now(SHANGHAI)
    data_root, artifact_root = Path(settings['data_root']), Path(settings['artifact_root'])
    output.mkdir(parents=True)
    stages: dict[str, Any] = {}
    result: dict[str, Any] = {
        'requested_to': to, 'as_of': None, 'saved_data': saved_data, 'rehearsal': rehearsal,
        'auto_trade': False, 'conclusion': 'RESEARCH_ONLY', 'status': 'incomplete', 'stages': stages,
        'policy': 'B20 independent; B32 requires refresh success or saved-data; monthly requires B32.',
        'account_paths': dict(zip(('b20', 'b32'), map(str, accounts))),
    }

    def save_summary() -> None:
        temporary = output/'summary.json.tmp'
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str),
                             encoding='utf-8')
        temporary.replace(output/'summary.json')

    save_summary()

    def stage(name: str, operation: Callable[[], dict], valid: Callable[[dict], bool]) -> bool:
        stages[name] = {'status': 'running'}
        save_summary()
        try:
            value = operation()
            ok = valid(value)
            stages[name] = {'status': 'complete' if ok else 'incomplete', 'result': value}
        except Exception as exc:
            ok = False
            stages[name] = {'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'}
        save_summary()
        return ok

    try:
        end = latest_session(data_root=data_root, through=completed_date(to, clock),
                             refresh_calendar=not saved_data)
    except Exception as exc:
        stages['calendar'] = {'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'}
    else:
        date = str(end)
        result['as_of'] = date
        stage('model', lambda: run_daily(
            to=date, selection=Path(settings['model']['selection']), output=output/'model',
            data_root=data_root, refresh_config=Path(settings['refresh_config']),
            artifact_root=artifact_root, saved_data=saved_data,
            intraday=settings.get('intraday', True), rehearsal=rehearsal, now=clock),
            lambda value: value.get('as_of') == date and value.get('status') == 'recorded')
        try:
            refresh = json.loads((output/'model/refresh.json').read_text(encoding='utf-8'))
            refresh_errors = [*refresh['intraday_errors'], *refresh['input_quality']['errors']]
            if refresh['latest_session'] != date:
                refresh_errors.append('Refresh snapshot does not match requested session')
        except (OSError, ValueError, KeyError) as exc:
            refresh_errors = [f'Unavailable input-quality result: {type(exc).__name__}: {exc}']
        refresh_ok = not refresh_errors
        stages['refresh'] = {'status': 'complete' if refresh_ok else 'failed',
                             'mode': 'saved_data' if saved_data else 'refresh',
                             'input_errors': refresh_errors,
                             'path': str(output/'model/refresh.json')}
        stage('b20', lambda: run_b20(config_path=Path(settings['b20']['config']),
              data_root=data_root, output=accounts[0], end=end, refresh_data=not saved_data),
              lambda value: value.get('as_of') == date and len(value.get('accounts', [])) == 6
              and all(Path(a['output']).name == date for a in value['accounts']))
        stock_ok = False
        # Saved observation accounts retain their independent, snapshot-specific validation.
        if refresh_ok or saved_data:
            stock_ok = stage('b32', lambda: run_b32(
                config_path=Path(settings['b32']['config']), data_root=data_root,
                output=accounts[1], end=end), lambda value:
                {a['account'] for a in value.get('accounts', [])} == set(ACCOUNTS)
                and all(a['as_of'] == date for a in value['accounts']))
        else:
            stages['b32'] = {'status': 'skipped', 'reason': 'refresh did not complete'}
        if stock_ok:
            def monthly() -> dict:
                # The existing report reads latest snapshots, not an explicit requested date.
                for account in ACCOUNTS:
                    snapshots = sorted((accounts[1]/account).glob('????-??-??/state.json'))
                    if not snapshots or snapshots[-1].parent.name != date:
                        raise ValueError('Monthly source snapshots do not match requested session')
                folder = output/'monthly'
                value = run_monthly(ledger_root=accounts[1], data_root=data_root,
                                    artifact_root=artifact_root, output=folder)
                if value.get('action') == 'no-op':
                    value = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
                return {**value, 'output': str(folder)}
            stage('monthly', monthly, lambda value: value.get('as_of') == date)
        else:
            stages['monthly'] = {'status': 'skipped', 'reason': 'B32 did not complete'}
    stage('risk', lambda: run_risk(record=result, output=output/'risk', data_root=data_root,
        config=Path(settings.get('risk_config', DEFAULT_CONFIG))),
        lambda value: value.get('status') == 'complete')
    if result['as_of'] is not None:
        stage('signal_monitor', lambda: run_monitor(known_through=dt.date.fromisoformat(result['as_of']),
            output=output/'signal_monitor', config=Path(settings.get('monitor_config', MONITOR_CONFIG))),
            lambda value: value.get('status') in ('insufficient', 'warning', 'observed'))
    else:
        stages['signal_monitor'] = {'status': 'skipped', 'reason': 'No known session cutoff'}
    result['signal_monitor_status'] = stages['signal_monitor'].get('result', {}).get('status', 'unavailable')
    result['requires_review'] = (stages['risk'].get('result', {}).get('requires_review', True)
        or stages['signal_monitor'].get('result', {}).get('requires_review', True))
    result['status'] = ('complete' if stages and all(
        s['status'] == 'complete' for s in stages.values()) else 'incomplete')
    save_summary()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/research/daily_observation_v1.toml'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--to', default='today')
    parser.add_argument('--saved-data', action='store_true')
    parser.add_argument('--rehearsal', action='store_true')
    parser.add_argument('--account-root', type=Path)
    parser.add_argument('--b20-output', type=Path)
    parser.add_argument('--b32-output', type=Path)
    args = parser.parse_args()
    result = run(**vars(args))
    print(json.dumps(result, ensure_ascii=False, default=str))
    if result['status'] != 'complete':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
