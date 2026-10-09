"""Extend monthly research data with dated corporate-action captures and new versions."""
from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
import time
import tomllib
from pathlib import Path
from typing import Any

import polars as pl

from quant.data.connectors.tushare import TushareConnector
from quant.data.equal_weight_index import load_return_benchmarks, publish, publish_etf_extension
from quant.data.factor_battery_inputs import read_battery_year
from quant.data.factor_benchmarks import capture_csi800
from quant.data.factor_panels import available_sessions
from quant.data.index_benchmarks import normalize_index
from quant.data.industry_history import refresh_daily as refresh_industry
from quant.data.refresh import latest_session
from quant.data.refresh_etf_prices import refresh as refresh_etfs
from quant.data.refresh_stocks import read_stock_data, refresh as refresh_stocks
from quant.data.stock_execution_inputs import restore_historical_instruments
from quant.data.stock_paper_inputs import capture_stock_paper_day
from quant.data.storage import RawStore
from quant.data.monthly_open_inputs import daily_open_facts, digest, extension_version, policy_of, validate_binding
from quant.data.stock_open_suspensions import POLICY


def _toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding='utf-8'))


def _toml_text(settings: dict) -> str:
    """The existing runtime has tomllib only; serialize the small configuration subset."""
    def value(item: Any) -> str:
        if isinstance(item, dt.date):
            return str(item)
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=False)
        if isinstance(item, bool):
            return str(item).lower()
        if isinstance(item, (int, float)):
            return str(item)
        if isinstance(item, list):
            return '['+', '.join(value(v) for v in item)+']'
        raise TypeError(f'Unsupported configuration value: {type(item).__name__}')
    lines: list[str] = []
    def section(mapping: dict, prefix: str = '') -> None:
        if prefix:
            lines.append(f'[{prefix}]')
        lines.extend(f'{key} = {value(item)}' for key, item in mapping.items() if not isinstance(item, dict))
        lines.append('')
        for key, item in mapping.items():
            if isinstance(item, dict):
                section(item, f'{prefix}.{key}' if prefix else key)
    section(settings)
    return '\n'.join(lines)


def _write_toml(path: Path, settings: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_toml_text(settings), encoding='utf-8')


def _execution_end(settings: dict, data_root: Path) -> dt.date:
    folder = data_root/'clean/stock_execution'/settings['execution_snapshot']
    if (folder/'coverage.json').is_file():
        return dt.date.fromisoformat(json.loads((folder/'coverage.json').read_text())['as_of'])
    # Legacy snapshots did not record their filtered ex-date end. A published
    # return index explicitly identifies both the execution source and its end.
    benchmark = _toml(Path(settings['return_benchmark_config']))['benchmarks']
    summary = json.loads((data_root/'clean/equal_weight_indexes'/benchmark['equal_weight_snapshot']/'summary.json').read_text())
    if summary['execution_snapshot'] != settings['execution_snapshot']:
        raise ValueError('Legacy execution snapshot has no verified corporate-action interval')
    return dt.date.fromisoformat(summary['end'])


def _mutable_capture_floor(folder: Path) -> dt.date:
    provenance = json.loads((folder/'sources.json').read_text(encoding='utf-8'))
    if isinstance(provenance, dict):
        return dt.date.fromisoformat(provenance['captured_through'])
    dates = []
    present = set()
    for raw in provenance:
        path = Path(raw)
        if path.parent.parent.name not in ('dividend', 'stock_basic'):
            continue
        meta = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        dates.append(dt.datetime.fromisoformat(meta['fetched_at']).date())
        present.add(path.parent.parent.name)
    if present != {'dividend', 'stock_basic'}:
        raise ValueError('Missing mutable execution raw provenance')
    return min(dates)


def _capture_day(root: Path, day: dt.date) -> Path:
    """Resume interrupted clean publication by retaining it and requesting a new raw version."""
    folder = root/'clean/stock_paper_inputs'/f'date={day}'
    expected = [*(f'{name}.parquet' for name in ('instruments','names','limits','suspensions','dividends')), 'sources.json']
    if folder.exists() and not all((folder/name).is_file() for name in expected):
        parent = (root/'clean/stock_paper_inputs').resolve()
        if folder.resolve().parent != parent:
            raise ValueError('Daily clean repair target escaped its parent')
        number = 1
        retained = parent/f'.{folder.name}-attempt-{number}'
        while retained.exists():
            number += 1
            retained = parent/f'.{folder.name}-attempt-{number}'
        folder.rename(retained)
    return capture_stock_paper_day(root, day)


