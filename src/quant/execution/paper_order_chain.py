"""Advance paper accounts independently from auxiliary research and reporting."""
import argparse
import datetime as dt
import json
import tomllib
from dataclasses import asdict
from pathlib import Path

from quant.data.refresh import SHANGHAI
from quant.execution.paper_rehearsal import DEFAULT_CONFIG
from quant.execution.q10_paper import run as run_q10


def run(*, config: Path = DEFAULT_CONFIG, end: dt.date,
        output: Path, forecast: Path | None = None, notify: bool = False) -> dict:
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    if settings.get('auto_trade') is not False:
        raise ValueError('Order chain requires auto_trade=false')
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'as_of': str(end), 'auto_trade': False,
               'recorded_at': dt.datetime.now(SHANGHAI).isoformat(), 'accounts': {}}

    def save() -> None:
        (output/'summary.json').write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    for name in ('q10', 'q10_shadow'):
        spec = settings.get(name)
        if not spec:
            continue
        account = Path(spec['output'])
        try:
            result = run_q10(config_path=Path(spec['config']),
                data_root=Path(settings.get('data_root', 'data')),
                output=account, end=end, forecast=forecast)
            if result['as_of'] != str(end):
                raise ValueError('Account snapshot does not match order date')
            item = {'status': 'complete', 'result': result}
        except Exception as exc:
            item = {'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'}
        receipt['accounts'][name] = item
        save()  # Preserve Q10 evidence even if the shadow account fails.
        if notify:
            try:
                from quant.notify import send
                if item['status'] == 'failed':
                    body = item['error']
                elif not result['reference_orders']:
                    continue
                else:
                    body = (account/'latest_orders.md').read_text(encoding='utf-8')
                item['notification'] = [asdict(row) for row in send(
                    title=f'{name} {end} 参考订单' if item['status'] == 'complete'
                    else f'{name} {end} 订单链异常', body=body)]
            except Exception as exc:
                item['notification_error'] = f'{type(exc).__name__}: {exc}'
            save()
    receipt['status'] = 'complete' if receipt['accounts'] and all(
        r['status'] == 'complete' for r in receipt['accounts'].values()) else 'failed'
    save()
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--to', type=dt.date.fromisoformat,
                        default=dt.datetime.now(SHANGHAI).date())
    parser.add_argument('--forecast', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--notify', action='store_true')
    args = parser.parse_args()
    output = args.output or Path('artifacts/paper/order_chain')/dt.datetime.now(
        SHANGHAI).strftime('%Y-%m-%d_%H%M%S_%f')
    result = run(config=args.config, end=args.to, output=output,
                 forecast=args.forecast, notify=args.notify)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['status'] == 'complete' else 1)


if __name__ == '__main__':
    main()
