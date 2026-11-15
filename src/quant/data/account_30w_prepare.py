"""Prepare two-ETF immutable inputs before account writers, without opening a book."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib

from quant.data.account_30w_top15_inputs import capture, read_capture, sha, shared_actions
from quant.data.refresh import SHANGHAI, latest_session

CONFIG = Path('configs/paper/account_30w_top15_v1_20261108.toml')


def run(*, config=CONFIG, data_root=Path('data'), output, end=None, connector=None, now=None):
    clock = now or dt.datetime.now(SHANGHAI)
    if clock.tzinfo is None:
        raise ValueError('Require an aware preparation clock')
    clock = clock.astimezone(SHANGHAI)
    settings = tomllib.loads(Path(config).read_text(encoding='utf-8'))
    if settings['paper']['auto_trade'] is not False:
        raise ValueError('Input preparation requires auto_trade=false')
    through = clock.date() - dt.timedelta(days=int(clock.hour < 21))
    if end is not None and end > through:
        raise ValueError('Requested ETF date has not reached its completion window')
    target = latest_session(data_root=Path(data_root), through=end or through, refresh_calendar=False)
    if end is not None and target != end:
        raise ValueError('Explicit ETF date must be a saved open session')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    record = dict(status='running', as_of=str(target), started_at=clock.isoformat(),
                  config_sha256=sha(config), auto_trade=False, account_state_changed=False)

    def save():
        (output/'summary.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    try:
        folder = capture(date=target, settings=settings['data'], data_root=Path(data_root),
                         now=clock, connector=connector)
        bars, _, receipt = read_capture(folder, date=target, now=dt.datetime.now(SHANGHAI))
        actions, version = shared_actions(folder=folder, settings=settings['data'])
        master = json.loads((version/'summary.json').read_text(encoding='utf-8'))
        available = max(dt.datetime.fromisoformat(receipt['available_at']),
                        dt.datetime.fromisoformat(master['observed_at']))
        record.update(status='complete', capture=str(folder), actions_version=str(version),
                      available_at=available.isoformat(), capture_sha256=sha(folder/'summary.json'),
                      actions_sha256=sha(version/'actions.parquet'), quote_rows=bars.height,
                      action_rows=actions.height, source_requests=receipt['requests'],
                      scope='Input preparation only; no model fit, orders, account advancement or notification')
    except Exception as exc:
        record.update(status='unavailable', error_type=type(exc).__name__, error=str(exc))
    record['finished_at'] = dt.datetime.now(SHANGHAI).isoformat()
    save()
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--to', type=dt.date.fromisoformat)
    args = parser.parse_args()
    result = run(config=args.config, data_root=args.data_root, output=args.output, end=args.to)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