def _publication_version(parent: Path, preferred: str, complete: str) -> str:
    """Keep interrupted new clean publications; retry under an unused version."""
    candidate, number = preferred, 1
    while (parent/candidate).exists() and not (parent/candidate/complete).is_file():
        number += 1
        candidate = f'{preferred}_attempt{number}'
    return candidate


def inspect_month_inputs(*, settings: dict, as_of: dt.date) -> dict[str, str]:
    """Report exact missing coverage; no network, mutation or inferred cutoff."""
    root = Path(settings.get('data_root', 'data'))
    calendar = available_sessions(root, as_of)
    if not calendar or calendar[-1] != as_of:
        raise ValueError('as_of must be an explicitly covered exchange session')
    missing: dict[str, str] = {}
    expected = {d for d in calendar if d.year == as_of.year}
    for table in ('bar_1d', 'daily_basic'):
        try:
            values = read_stock_data(data_root=root, config=Path(settings['refresh_config']), table=table,
                start=dt.date(as_of.year, 1, 1), end=as_of)
            if set(values['trade_date']) != expected:
                missing['stocks'] = f'{table} missing sessions through {as_of}'
        except (OSError, ValueError, pl.exceptions.PolarsError) as error:
            missing['stocks'] = str(error)
    battery = _toml(Path(settings['battery_config']))
    try:
        limits = pl.scan_parquet(str(root/'clean/factor_execution'/battery['data']['limits_snapshot']/'year=*/limits.parquet'))
        actual = set(limits.select('trade_date').unique().collect()['trade_date'])
        required = {d for d in calendar if battery['start'] <= d <= as_of}
        if not required <= actual:
            missing['factor_limits'] = f'Missing {len(required-actual)} factor-limit sessions'
    except (OSError, pl.exceptions.PolarsError) as error:
        missing['factor_limits'] = str(error)
    try:
        folder = root/'clean/stock_execution'/settings['execution_snapshot']
        if _execution_end(settings, root) < as_of or _mutable_capture_floor(folder) < as_of:
            missing['execution'] = f'Corporate actions/instruments not captured through {as_of}'
        for name in ('instruments', 'limits', 'suspensions', 'dividends'):
            if not (folder/f'{name}.parquet').is_file():
                missing['execution'] = f'Missing execution {name}'
        bands = pl.read_parquet(folder/'limits.parquet')
        order_dates = {b for a, b in zip(calendar, calendar[1:])
                       if a >= battery['start'] and (a.year, a.month) != (b.year, b.month)}
        if not order_dates <= set(bands['trade_date']):
            missing['execution'] = 'Missing monthly execution price-band sessions'
        if bands.select('symbol', 'trade_date').is_duplicated().any():
            missing['execution'] = 'Duplicate monthly execution price bands'
        instruments = pl.read_parquet(folder/'instruments.parquet')
        latest = read_stock_data(data_root=root, config=Path(settings['refresh_config']), table='bar_1d', start=as_of, end=as_of)
        if set(latest['symbol'])-set(instruments['symbol']):
            missing['execution'] = 'Execution instrument master misses current stock symbols'
    except (OSError, ValueError, KeyError, pl.exceptions.PolarsError) as error:
        missing['execution'] = str(error)
    try:
        validate_binding(settings, root)
        load_return_benchmarks(config=Path(settings['return_benchmark_config']), data_root=root,
            start=dt.date(2015, 1, 5), end=as_of)
    except (OSError, ValueError, pl.exceptions.PolarsError) as error:
        missing['returns'] = str(error)
    try:
        measure = _toml(Path(settings['measurement_config']))
        frame = pl.scan_parquet(root/'clean/index_benchmarks'/measure['index_version']/'data.parquet').collect()
        for code in measure['index_codes']:
            if set(frame.filter((pl.col('index_code') == code) & pl.col('trade_date').is_in(sorted(expected)))['trade_date']) != expected:
                missing['official_indexes'] = f'Missing official index sessions: {code}'
    except (OSError, KeyError, pl.exceptions.PolarsError) as error:
        missing['official_indexes'] = str(error)
    return missing


