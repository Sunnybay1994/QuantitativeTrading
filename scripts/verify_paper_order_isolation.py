"""Reproduce the Oct-30 legacy shadow-universe failure using isolated real accounts."""
import argparse
import datetime as dt
import hashlib
import json
import tomllib
from pathlib import Path
from unittest.mock import patch

from quant.data.factor_battery_inputs import read_frozen_battery_universe
from quant.execution.paper_rehearsal import DEFAULT_CONFIG, run


def fingerprint(accounts):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for account in accounts for path in account.rglob('*')
            if path.is_file() and 'rehearsal' not in path.relative_to(account).parts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    settings = tomllib.loads(DEFAULT_CONFIG.read_text(encoding='utf-8'))
    accounts = [Path(settings[name]['output']) for name in ('q10', 'q10_shadow')]
    before = fingerprint(accounts)

    def legacy_reader(*, statistics, as_of_dates, include_tradeability=False, **kwargs):
        # Before the forward-universe repair, shadow construction read only this
        # frozen parquet. Keep its actual rows and original missing-date error.
        return read_frozen_battery_universe(statistics=statistics, as_of_dates=as_of_dates,
                                           include_tradeability=include_tradeability)

    with patch('quant.research.run_constrained_portfolio.read_battery_universe_dates', legacy_reader):
        replay = run(end=dt.date(2026, 10, 30))
    after = fingerprint(accounts)
    primary, shadow = replay['accounts']['q10'], replay['accounts']['q10_shadow']
    checks = {'production_files_unchanged': before == after,
              'primary_orders_generated': primary['status'] == 'complete'
                  and primary['result']['reference_orders'] > 0,
              'legacy_shadow_missing_date_reproduced': shadow['status'] == 'failed'
                  and 'Missing frozen universe trade dates' in shadow.get('error', '')
                  and '2026, 10, 30' in shadow.get('error', ''),
              'no_push': replay['pushed'] is False}
    result = {'checks': checks, 'replay': replay,
              'method': 'Real frozen forecast, prices and account snapshots; restore legacy frozen-only shadow reader in memory',
              'production_hashes_before': before, 'production_hashes_after': after}
    (args.output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (args.output/'report.md').write_text(
        '# K1 历史缺日隔离复现\n\n' + '\n'.join(f'- {k}: {v}' for k, v in checks.items())
        + f'\n\nQ10 订单：{primary.get("result", {}).get("reference_orders")} 笔。'
        + f'\n\n影子错误：{shadow.get("error")}\n'
        + '\n使用真实历史输入，在内存恢复旧版仅读冻结股票池的路径；不代表当前数据仍缺失。\n', encoding='utf-8')
    print(json.dumps({'checks': checks, 'output': str(args.output)}, ensure_ascii=False))
    raise SystemExit(0 if all(checks.values()) else 1)


if __name__ == '__main__':
    main()
