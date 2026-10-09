"""Freeze existing PEAD execution facts without collecting or changing source data."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl
import pyarrow.parquet as pq

from quant.domain import Bar1dSchema, InstrumentSchema, TradeCalendarSchema


BAR_COLUMNS = ['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'adj_factor', 'source']
ALIAS_URL = 'https://static.cninfo.com.cn/finalpage/2019-12-16/1207164397.PDF'
ALIAS_DATE = dt.date(2019, 12, 16)
EMPTY_SUSPENSIONS = {'symbol': pl.String, 'trade_date': pl.Date, 'suspension_scope': pl.String,
                     'suspension_detail': pl.String, 'source_metadata': pl.String}


def _sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def _json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding='utf-8')


def _verify(paths: dict[str, str]):
    for path, expected in paths.items():
        if _sha(Path(path)) != expected:
            raise ValueError('Frozen source changed: '+path)


def verify_frozen_inputs(*, output: Path) -> dict:
    """Validate local frozen files and parent-stage identities, without rescanning raw."""
    target = output/'inputs'
    manifest = _json(target/'manifest.json')
    for name, expected in manifest['files'].items():
        path = target/name
        if not path.resolve().is_relative_to(target.resolve()) or _sha(path) != expected:
            raise ValueError('Frozen account input changed: '+name)
    market, identity = _json(target/'market_manifest.json'), _json(target/'eligibility_identity.json')
    if (market['financial_manifest_sha256'] != _sha(target/'financial_manifest.json')
            or identity['market_manifest_sha256'] != _sha(target/'market_manifest.json')
            or identity['events_sha256'] != manifest['financial_events_sha256']
            or _json(target/'eligibility_manifest.json')['events_sha256'] != _sha(target/'eligibility_events.parquet')):
        raise ValueError('Frozen parent-stage identity mismatch')
    return manifest


def _resolve_market_bars(sources: list[Path], *, start: dt.date, end: dt.date,
                         symbols: set[str]) -> pl.DataFrame:
    """Preserve the financial-market freeze's history-then-increment precedence."""
    frames = [pl.scan_parquet(path).select(BAR_COLUMNS).filter(
        pl.col('trade_date').is_between(start, end) & pl.col('symbol').is_in(sorted(symbols)))
        .with_columns(pl.lit(index).alias('_priority')) for index, path in enumerate(sources)]
    frame = pl.concat(frames, how='vertical_relaxed').collect()
    if frame.select('symbol', 'trade_date', '_priority').is_duplicated().any():
        raise ValueError('Duplicate daily keys inside a market source')
    frame = frame.sort('_priority').unique(['symbol', 'trade_date'], keep='last').drop('_priority')
    return Bar1dSchema.validate(frame).sort('trade_date', 'symbol')