def _daily_extensions(settings: dict, as_of: dt.date, output: Path, version: str) -> dict:
    root = Path(settings.get('data_root', 'data'))
    original = root/'clean/stock_execution'/settings['execution_snapshot']
    target = root/'clean/stock_execution'/version
    limit_target = root/'clean/factor_execution'/version
    if target.exists() or limit_target.exists():
        raise ValueError('Execution extension target already exists; frozen inputs cannot be overwritten')
    old_end = _execution_end(settings, root)
    sessions = available_sessions(root, as_of)
    # Per-ex-date captures use fresh stock_basic requests and dated dividend
    # requests, never the mutable historical ts_code-only dividend cache.
    low = min(old_end+dt.timedelta(days=1), as_of.replace(day=1))
    dates = [d for d in sessions if low <= d <= as_of]
    daily = [_capture_day(root, day) for day in dates]
    if not daily:
        raise ValueError('No completed sessions for execution extension')
    for day, path in zip(dates, daily, strict=True):
        provenance = json.loads((path/'sources.json').read_text(encoding='utf-8'))
        if provenance['as_of'] != str(day):
            raise ValueError('Wrong-date daily corporate-action capture')
        kinds = set()
        for raw in provenance['raw']:
            raw_path = Path(raw)
            if raw_path.parent.parent.name in ('dividend', 'stock_basic'):
                meta = json.loads(raw_path.with_suffix('.json').read_text(encoding='utf-8'))
                if dt.datetime.fromisoformat(meta['fetched_at']).date() < day:
                    raise ValueError('Mutable daily facts came from an older request version')
                kinds.add(raw_path.parent.parent.name)
        if kinds != {'dividend', 'stock_basic'}:
            raise ValueError('Daily capture lacks fresh dividend or stock_basic provenance')
    target.mkdir(parents=True, exist_ok=False)
    opening = policy_of(original) == POLICY
    open_facts, open_receipts = [], []
    source_hashes = {}
    if opening:
        source_paths = [p for p in original.glob('*') if p.is_file()]
        for day, path in zip(dates, daily, strict=True):
            source_paths.extend(p for p in path.glob('*') if p.is_file())
            provenance = json.loads((path/'sources.json').read_text(encoding='utf-8'))
            for name in provenance['raw']:
                raw = Path(name)
                if raw.parent.parent.name in ('dividend', 'stock_basic'):
                    meta = raw.with_suffix('.json')
                    if digest(raw) != json.loads(meta.read_text(encoding='utf-8'))['checksum_sha256']:
                        raise ValueError('Mutable monthly execution receipt checksum differs')
                    source_paths.extend([raw, meta])
            bars = read_stock_data(data_root=root, config=Path(settings['refresh_config']),
                table='bar_1d', start=day, end=day).select('symbol', 'trade_date', 'volume')
            facts, receipt = daily_open_facts(path, day, bars)
            open_facts.append(facts)
            open_receipts.append(receipt)
        source_hashes = {str(p): digest(p) for p in sorted(set(source_paths))}
        for receipt in open_receipts:
            source_hashes.update(receipt['raw_hashes'])
    for name, key in [('limits', 'trade_date'), ('suspensions', 'trade_date'), ('dividends', 'ex_date')]:
        old = pl.read_parquet(original/f'{name}.parquet').filter(~pl.col(key).is_in(dates))
        extras = [pl.read_parquet(path/f'{name}.parquet').filter(
            pl.col('symbol').str.contains(r'^[0-9]{6}\.(SH|SZ)$')) for path in daily]
        if name == 'suspensions' and opening:
            extras = [frame.filter(pl.col('open_status') != 'clear_at_open') for frame in open_facts]
        if name == 'dividends':
            extras = [frame.with_columns(pl.lit(True).alias('adjust_share_price')) for frame in extras]
        combined = pl.concat([old, *extras], how='vertical_relaxed' if name == 'suspensions' and opening else 'diagonal_relaxed')
        if combined.select('symbol', key).is_duplicated().any():
            raise ValueError(f'Duplicate extended {name}')
        combined.write_parquet(target/f'{name}.parquet')
    if opening:
        old_facts = pl.read_parquet(original/'suspension_open_facts.parquet').filter(~pl.col('trade_date').is_in(dates))
        pl.concat([old_facts, *open_facts], how='vertical_relaxed').write_parquet(target/'suspension_open_facts.parquet')
        (target/'suspension_receipts.json').write_text(json.dumps(open_receipts, indent=2), encoding='utf-8')
        policy_of(target)
    instruments = restore_historical_instruments(pl.read_parquet(daily[-1]/'instruments.parquet'))
    old_instruments = pl.read_parquet(original/'instruments.parquet')
    instruments = pl.concat([old_instruments.join(instruments.select('symbol'), on='symbol', how='anti'), instruments], how='vertical_relaxed')
    instruments.write_parquet(target/'instruments.parquet')
    (target/'sources.json').write_text(json.dumps({'previous': str(original), 'daily': [str(p) for p in daily],
        'captured_through': str(as_of)}, indent=2), encoding='utf-8')
    coverage = {'as_of': str(as_of), 'start': str(settings.get('history_start', '2010-01-01'))}
    if opening:
        coverage.update(suspension_policy=POLICY, previous_snapshot=original.name,
            corporate_action_dates=[str(d) for d in dates], instrument_capture=str(daily[-1]),
            dated_mutable_receipts_verified=True)
        if any(digest(Path(name)) != expected for name, expected in source_hashes.items()):
            raise ValueError('Execution extension sources changed')
        (target/'source_manifest.json').write_text(json.dumps(source_hashes, indent=2), encoding='utf-8')
    (target/'coverage.json').write_text(json.dumps(coverage), encoding='utf-8')
    battery = _toml(Path(settings['battery_config']))
    old_limits = root/'clean/factor_execution'/battery['data']['limits_snapshot']
    old_years = {int(p.name[5:]): p for p in old_limits.glob('year=*')}
    for year in range(battery['start'].year, as_of.year+1):
        frames = [pl.read_parquet(old_years[year]/'limits.parquet')] if year in old_years else []
        existing = set(frames[0]['trade_date']) if frames else set()
        for day in (d for d in sessions if d.year == year and d >= battery['start'] and d not in existing):
            captured = _capture_day(root, day)
            frames.append(pl.read_parquet(captured/'limits.parquet').filter(
                pl.col('symbol').str.contains(r'^[0-9]{6}\.(SH|SZ)$')))
        merged = pl.concat(frames, how='vertical_relaxed')
        year_folder = limit_target/f'year={year}'
        year_folder.mkdir(parents=True, exist_ok=True)
        merged.write_parquet(year_folder/'limits.parquet')
    battery['data']['limits_snapshot'] = version
    _write_toml(output/'battery.toml', battery)
    return {**settings, 'execution_snapshot': version, 'battery_config': str(output/'battery.toml')}


