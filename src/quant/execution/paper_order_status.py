"""Read dated order evidence and alert on missing month-end orders."""
import argparse
import datetime as dt
import json
import tomllib
from dataclasses import asdict
from pathlib import Path

import polars as pl

from quant.data.refresh import SHANGHAI
from quant.data.stock_paper_inputs import read_stock_paper_calendar
from quant.execution.paper_rehearsal import DEFAULT_CONFIG


def _path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root/path


def collect(*, root: Path, today: dt.date, config: Path = DEFAULT_CONFIG) -> dict:
    settings = tomllib.loads(_path(root, config).read_text(encoding='utf-8'))
    sessions = sorted(read_stock_paper_calendar(_path(root, settings.get('data_root', 'data')))
                      .filter(pl.col('is_open'))['date'].unique().to_list())
    month_ends = [a for a, b in zip(sessions, sessions[1:]) if a.month != b.month]
    upcoming = next((day for day in month_ends if day >= today), None)
    accounts = {}
    for name in ('q10', 'q10_shadow'):
        if name not in settings:
            continue
        account = _path(root, settings[name]['output'])
        item = {'ready': False, 'orders': None, 'path': str(account/'latest_orders.md')}
        try:
            if upcoming is None:
                raise ValueError('Exchange calendar does not establish next month-end')
            summary = json.loads((account/'latest_summary.json').read_text(encoding='utf-8'))
            state = json.loads((account/str(upcoming)/'state.json').read_text(encoding='utf-8'))
            orders = pl.read_csv(account/'latest_orders.csv')
            snapshot = account/str(upcoming)/'orders.csv'
            if (summary.get('as_of') != str(upcoming) or state.get('date') != str(upcoming)
                    or summary.get('rehearsal') or state.get('rehearsal')
                    or summary.get('auto_trade') is not False
                    or not (account/'latest_orders.md').read_text(encoding='utf-8').strip()
                    or (account/'latest_orders.csv').read_bytes() != snapshot.read_bytes()
                    or orders.height != summary.get('reference_orders')
                    or (orders.height and orders['as_of'].unique().to_list() != [str(upcoming)])):
                raise ValueError('Latest orders lack matching dated production evidence')
            item.update(ready=True, orders=orders.height)
        except (OSError, ValueError, KeyError, pl.exceptions.PolarsError) as exc:
            item['reason'] = f'{type(exc).__name__}: {exc}'
        accounts[name] = item
    return {'next_rebalance': str(upcoming) if upcoming else None,
            'is_month_end': today in month_ends, 'accounts': accounts,
            'ready': bool(accounts) and all(row['ready'] for row in accounts.values())}


def watch(*, root: Path, now: dt.datetime | None = None, notify: bool = False,
          config: Path = DEFAULT_CONFIG) -> dict:
    clock = (now or dt.datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    result = collect(root=root, today=clock.date(), config=config)
    due = result['is_month_end'] and clock.time().replace(tzinfo=None) >= dt.time(22, 30)
    result.update(generated_at=clock.isoformat(), alert_due=due and not result['ready'])
    if result['alert_due'] and notify:
        from quant.notify import send
        missing = [name for name, row in result['accounts'].items() if not row['ready']]
        result['notifications'] = [asdict(row) for row in send(
            title=f'月末订单未就绪：{clock.date()}',
            body='22:30 缺少匹配当日正式状态的订单文件：' + '、'.join(missing))]
    folder = root/'artifacts/paper/order_watch'
    folder.mkdir(parents=True, exist_ok=True)
    (folder/f'{clock:%Y-%m-%d_%H%M%S_%f}.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--notify', action='store_true')
    args = parser.parse_args()
    from quant.core.paths import project_paths
    result = watch(root=project_paths().root, config=args.config, notify=args.notify)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(1 if result['alert_due'] else 0)


if __name__ == '__main__':
    main()
