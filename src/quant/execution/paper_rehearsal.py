"""Generate isolated month-end reference orders from frozen prospective forecasts."""
import argparse
import datetime as dt
import json
import shutil
import tomllib
from pathlib import Path

from quant.data.refresh import SHANGHAI
from quant.execution.q10_paper import run as run_q10

DEFAULT_CONFIG = Path('configs/research/daily_observation_q2_sue_v2_20260930.toml')


def rehearse_account(*, account: Path, config: Path, end: dt.date,
                     data_root: Path, forecast: Path | None = None) -> dict:
    """Clone the last preceding snapshot; never advance the production account."""
    account = account.resolve()
    snapshots = sorted(p for p in account.glob('????-??-??/state.json')
                       if dt.date.fromisoformat(p.parent.name) < end)
    if not snapshots:
        raise ValueError(f'No account snapshot before rehearsal date {end}: {account}')
    stamp = dt.datetime.now(SHANGHAI).strftime('%Y%m%dT%H%M%S_%f')
    output = account/'rehearsal'/f'{end}_{stamp}'
    output.mkdir(parents=True, exist_ok=False)
    source = snapshots[-1]
    shutil.copytree(source.parent, output/source.parent.name)
    for name in ('config.toml', 'controls.json'):
        if (account/name).is_file():
            shutil.copy2(account/name, output/name)
    receipt = {'rehearsal': True, 'auto_trade': False, 'pushed': False,
               'source_account': str(account), 'source_snapshot': str(source),
               'requested_date': str(end), 'output': str(output), 'status': 'running'}

    def save() -> None:
        (output/'rehearsal.json').write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    try:
        receipt['result'] = run_q10(config_path=config, data_root=data_root,
                                   output=output, end=end, forecast=forecast, as_month_end=True)
        receipt['status'] = 'complete'
        banner = '# 月末隔离预演（不推送，不计入正式账户）\n\n'
        for name in ('latest_orders.md', 'report.md'):
            path = output/name
            path.write_text(banner + path.read_text(encoding='utf-8'), encoding='utf-8')
    except Exception as exc:
        receipt.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    save()
    return receipt


def run(*, config: Path = DEFAULT_CONFIG, end: dt.date,
        forecast: Path | None = None) -> dict:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    if settings.get('auto_trade') is not False:
        raise ValueError('Paper rehearsal requires auto_trade=false')
    results = {}
    for name in ('q10', 'q10_shadow'):
        spec = settings.get(name)
        if not spec:
            continue
        try:
            results[name] = rehearse_account(account=Path(spec['output']),
                config=Path(spec['config']), end=end,
                data_root=Path(settings.get('data_root', 'data')), forecast=forecast)
        except Exception as exc:
            results[name] = {'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'}
    return {'as_of': str(end), 'rehearsal': True, 'auto_trade': False, 'pushed': False,
            'status': 'complete' if results and all(
                r['status'] == 'complete' for r in results.values()) else 'failed',
            'accounts': results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--to', type=dt.date.fromisoformat,
                        default=dt.datetime.now(SHANGHAI).date())
    parser.add_argument('--forecast', type=Path)
    parser.add_argument('--as-month-end', action='store_true', required=True)
    args = parser.parse_args()
    result = run(config=args.config, end=args.to, forecast=args.forecast)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['status'] == 'complete' else 1)


if __name__ == '__main__':
    main()
