"""Opt-in R5 input qualification and the existing N1/N3/N4 battery, isolated outputs."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import tomllib

import polars as pl

from quant.research import sue_preliminary_audit as audit
from quant.research.sue_preliminary_r5_inputs import (
    FAMILY, IDENTIFIER, PREFIX, sha, spec_at,
)
from quant.research.sue_preliminary_s4 import build_monthly_s4

CONFIG = Path('configs/research/sue_preliminary_s4_v1.toml')


def save(path, row):
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def qualify(*, config, data_root, refresh_config, output, known_at):
    spec = spec_at(config, known_at)
    result = audit.run(config=config, output=output, data_root=data_root, known_at=known_at)
    result.update(finite_signal_months=0, enqueued=False, completed_battery=False)
    if result['months_with_100_basis_verified_points'] < spec['minimum_months']:
        save(output/'qualification.json', result)
        return result
    from quant.data.financial_repository import TushareFinancialHistoryQuery, read_tushare_financial_history
    preliminary = pl.read_parquet(output/'observations.parquet')
    symbols = tuple(preliminary['symbol'].unique().sort())
    refresh = tomllib.loads(refresh_config.read_text(encoding='utf-8'))
    income_source = data_root/'clean/tushare_financials'/refresh['financial_snapshot']/'income.parquet'
    before = sha(income_source)
    income = read_tushare_financial_history(data_root=data_root, query=TushareFinancialHistoryQuery(
        snapshot_id=refresh['financial_snapshot'], dataset='income', start_period=dt.date(1900, 1, 1),
        end_period=spec['audit_end'], symbols=symbols))
    if sha(income_source) != before:
        raise ValueError('R5 income chain changed during qualification')
    dates = tuple(pl.read_parquet(output/'monthly_input_coverage.parquet')['signal_date'])
    panel = build_monthly_s4(income_history=income, preliminary_history=preliminary,
                            signal_dates=dates, candidate_symbols=symbols).factors
    panel.write_parquet(output/'qualified_monthly_values.parquet')
    months = panel.filter(pl.col('sue_prelim').is_finite()).group_by('trade_date').len().filter(
        pl.col('len') >= spec['minimum_symbols']).height
    result.update(status='QUALIFIED_INPUTS' if months >= spec['minimum_months'] else 'SAMPLE_INSUFFICIENT',
                  finite_signal_months=months)
    if months >= spec['minimum_months']:
        income.write_parquet(output/'income.parquet')
        files = [output/'income.parquet', output/'observations.parquet', output/'config.toml',
                 output/'qualified_monthly_values.parquet', Path(spec['battery_config']), income_source,
                 refresh_config, Path(__file__).with_name('sue_preliminary_s4.py')]
        files += [Path(row['path']) for row in result['inputs_sha256']]
        file_hashes={str(p.resolve()): sha(p) for p in files}
        if file_hashes[str(income_source.resolve())] != before:
            raise ValueError('R5 income chain changed before frozen publication')
        if any(sha(row['path']) != row['sha256'] for row in result['inputs_sha256']):
            raise ValueError('R5 qualification sources changed')
        result.update(observed_at=known_at.isoformat(), registered_at=spec['registered_at'],
            config=str((output/'config.toml').resolve()), config_sha256=sha(output/'config.toml'),
            source_data_root=str(data_root.resolve()), income=str((output/'income.parquet').resolve()),
            observations=str((output/'observations.parquet').resolve()),
            files=file_hashes)
    save(output/'qualification.json', result)
    return result


def isolated_inputs(source, target):
    """Share existing clean captures read-only by convention; publish only new factors."""
    target.mkdir(parents=True, exist_ok=False)
    clean = target/'clean'
    if os.name == 'nt':
        import _winapi
        _winapi.CreateJunction(str((source/'clean').resolve()), str(clean))
    else:
        clean.symlink_to((source/'clean').resolve(), target_is_directory=True)


def run(*, config=CONFIG, settings_config=Path('configs/research/nightly.toml'),
        data_root=Path('data'), output, execute=False):
    now = dt.datetime.now(dt.UTC)
    spec = spec_at(config, now)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    settings = tomllib.loads(settings_config.read_text(encoding='utf-8'))
    result = qualify(config=config, data_root=data_root, refresh_config=Path(settings['refresh_config']),
                     output=output/'N1_inputs', known_at=now)
    result = {**result, 'pipeline_output': str(output), 'battery_requested': execute}
    if result['status'] != 'QUALIFIED_INPUTS' or not execute:
        save(output/'summary.json', result)
        return result
    from quant.research import nightly_steps
    from quant.research.compute_allocation import apply
    receipt = output/'N1_inputs/qualification.json'
    private_data = output/'data'
    isolated_inputs(data_root, private_data)
    library = output/'reference_library'
    shutil.copytree(Path(settings['library']), library)
    queue = output/'queue'
    queue.mkdir()
    definition = dict(id=IDENTIFIER, expr=IDENTIFIER, family=FAMILY, direction=spec['direction'],
                      source_ref=PREFIX+sha(receipt)+':'+str(receipt))
    (queue/(IDENTIFIER+'.toml')).write_text(''.join(
        f'{k} = {json.dumps(v)}\n' for k, v in definition.items()), encoding='utf-8')
    settings.update(data_root=str(private_data), r5_reference_data_root=str(data_root.resolve()),
        r5_input_receipt=str(receipt), queue=str(queue), library=str(library),
        batch_root=str(output/'batches'), rejected_root=str(output/'rejected'),
        output_root=str(output/'nightly'), history_start=spec['audit_start'],
        as_of=dt.date.fromisoformat(str(result['signal_end'])),
        training_end=dt.date(now.year-1, 12, 31), battery_config=spec['battery_config'],
        prepare_month_inputs=False)
    settings = apply(settings)
    run_path = output/'run'
    for stage in ('N1', 'N3', 'N4'):
        (run_path/stage).mkdir(parents=True)
    # No N2 search, alternate battery, model refit or external cost-run reuse.
    result['stages'] = {}
    result['status'] = 'RUNNING_EXISTING_PIPELINE'
    save(output/'summary.json', result)
    try:
        for name, action in (('N1', nightly_steps.ingest), ('N3', nightly_steps.evaluate), ('N4', nightly_steps.admit)):
            value = action(settings, run_path)
            save(run_path/name/'result.json', value)
            result['stages'][name] = value
            if name == 'N1' and value['queued_candidates'] != 1:
                raise ValueError('R5 was not ingested by N1')
            if name == 'N3' and value['evaluated'] != 1:
                raise ValueError('R5 has no completed N3 battery')
            result['enqueued'] = True
            save(output/'summary.json', result)
    except Exception as exc:
        result.update(status='PIPELINE_INCOMPLETE', error=f'{type(exc).__name__}: {exc}')
        save(output/'summary.json', result)
        raise
    from quant.research.sue_preliminary_r5_inputs import diagnostics
    result.update(diagnostics(result['stages']['N3']['batch'], result['stages']['N4']['admission_scorecard']))
    result.update(enqueued=True, completed_battery=True, status='COMPLETED_EXISTING_PIPELINE',
                  registered=True, registry_reason='Existing N3 completed battery registered by nightly evaluate')
    save(output/'summary.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--settings-config', type=Path, default=Path('configs/research/nightly.toml'))
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    result = run(**vars(args))
    print(json.dumps({k: result[k] for k in ('status', 'finite_signal_months', 'enqueued', 'completed_battery')}))


if __name__ == '__main__':
    main()
