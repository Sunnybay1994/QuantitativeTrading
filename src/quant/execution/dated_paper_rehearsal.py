"""One-attempt, isolated three-account rehearsal for the November 27 close."""
import argparse
import datetime as dt
import hashlib
import json
import re
import tomllib
from pathlib import Path

from quant.data.refresh import SHANGHAI
from quant.execution import account_30w_top15_paper as a2
from quant.execution import paper_rehearsal

TARGET = dt.date(2026, 11, 27)
ROOT = Path('artifacts/paper/dated_rehearsal')
NAMES = ('q10', 'q10_shadow', 'account_30w_top15')


def hashes(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*'))
            if p.is_file() and 'rehearsal' not in p.relative_to(root).parts}


def run(*, config=paper_rehearsal.DEFAULT_CONFIG, target=TARGET, root=ROOT,
        forecast=None):
    # No synthetic clock in the scheduled entry point; historical dates are useful
    # only to exercise this same code with saved inputs during development.
    clock = dt.datetime.now(SHANGHAI)
    receipt = dict(observed_at=clock.isoformat(), target=str(target), rehearsal=True,
                   auto_trade=False, pushed=False, status='running', accounts={})
    if target > clock.date() or target == clock.date() and clock.hour < 21:
        return dict(receipt, status='failed', error=
                    'Wait for the actual target close and ready inputs after 21:00')
    if Path(root).resolve() == ROOT.resolve() and (
            target != TARGET or clock.date() != TARGET):
        return dict(receipt, status='failed', error=
                    'Formal rehearsal requires the registered target on the actual target day')
    folder = Path(root) / 'rehearsal' / str(target)
    folder.mkdir(parents=True, exist_ok=False)  # Failed attempts require human action.
    accounts = {}
    before = {}
    try:
        settings = tomllib.loads(Path(config).read_text(encoding='utf-8'))
        if settings.get('auto_trade') is not False:
            raise ValueError('Require auto_trade=false')
        accounts = {name: Path(settings[name]['output']) for name in NAMES}
        before = {name: hashes(path) for name, path in accounts.items()}
        receipt['formal_before'] = before
        data_root = Path(settings.get('data_root', 'data'))
        paper_rehearsal.resolve_session(data_root=data_root, end=target, now=clock)
        model = tomllib.loads(Path(settings['q10']['config']).read_text(encoding='utf-8'))['model']
        candidates = [Path(forecast)] if forecast else sorted(
            Path(model['forecast_root']).glob('**/model/forecast'), reverse=True)
        selected = None
        for candidate in candidates:
            summary = json.loads((candidate / 'summary.json').read_text(encoding='utf-8'))
            if summary.get('as_of') == str(target) and summary.get('rehearsal') is False:
                selected = candidate
                break
        if selected is None:
            raise ValueError('Missing actual same-day frozen forecast')
        # Engines retain all original provenance and publication-time checks.
        receipt.update(forecast=str(selected.resolve()), forecast_hashes=hashes(selected))
        receipt['forecast_parent_summary_sha256'] = hashlib.sha256(
            (selected.parent / 'summary.json').read_bytes()).hexdigest()
        for name in ('q10', 'q10_shadow'):
            try:
                receipt['accounts'][name] = paper_rehearsal.rehearse_account(
                    account=accounts[name], config=Path(settings[name]['config']),
                    end=target, data_root=data_root, forecast=selected)
            except Exception as exc:
                receipt['accounts'][name] = dict(status='failed', error=str(exc))
        spec = settings['account_30w_top15']
        output = folder / 'a2'
        payload = Path(spec['config']).read_text(encoding='utf-8')
        payload, count = re.subn(r'(?m)^inception_date\s*=\s*\d{4}-\d{2}-\d{2}\s*$',
                                'inception_date = ' + str(target), payload)
        if count != 1:
            raise ValueError('Expected one A2 inception date')
        isolated_config = folder / 'a2.toml'
        isolated_config.write_text(payload, encoding='utf-8')
        try:
            result = a2.run(config_path=isolated_config, data_root=data_root, output=output,
                            end=target, forecast=selected, as_month_end=True)
            if result.get('as_of') != str(target) or result.get('rehearsal') is not True:
                raise ValueError('A2 did not produce the requested isolated observation')
            receipt['accounts']['account_30w_top15'] = dict(
                status='complete', output=str(output.resolve()), result=result)
        except Exception as exc:
            receipt['accounts']['account_30w_top15'] = dict(status='failed', error=str(exc),
                                                          output=str(output.resolve()))
        receipt['status'] = 'complete' if all(
            receipt['accounts'][name]['status'] == 'complete' for name in NAMES) else 'failed'
    except Exception as exc:
        receipt.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    finally:
        after = {name: hashes(path) for name, path in accounts.items()}
        receipt.update(formal_after=after, formal_unchanged=bool(before) and before == after)
        if not receipt['formal_unchanged']:
            receipt['status'] = 'failed'
        receipt['artifact_hashes'] = {
            name: hashes(Path(value['output'])) for name, value in receipt['accounts'].items()
            if value.get('output')}
        receipt['finished_at'] = dt.datetime.now(SHANGHAI).isoformat()
        (folder / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2),
                                           encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=paper_rehearsal.DEFAULT_CONFIG)
    args = parser.parse_args()
    result = run(config=args.config)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['status'] == 'complete' else 1)


if __name__ == '__main__':
    main()