def fill_same_entity_limits(*, bars: pl.DataFrame, limits: pl.DataFrame,
                            evidence: list[dict]) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Only fill missing canonical bands before the verified unchanged-share code switch."""
    if not any(row.get('url') == ALIAS_URL and '000043' in row.get('finding', '')
               and '001914' in row.get('finding', '') for row in evidence):
        raise ValueError('Missing official same-entity code-change evidence')
    keys = ['symbol', 'trade_date']
    new = bars.filter((pl.col('symbol') == '001914.SZ') & (pl.col('trade_date') < ALIAS_DATE))
    missing = new.join(limits.select(keys), on=keys, how='anti').select(
        *keys, pl.col('close').alias('canonical_close'), pl.col('amount').alias('canonical_amount'))
    old = bars.filter(pl.col('symbol') == '000043.SZ').select(
        'trade_date', pl.col('close').alias('historical_close'), pl.col('amount').alias('historical_amount'))
    old_limits = limits.filter(pl.col('symbol') == '000043.SZ').drop('symbol')
    mappings = missing.join(old, on='trade_date', how='left').join(old_limits, on='trade_date', how='left')
    valid = ((pl.col('canonical_close') == pl.col('historical_close'))
             & (pl.col('canonical_amount') == pl.col('historical_amount'))
             & pl.col('up_limit').is_finite() & pl.col('down_limit').is_finite()
             & (pl.col('up_limit') > 0) & (pl.col('down_limit') > 0)).fill_null(False)
    mappings = mappings.with_columns(valid.alias('applied'), pl.lit('000043.SZ').alias('source_symbol'),
        pl.lit(ALIAS_URL).alias('official_source'),
        pl.when(valid).then(pl.lit('same_day_close_amount_equal'))
        .otherwise(pl.lit('missing_or_unequal_daily_evidence')).alias('reason'))
    additions = mappings.filter(pl.col('applied')).select(limits.columns)
    return pl.concat([limits, additions]), mappings


def _usable_daily_bands(limits: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    if limits.select('symbol', 'trade_date').is_duplicated().any():
        raise ValueError('Duplicate daily price bands')
    valid = (pl.all_horizontal(pl.col('up_limit', 'down_limit').is_not_null()
        & pl.col('up_limit', 'down_limit').is_finite() & (pl.col('up_limit', 'down_limit') > 0))
        & (pl.col('up_limit') >= pl.col('down_limit'))).fill_null(False)
    return limits.filter(valid), limits.filter(~valid)


def _account_dividends(frame: pl.DataFrame, *, symbols: set[str], start: dt.date, end: dt.date):
    # Record-date rights can remain payable or restricted after the terminal session.
    return frame.filter(pl.col('symbol').is_in(sorted(symbols))
                        & (pl.col('ex_date') >= start) & (pl.col('record_date') <= end))


def read_suspensions(*, data_root: Path, sessions: list[dt.date], symbols: set[str]):
    """Read immutable raw requests; absence is not a negative suspension observation."""
    roots = [data_root/'raw/tushare/suspend_d', data_root/'raw/m3_g1/tushare/suspend_d']
    paths = sorted([*roots[0].glob('date=*/*.json'), *roots[1].glob('request=*/metadata.json')])
    covered: dict[dt.date, list[str]] = {}
    details, requests, individual, checksums = [], [], [], {}
    for metadata in paths:
        row = _json(metadata)
        params = row.get('parameters', {})
        if row.get('table') != 'suspend_d' or row.get('source') != 'tushare':
            raise ValueError('Unexpected suspension source: '+str(metadata))
        raw = metadata.parent/'data.parquet' if metadata.name == 'metadata.json' else metadata.with_suffix('.parquet')
        meta_sha, raw_sha = _sha(metadata), _sha(raw)
        if raw_sha != row.get('checksum_sha256'):
            raise ValueError('Suspension raw checksum mismatch: '+str(raw))
        table = pl.read_parquet(raw)
        if table.height != row.get('rows') or table.columns != row.get('columns'):
            raise ValueError('Suspension raw row/column receipt mismatch: '+str(raw))
        checksums.update({str(metadata): meta_sha, str(raw): raw_sha})
        if not {'ts_code', 'trade_date', 'suspend_timing', 'suspend_type'}.issubset(table.columns):
            raise ValueError('Incomplete suspension raw schema: '+str(raw))
        def date(value):
            return dt.datetime.strptime(value, '%Y%m%d').date()
        if params.get('trade_date'):
            first = last = date(params['trade_date'])
        elif params.get('start_date') and params.get('end_date'):
            first, last = date(params['start_date']), date(params['end_date'])
        else:
            raise ValueError('Unbounded suspension request: '+str(metadata))
        if first > last or (table.height and table.filter(
                ~pl.col('suspend_type').is_in(['S', 'R']) | pl.col('suspend_type').is_null()).height):
            raise ValueError('Invalid suspension request dates/type: '+str(metadata))
        # Tushare suspend_d caps one request at 5000 rows; a capped reply cannot prove completeness.
        complete = table.height < 5000 and params.get('suspend_type', 'S') == 'S'
        known_keys = {'trade_date', 'start_date', 'end_date', 'fields', 'suspend_type', 'ts_code'}
        complete = complete and set(params).issubset(known_keys)
        scope = 'symbol' if params.get('ts_code') else 'all_market'
        requests.append({'metadata': str(metadata), 'start': first, 'end': last, 'scope': scope,
            'symbol': params.get('ts_code'), 'rows': table.height, 'coverage_complete': complete,
            'reason': 'verified_uncapped_request' if complete else 'capped_or_unsupported_request'})
        relevant = [day for day in sessions if first <= day <= last]
        if complete and scope == 'all_market':
            for day in relevant:
                covered.setdefault(day, []).append(str(metadata))
        elif complete and params.get('ts_code') in symbols:
            individual.append({'symbol': params['ts_code'], 'start': first, 'end': last,
                               'source_metadata': str(metadata)})
        if not table.height:
            continue
        parsed = table.with_columns(pl.col('trade_date').str.strptime(pl.Date, '%Y%m%d'))
        if parsed.filter(~pl.col('trade_date').is_between(first, last)).height:
            raise ValueError('Suspension row outside requested date window')
        if params.get('ts_code') and parsed.filter(pl.col('ts_code') != params['ts_code']).height:
            raise ValueError('Suspension row outside requested security')
        stopped = parsed.filter((pl.col('suspend_type') == 'S') & pl.col('ts_code').is_in(sorted(symbols))
            & pl.col('trade_date').is_in(sessions))
        if stopped.height:
            if stopped.filter(pl.col('suspend_timing').is_not_null()
                              & (pl.col('suspend_timing').str.strip_chars().str.len_chars() == 0)).height:
                raise ValueError('Empty suspension timing is not a known full-day halt')
            details.append(stopped.select(pl.col('ts_code').alias('symbol'), 'trade_date',
                pl.when(pl.col('suspend_timing').is_null()).then(pl.lit('FULL_DAY'))
                .otherwise(pl.lit('PARTIAL')).alias('suspension_scope'),
                pl.col('suspend_timing').alias('suspension_detail'), pl.lit(str(metadata)).alias('source_metadata')))
    detail = pl.concat(details, how='vertical_relaxed').unique() if details else pl.DataFrame(schema=EMPTY_SUSPENSIONS)
    coverage = pl.DataFrame({'trade_date': sessions, 'coverage_complete': [day in covered for day in sessions],
        'request_count': [len(covered.get(day, [])) for day in sessions],
        'reason': ['verified_uncapped_all_market_request' if day in covered else 'no_complete_all_market_request'
                   for day in sessions]})
    return detail, coverage, individual, requests, checksums


def freeze_account_inputs(*, source: Path, output: Path, data_root: Path, start: dt.date, end: dt.date,
                          share_exchange_config: Path) -> dict:
    """Write a new inputs directory; the caller may already have frozen its account config."""
    if start > end:
        raise ValueError('Invalid account window')
    target = output/'inputs'
    if target.exists():
        raise FileExistsError(target)
    financial = _json(source/'inputs/manifest.json')
    market = _json(source/'market_inputs/manifest.json')
    eligibility = _json(source/'eligibility/summary.json')
    identity = _json(source/'eligibility/input_identity.json')
    if (market['financial_manifest_sha256'] != _sha(source/'inputs/manifest.json')
            or identity['market_manifest_sha256'] != _sha(source/'market_inputs/manifest.json')
            or identity['events_sha256'] != _sha(source/'events.parquet')):
        raise ValueError('PEAD source stage identity mismatch')
    expected = {str(source/'inputs'/name): sha for name, sha in financial['files'].items()}
    expected.update({str(source/'market_inputs'/name): sha for name, sha in market['files'].items()})
    expected.update(market['sources_sha256'])
    expected[str(source/'eligibility/events.parquet')] = eligibility['events_sha256']
    _verify(expected)
    events = pl.read_parquet(source/'eligibility/events.parquet')
    symbols = set(events.filter(pl.col('eligible'))['symbol'])
    settings = tomllib.loads(share_exchange_config.read_text(encoding='utf-8'))
    for action in settings.get('share_exchanges', []):
        symbols.update([action['from_symbol'], action['to_symbol']])
    if not symbols:
        raise ValueError('Empty PEAD candidate universe')
    # The old symbol is a price-band verification input, never an extra financial candidate.
    read_symbols = symbols | {'000043.SZ', '001914.SZ'}
    calendars = [data_root/f'clean/trade_calendar/market={market}/data.parquet' for market in ('SH', 'SZ')]
    calendar = TradeCalendarSchema.validate(pl.concat([pl.read_parquet(path) for path in calendars]))
    sh = calendar.filter((pl.col('market') == 'SH') & pl.col('is_open'))['date'].sort().to_list()
    sz = calendar.filter((pl.col('market') == 'SZ') & pl.col('is_open'))['date'].sort().to_list()
    prior = [day for day in sh if day < start]
    if len(prior) < 20:
        raise ValueError('Account inputs require 20 prior exchange sessions')
    warmup = prior[-20]
    sessions = [day for day in sh if warmup <= day <= end]
    if sessions != [day for day in sz if warmup <= day <= end] or not sessions:
        raise ValueError('SH/SZ calendar coverage differs')
    financial_sessions = {dt.date.fromisoformat(day) for day in _json(source/'inputs/sessions.json')}
    calendar_end = max(end, events['reference_expiry_date'].max())
    horizon_sessions = [day for day in sh if warmup <= day <= calendar_end]
    if (calendar['date'].max() < calendar_end
            or horizon_sessions != [day for day in sz if warmup <= day <= calendar_end]):
        raise ValueError('Incomplete common exchange calendar for registered event horizons')
    if set(horizon_sessions) - financial_sessions:
        raise ValueError('Execution calendar differs from the frozen event calendar')
    execution = data_root/'clean/stock_execution/factor_battery_20260911_v2'
    metadata_sources = [*calendars, share_exchange_config, execution/'instruments.parquet',
        execution/'dividends.parquet', execution/'sources.json', source/'inputs/manifest.json',
        source/'market_inputs/manifest.json', source/'eligibility/input_identity.json', source/'eligibility/summary.json',
        source/'events.parquet']
    proof = Path('artifacts/research/paper_reading_code_migrations_20260912_01/sources.json')
    metadata_sources.append(proof)
    expected.update({str(path): _sha(path) for path in metadata_sources})
    sources = [Path(path) for path in market['sources_sha256'] if Path(path).suffix == '.parquet'
               and ('bar_1d' in Path(path).parts or Path(path).name == 'bar_1d.parquet')]
    if not sources:
        raise ValueError('Market manifest contains no full-bar sources')
    instruments = InstrumentSchema.validate(pl.read_parquet(execution/'instruments.parquet'))
    missing_instruments = symbols - set(instruments['symbol'])
    if missing_instruments:
        raise ValueError('Candidate/successor instruments missing: '+str(sorted(missing_instruments)))
    target.mkdir(parents=True, exist_ok=False)
    for src, name in ((source/'inputs/manifest.json', 'financial_manifest.json'),
                      (source/'market_inputs/manifest.json', 'market_manifest.json'),
                      (source/'eligibility/summary.json', 'eligibility_manifest.json'),
                      (source/'eligibility/input_identity.json', 'eligibility_identity.json')):
        (target/name).write_bytes(src.read_bytes())
    (target/'eligibility_events.parquet').write_bytes((source/'eligibility/events.parquet').read_bytes())
    calendar.filter(pl.col('date').is_between(warmup, calendar_end)).write_parquet(target/'calendar.parquet')
    instruments.filter(pl.col('symbol').is_in(sorted(symbols))).write_parquet(target/'instruments.parquet')
    dividends = _account_dividends(pl.read_parquet(execution/'dividends.parquet'), symbols=symbols,
                                  start=start, end=end)
    dividends.write_parquet(target/'dividends.parquet')
    evidence = _json(proof)
    yearly, mapping_frames, endpoint_coverage, invalid_band_frames = [], [], [], []
    bar_writer = limit_writer = None
    try:
        for year in range(warmup.year, end.year+1):
            first, last = max(warmup, dt.date(year, 1, 1)), min(end, dt.date(year, 12, 31))
            relevant = [path for path in sources if (f'year={year}' in path.parts
                or ('tushare_incremental' in path.parts and first <= dt.date.fromisoformat(path.parent.name[5:]) <= last))]
            if not relevant:
                raise ValueError(f'Missing frozen market source year: {year}')
            bars = _resolve_market_bars(relevant, start=first, end=last, symbols=read_symbols)
            frozen = pl.scan_parquet(source/'market_inputs/bars.parquet').filter(
                pl.col('trade_date').is_between(first, last) & pl.col('symbol').is_in(sorted(read_symbols)))
            old = frozen.select('symbol', 'trade_date', 'close', 'amount').collect().sort('trade_date', 'symbol')
            if not bars.select('symbol', 'trade_date', 'close', 'amount').equals(old):
                raise ValueError(f'Full bars differ from frozen eligibility market: {year}')
            limit_path = data_root/f'clean/factor_execution/limits_20260911/year={year}/limits.parquet'
            if year < start.year:
                limits = pl.DataFrame(schema={'symbol': pl.String, 'trade_date': pl.Date,
                                              'up_limit': pl.Float64, 'down_limit': pl.Float64})
                mappings = None
                invalid_bands = limits.clear()
            else:
                expected[str(limit_path)] = _sha(limit_path)
                limits = pl.read_parquet(limit_path).filter(pl.col('symbol').is_in(sorted(read_symbols))
                    & pl.col('trade_date').is_between(max(start, first), last))
                limits, invalid_bands = _usable_daily_bands(limits)
                invalid_band_frames.append(invalid_bands.with_columns(pl.lit(str(limit_path)).alias('source_path'),
                    pl.lit('missing_nonfinite_nonpositive_or_reversed_band').alias('reason')))
                limits, mappings = fill_same_entity_limits(bars=bars, limits=limits, evidence=evidence)
                mapping_frames.append(mappings)
            bars = bars.filter(pl.col('symbol').is_in(sorted(symbols)))
            limits = limits.filter(pl.col('symbol').is_in(sorted(symbols))).sort('trade_date', 'symbol')
            for frame, name in ((bars, 'bars'), (limits, 'limits')):
                table = frame.to_arrow()
                writer = bar_writer if name == 'bars' else limit_writer
                if writer is None:
                    writer = pq.ParquetWriter(target/f'{name}.parquet', table.schema, compression='zstd')
                    if name == 'bars':
                        bar_writer = writer
                    else:
                        limit_writer = writer
                writer.write_table(table)
            positive = bars.filter((pl.col('volume') > 0) & (pl.col('trade_date') >= start))
            missing = positive.join(limits.select('symbol', 'trade_date'), on=['symbol', 'trade_date'], how='anti')
            yearly.append({'year': year, 'bar_rows': bars.height, 'bar_dates': bars['trade_date'].n_unique(),
                'limit_rows': limits.height, 'positive_bar_missing_band_rows': missing.height,
                'invalid_source_band_rows': invalid_bands.height,
                'zero_volume_rows': bars.filter(pl.col('volume') == 0).height,
                'mapped_bands': 0 if mappings is None else mappings['applied'].sum()})
            for cohort in ('eligible', 'selected'):
                for phase in ('earliest_execution_date', 'reference_expiry_date'):
                    keys = events.filter(pl.col(cohort)).select('symbol', pl.col(phase).alias('trade_date')).unique()
                    keys = keys.filter(pl.col('trade_date').is_between(max(start, first), last))
                    endpoint_coverage.append({'year': year, 'cohort': cohort, 'phase': phase, 'keys': keys.height,
                        'missing_bars': keys.join(bars.select('symbol', 'trade_date'), on=['symbol', 'trade_date'], how='anti').height,
                        'missing_bands': keys.join(limits.select('symbol', 'trade_date'), on=['symbol', 'trade_date'], how='anti').height})
            print(json.dumps({'pead_account_input_year': year, 'bars': bars.height, 'daily_bands': limits.height}), flush=True)
    finally:
        if bar_writer is not None:
            bar_writer.close()
        if limit_writer is not None:
            limit_writer.close()
    mappings = pl.concat(mapping_frames, how='vertical_relaxed')
    mappings.write_parquet(target/'band_alias_mappings.parquet')
    pl.concat(invalid_band_frames, how='vertical_relaxed').write_parquet(target/'invalid_daily_bands.parquet')
    detail, coverage, individual, requests, suspend_hashes = read_suspensions(
        data_root=data_root, sessions=sessions, symbols=read_symbols)
    expected.update(suspend_hashes)
    # Alias legacy-code halt positives conservatively; a code change never proves the absence of a halt.
    old_halts = detail.filter((pl.col('symbol') == '000043.SZ') & (pl.col('trade_date') < ALIAS_DATE))
    old_halts = old_halts.with_columns(pl.lit('001914.SZ').alias('symbol'))
    detail = pl.concat([detail, old_halts]).filter(pl.col('symbol').is_in(sorted(symbols))).unique()
    detail.write_parquet(target/'suspension_details.parquet')
    detail.select('symbol', 'trade_date').unique().write_parquet(target/'suspensions.parquet')
    coverage.write_parquet(target/'suspension_coverage.parquet')
    _write_json(target/'suspension_symbol_coverage.json', individual)
    _write_json(target/'suspension_requests.json', requests)
    _verify(expected)
    account_coverage = coverage.filter(pl.col('trade_date') >= start)
    result = {'created_at': dt.datetime.now(dt.timezone.utc), 'source': str(source), 'start': start, 'end': end,
        'financial_events_sha256': identity['events_sha256'],
        'warmup_start': warmup, 'calendar_end': calendar_end,
        'prior_sessions': 20, 'account_sessions': account_coverage.height,
        'candidate_symbols': len(set(events.filter(pl.col('eligible'))['symbol'])), 'symbols_with_successors': len(symbols),
        'source_sha256_before': expected, 'source_sha256_after': expected, 'source_files_unchanged': True,
        'files': {path.name: _sha(path) for path in sorted(target.iterdir()) if path.is_file()},
        'schemas': {path.name: {key: str(value) for key, value in pl.read_parquet_schema(path).items()}
                    for path in sorted(target.glob('*.parquet'))},
        'yearly': yearly, 'endpoint_coverage': endpoint_coverage,
        'band_alias_rows': mappings.height, 'band_alias_applied': mappings['applied'].sum(),
        'suspension_covered_sessions': account_coverage['coverage_complete'].sum(),
        'suspension_unknown_sessions': account_coverage.filter(~pl.col('coverage_complete')).height,
        'suspension_yearly_coverage': account_coverage.group_by(pl.col('trade_date').dt.year().alias('year'))
            .agg(pl.len().alias('sessions'), pl.col('coverage_complete').sum().alias('covered_sessions')).sort('year').to_dicts(),
        'suspension_scope': 'All available verified raw positives; full-market day coverage kept separate from symbol windows.',
        'limitations': ['Reconstructed financial/name vintages are not original release-time snapshots.',
            'A positive-volume bar on an uncovered date cannot rule out an intraday halt.',
            'Missing or zero-volume bars are not tradable; missing bands require blocked orders.',
            'No account replay or strategy admission was performed by this input freeze.'],
        'auto_trade': False, 'account_replays': 0, 'code_sha256': _sha(Path(__file__))}
    _write_json(target/'manifest.json', result)
    return result