def _extend_official(settings: dict, as_of: dt.date, output: Path, version: str) -> dict:
    root = Path(settings.get('data_root', 'data'))
    measurement = _toml(Path(settings['measurement_config']))
    old_folder = root/'clean/index_benchmarks'/measurement['index_version']
    old = pl.read_parquet(old_folder/'data.parquet')
    summary = json.loads((old_folder/'summary.json').read_text(encoding='utf-8'))
    client = TushareConnector(config_path=Path('configs/tushare.local.toml'))
    store = RawStore(root/'raw')
    frames = []
    for spec in summary['series']:
        frame = old.filter(pl.col('index_code') == spec['index_code']).sort('trade_date')
        anchor = frame['trade_date'][-1]
        if anchor < as_of:
            raw_path = output/f"index_{spec['index_code'].replace('.', '_')}.json"
            if raw_path.is_file():
                raw = pl.read_parquet(json.loads(raw_path.read_text())['raw'])
            else:
                params = {'ts_code': spec['index_code'], 'start_date': anchor.strftime('%Y%m%d'), 'end_date': as_of.strftime('%Y%m%d')}
                raw = client.query_raw('index_daily', **params)
                saved = store.write(source='tushare', table='index_daily', frame=raw, parameters=params)
                raw_path.write_text(json.dumps({'raw': str(saved.data_path)}), encoding='utf-8')
                time.sleep(1.05)
            dates = [d for d in available_sessions(root, as_of) if anchor <= d <= as_of]
            addition = normalize_index(raw, spec=spec, sessions=dates, start=anchor+dt.timedelta(days=1))
            if abs(addition['previous_level'][0]-frame['index_level'][-1]) > .00011:
                raise ValueError('Official index extension seam changed')
            frame = pl.concat([frame, addition])
        frames.append(frame)
    target = root/'clean/index_benchmarks'/version
    target.mkdir(parents=True, exist_ok=True)
    pl.concat(frames).write_parquet(target/'data.parquet')
    summary.update(version=version, end=str(as_of))
    (target/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    measurement['index_version'] = version
    _write_toml(output/'measurement.toml', measurement)
    return {**settings, 'measurement_config': str(output/'measurement.toml')}


def _extend_returns(settings: dict, as_of: dt.date, output: Path, version: str) -> dict:
    root = Path(settings.get('data_root', 'data'))
    references = _toml(Path(settings['return_benchmark_config']))
    benchmark = references['benchmarks']
    battery = _toml(Path(settings['battery_config']))
    old_members = pl.read_parquet(root/'clean/factor_benchmarks'/battery['data']['csi800_snapshot']/'members.parquet')
    members_end = old_members['snapshot_date'].max()
    if not isinstance(members_end, dt.date):
        raise ValueError('Empty historical CSI800 memberships')
    if members_end < as_of.replace(day=1):
        delta = _publication_version(root/'clean/factor_benchmarks', version+'_members_delta', 'summary.json')
        delta_folder = root/'clean/factor_benchmarks'/delta
        if not (delta_folder/'summary.json').is_file():
            capture_csi800(data_root=root, name=delta, start=members_end+dt.timedelta(days=1), end=as_of)
        members = pl.concat([old_members, pl.read_parquet(delta_folder/'members.parquet')]).unique(['snapshot_date', 'symbol'])
        member_folder = root/'clean/factor_benchmarks'/version
        member_folder.mkdir(parents=True, exist_ok=True)
        members.write_parquet(member_folder/'members.parquet')
        battery['data']['csi800_snapshot'] = version
    stats = output/'benchmark_statistics'
    stats.mkdir(parents=True, exist_ok=True)
    original_stats = Path(settings.get('reference_statistics', settings['statistics'][0]))
    previous_battery = _toml(original_stats/'battery.toml')
    # Base battery configs have no run metadata until an evaluation is prepared.
    battery.setdefault('run', {})['as_of'] = as_of
    _write_toml(stats/'battery.toml', battery)
    for year in range(battery['start'].year, as_of.year+1):
        dest = stats/f'inputs/{year}'
        dest.mkdir(parents=True, exist_ok=True)
        if (dest/'universe.parquet').exists():
            continue
        if year < previous_battery['run']['as_of'].year:
            shutil.copy2(original_stats/f'inputs/{year}/universe.parquet', dest/'universe.parquet')
        else:
            universe, _ = read_battery_year(data_root=root, refresh_config=Path(settings['refresh_config']),
                limits_snapshot=battery['data']['limits_snapshot'], start=max(battery['start'], dt.date(year,1,1)),
                end=min(as_of, dt.date(year,12,31)), known_through=as_of)
            universe.write_parquet(dest/'universe.parquet')
    index_version = _publication_version(root/'clean/equal_weight_indexes', version, 'summary.json')
    index_folder = root/'clean/equal_weight_indexes'/index_version
    if not (index_folder/'summary.json').is_file():
        old_summary = json.loads((root/'clean/equal_weight_indexes'/benchmark['equal_weight_snapshot']/'summary.json').read_text())
        index_settings = {**_toml(Path(settings['refresh_config'])), 'version': index_version,
            'statistics': str(stats), 'execution_snapshot': settings['execution_snapshot'], 'end': as_of,
            'rules': old_summary['rules']}
        _write_toml(output/'equal_weight_indexes.toml', index_settings)
        publish(config=output/'equal_weight_indexes.toml', data_root=root)
    etf_folder = root/'clean/factor_benchmarks'/version
    if not (etf_folder/'prices.parquet').is_file():
        refresh_settings = _toml(Path(settings['refresh_config']))
        refresh_etfs(end=as_of, data_root=root, artifact_root=output, config=Path(refresh_settings['etf_config']))
        # CSI membership and ETF prices share this new version directory, but
        # the ETF publisher intentionally requires an unused target directory.
        etf_version = _publication_version(root/'clean/factor_benchmarks', version+'_etf', 'summary.json')
        if not (root/'clean/factor_benchmarks'/etf_version/'prices.parquet').is_file():
            publish_etf_extension(data_root=root, previous=benchmark['etf_total_return_snapshot'], version=etf_version, end=as_of)
        benchmark['etf_total_return_snapshot'] = etf_version
    benchmark['equal_weight_snapshot'] = index_version
    _write_toml(output/'return_benchmarks.toml', references)
    battery['data']['etf_total_return_snapshot'] = benchmark['etf_total_return_snapshot']
    _write_toml(output/'battery.toml', battery)
    return {**settings, 'battery_config': str(output/'battery.toml'), 'return_benchmark_config': str(output/'return_benchmarks.toml')}


def _bind_price_delay_index(settings: dict, output: Path) -> dict:
    """Bind opt-in monthly factors to this run's verified official-index version."""
    refresh = _toml(Path(settings['refresh_config']))
    keys = [key for key in ('price_delay_index_version', 'statement_event_index_version') if key in refresh]
    if not keys:
        return settings
    version = _toml(Path(settings['measurement_config']))['index_version']
    if all(refresh[key] == version for key in keys):
        return settings
    for key in keys:
        refresh[key] = version
    path = output/'refresh_price_delay.toml'
    _write_toml(path, refresh)
    return {**settings, 'refresh_config': str(path)}


def ensure_nightly_month_inputs(*, settings: dict, as_of: dt.date, output: Path) -> dict:
    """Prepare full SH/SZ monthly inputs; resume same cutoff, or fail explicitly."""
    current = copy.deepcopy(settings)
    root = Path(current.get('data_root', 'data'))
    output.mkdir(parents=True, exist_ok=True)
    request = output/'request.json'
    identity = {key: str(current[key]) for key in ('execution_snapshot', 'battery_config',
        'return_benchmark_config', 'measurement_config')}
    if request.exists():
        previous_request = json.loads(request.read_text())
        if previous_request['as_of'] != str(as_of):
            raise ValueError('Monthly input checkpoint belongs to another as_of')
        if 'sources' in previous_request and previous_request['sources'] != identity:
            raise ValueError('Monthly input checkpoint belongs to another source/policy')
        if 'sources' not in previous_request:
            original = root/'clean/stock_execution'/current['execution_snapshot']
            if original.exists() and policy_of(original) == POLICY:
                raise ValueError('Legacy checkpoint cannot be reused for opening-policy inputs')
    else:
        request.write_text(json.dumps({'as_of': str(as_of), 'sources': identity}), encoding='utf-8')
    saved = output/'settings.json'
    if saved.exists():
        current.update(json.loads(saved.read_text(encoding='utf-8')))
    if latest_session(data_root=root, through=as_of) != as_of:
        raise ValueError('Monthly as_of is not a completed exchange session')
    missing = inspect_month_inputs(settings=current, as_of=as_of)
    if not missing:
        current = _bind_price_delay_index(current, output)
        saved.write_text(json.dumps({k: current[k] for k in ('execution_snapshot','battery_config','refresh_config','return_benchmark_config','measurement_config')}, indent=2), encoding='utf-8')
        (output/'coverage.json').write_text(json.dumps({'as_of': str(as_of), 'missing': {}, 'network_required': False}), encoding='utf-8')
        return current
    version = extension_version(current, as_of)
    # Interrupted publications remain intact; a new attempt gets a new directory.
    while (root/'clean/stock_execution'/version).exists() or (root/'clean/factor_execution'/version).exists():
        version += '_retry'
    refresh_stocks(end=as_of, data_root=root, artifact_root=output, config=Path(current['refresh_config']))
    if any(key in missing for key in ('execution', 'factor_limits')):
        current = _daily_extensions(current, as_of, output, version)
        refresh_industry(data_root=root, end=as_of)
        saved.write_text(json.dumps({k: current[k] for k in ('execution_snapshot','battery_config','refresh_config','return_benchmark_config','measurement_config')}, indent=2), encoding='utf-8')
        if policy_of(root/'clean/stock_execution'/current['execution_snapshot']) == POLICY:
            # The former compatibility proof identifies the former execution
            # snapshot. Publish an explicitly bound index for this extension.
            missing['returns'] = 'Opening-policy execution source changed'
    if 'returns' in missing:
        current = _extend_returns(current, as_of, output, version)
    if 'official_indexes' in missing:
        current = _extend_official(current, as_of, output, version)
    current = _bind_price_delay_index(current, output)
    paths = {k: current[k] for k in ('execution_snapshot','battery_config','refresh_config','return_benchmark_config','measurement_config')}
    saved.write_text(json.dumps(paths, indent=2), encoding='utf-8')
    remaining = inspect_month_inputs(settings=current, as_of=as_of)
    if remaining:
        raise ValueError(f'Monthly inputs incomplete through {as_of}: {remaining}')
    (output/'coverage.json').write_text(json.dumps({'as_of': str(as_of), 'missing': {}, 'network_required': True}), encoding='utf-8')
    return current
