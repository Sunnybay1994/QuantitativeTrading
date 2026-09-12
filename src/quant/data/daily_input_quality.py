"""Inspect actual daily input rows and factor availability after incremental refresh."""
import datetime as dt
import json
import tomllib
from pathlib import Path

import polars as pl

from quant.data.factor_panels import available_sessions
from quant.data.refresh_stocks import read_stock_data
from quant.data.daily_value_quality import diagnose_daily_value_inputs
from quant.data.sue_input_quality import read_sue_report_context


def check_stock_inputs(bars: pl.DataFrame, basic: pl.DataFrame, adjustment: pl.DataFrame,
                       *, sessions: tuple[dt.date, ...]) -> dict:
    keys = ['trade_date', 'symbol']
    adjustment = adjustment.rename({'effective_date': 'trade_date'})
    missing_dates = sorted(set(sessions)-set(bars['trade_date']))
    result = {'expected_sessions': len(sessions), 'missing_sessions': [str(d) for d in missing_dates],
              'traded_rows': bars.height, 'latest_traded_symbols': bars.filter(
                  pl.col('trade_date') == sessions[-1])['symbol'].n_unique()}
    for name, frame in (('bars', bars), ('daily_basic', basic), ('adjustment', adjustment)):
        result[f'{name}_duplicate_keys'] = frame.height-frame.unique(subset=keys).height
        result[f'{name}_missing_keys'] = bars.select(keys).join(frame.select(keys), on=keys, how='anti').height
    paired = bars.select(*keys, 'close').join(basic.select(*keys, pl.col('close').alias('basic_close')),
                                             on=keys, how='inner')
    result['close_mismatches'] = paired.filter(
        pl.col('close').is_null() | pl.col('basic_close').is_null()
        | ((pl.col('close')-pl.col('basic_close')).abs() > 1e-8)).height
    result['invalid_adjustments'] = adjustment.filter(
        pl.col('adj_factor').is_null() | ~pl.col('adj_factor').is_finite() | (pl.col('adj_factor') <= 0)).height
    return result


def inspect_factor(frame: pl.DataFrame, *, symbols: set[str]) -> dict:
    valid = frame.filter(pl.col('value').is_not_null() & pl.col('value').is_finite())
    present = set(frame['ts_code'])
    valid_symbols = set(valid['ts_code']) & symbols
    return {'rows': frame.height, 'valid_symbols': len(valid_symbols),
            'valid_share': len(valid_symbols)/len(symbols) if symbols else 0.0,
            'duplicate_keys': frame.height-frame['ts_code'].n_unique(),
            'missing_bar_symbols': len(symbols-present), 'extra_symbols': len(present-symbols),
            'nonfinite_values': frame.filter(pl.col('value').is_not_null() & ~pl.col('value').is_finite()).height}


def run_quality(*, data_root: Path, config: Path, end: dt.date, factors: list[dict],
                financials: dict, output: Path, lookback_sessions: int = 5, minimum_symbols: int = 100) -> dict:
    if lookback_sessions < 1 or minimum_symbols < 1:
        raise ValueError('Use positive session and symbol counts for input quality checks')
    calendar = available_sessions(data_root, end)
    if not calendar or calendar[-1] != end:
        raise ValueError('Quality checks require a completed exchange session')
    sessions = calendar[-lookback_sessions:]
    tables = {name: read_stock_data(data_root=data_root, config=config, table=name,
        start=sessions[0], end=end) for name in ('bar_1d', 'daily_basic', 'adjust_factor')}
    stocks = check_stock_inputs(tables['bar_1d'], tables['daily_basic'], tables['adjust_factor'], sessions=sessions)
    symbols = set(tables['bar_1d'].filter(pl.col('trade_date') == end)['symbol'])
    rows, errors, value_checks, value_summaries = [], [], [], []
    sue_checks, sue_summaries = [], []
    financial_snapshot = financials.get('financial_snapshot')
    if stocks['missing_sessions'] or not symbols:
        errors.append('Missing expected stock trading sessions')
    for name, count in stocks.items():
        if (name.endswith(('_duplicate_keys', '_missing_keys')) or name in
                ('close_mismatches', 'invalid_adjustments')) and count:
            errors.append(f'{name}: {count}')
    for factor in factors:
        path = data_root/'factors'/factor['id']/f'year={end.year}'/'data.parquet'
        last_valid = None
        if path.is_file():
            panel = pl.scan_parquet(path).filter(pl.col('trade_date') <= end)
            frame = panel.filter(pl.col('trade_date') == end).select('ts_code', 'value').collect()
            last_valid = panel.filter(pl.col('value').is_not_null() & pl.col('value').is_finite()).select(
                pl.col('trade_date').max()).collect().item()
        else:
            frame = pl.DataFrame(schema={'ts_code': pl.String, 'value': pl.Float64})
        row = {'factor': factor['id'], 'family': factor['family'], 'file_present': path.is_file(),
               'last_valid_date_this_year': str(last_valid) if last_valid is not None else None,
               **inspect_factor(frame, symbols=symbols)}
        rows.append(row)
        if not row['file_present'] or row['missing_bar_symbols'] or row['extra_symbols'] or row['duplicate_keys']:
            errors.append(f"{factor['id']}: missing or inconsistent daily panel keys")
        if factor['id'] in {'daily_dividend_yield_ttm', 'daily_ep_ttm_positive'}:
            try:
                checked = diagnose_daily_value_inputs(
                    pool=tables['bar_1d'].filter(pl.col('trade_date') == end).select('symbol', 'trade_date'),
                    basic=tables['daily_basic'].filter(pl.col('trade_date') == end),
                    factor_values=frame.with_columns(pl.lit(end).alias('trade_date')), factor_id=factor['id'])
            except ValueError as exc:
                errors.append(f"{factor['id']}: value-input diagnosis failed: {exc}")
            else:
                value_checks.append(checked.with_columns(pl.lit(factor['id']).alias('factor')))
                counts = dict(checked.group_by('reason').len().iter_rows())
                unexpected = checked['unexpected_factor_value'].sum()
                value_summaries.append({'factor': factor['id'], 'symbols': checked.height,
                    'reasons': counts, 'unexpected_factor_values': unexpected})
                defects = sum(counts.get(reason, 0) for reason in (
                    'source_nonfinite', 'factor_row_missing', 'factor_value_missing', 'factor_value_mismatch'))
                if defects or unexpected:
                    errors.append(f"{factor['id']}: {defects} invalid/missing transformations; "
                                  f"{unexpected} unexpected finite values")
        if factor['id'] == 'pit_sue8':
            if not financial_snapshot:
                financial_snapshot = tomllib.loads(config.read_text(encoding='utf-8')).get('financial_snapshot')
            if not financial_snapshot:
                errors.append('pit_sue8: missing financial snapshot for PIT context check')
            else:
                try:
                    checked = read_sue_report_context(data_root=data_root, snapshot=financial_snapshot,
                        pool=tables['bar_1d'].filter(pl.col('trade_date') == end).select('symbol', 'trade_date'),
                        factor_values=frame.with_columns(pl.lit(end).alias('trade_date')), as_of=end)
                except ValueError as exc:
                    errors.append(f'pit_sue8: report-context diagnosis failed: {exc}')
                else:
                    sue_checks.append(checked)
                    unexpected = checked['unexpected_factor_value'].sum()
                    sue_summaries.append({'factor': 'pit_sue8', 'symbols': checked.height,
                        'report_contexts': dict(checked.group_by('report_context').len().iter_rows()),
                        'unexpected_factor_values': unexpected})
                    if unexpected:
                        errors.append(f'pit_sue8: {unexpected} finite values lack compatible latest PIT report context')
    unresolved = financials.get('unresolved_announcements', [])
    result = {'as_of': str(end), 'stocks': stocks, 'factor_count': len(rows),
              'factors_with_valid_values': sum(row['valid_symbols'] > 0 for row in rows),
              'minimum_symbols': minimum_symbols,
              'factors_meeting_symbol_count': sum(row['valid_symbols'] >= minimum_symbols for row in rows),
              'factors_without_valid_values': [row['factor'] for row in rows if row['valid_symbols'] == 0],
              'financial_snapshot': financial_snapshot,
              'unresolved_financial_announcements': len(unresolved),
              'unresolved_financial_symbols': sorted({row['symbol'] for row in unresolved}),
              'daily_value_input_checks': value_summaries,
              'sue_report_context_checks': sue_summaries,
              'errors': errors, 'output': str(output),
              'scope': 'Actual latest-session values; sparse or monthly factors are reported without a universal availability threshold'}
    output.mkdir(parents=True, exist_ok=False)
    pl.from_dicts(rows, infer_schema_length=None).write_parquet(output/'factor_coverage.parquet')
    if value_checks:
        pl.concat(value_checks).write_parquet(output/'daily_value_input_reasons.parquet')
    if sue_checks:
        pl.concat(sue_checks).write_parquet(output/'sue_report_context.parquet')
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = [f'# 每日输入检查：{end}', '',
        f"最近{len(sessions)}个交易日，最新成交股票{len(symbols)}只；"
        f"{result['factors_with_valid_values']}/{len(rows)}项因子当天有有限数值。", '',
        f"达到评估电池最少{minimum_symbols}只有效股票数量要求的因子：{result['factors_meeting_symbol_count']}项。", '',
        f"结构或数据配对问题：{len(errors)}项；待解析财务公告：{len(unresolved)}条。", '',
        '可用比例以当天实际成交股票为分母，空值可能来自预热、月度规则或数据缺口，不能仅凭空值判定源数据故障。', '',
        '|因子|有效股票|覆盖率|本年最近有效日|', '|---|---:|---:|---|']
    lines += [f"|{r['factor']}|{r['valid_symbols']}|{r['valid_share']:.1%}|{r['last_valid_date_this_year'] or '无'}|"
              for r in sorted(rows, key=lambda r: (r['valid_share'], r['factor']))]
    if errors:
        lines += ['', '需处理：', *['- '+error for error in errors]]
    if value_summaries:
        lines += ['', '日频价值因子已逐股票对照源值；源字段null、非正PE定义排除与转换缺陷分开统计。'
                  '真实股息率0有效，源null保留。详见daily_value_input_reasons.parquet及summary.json。']
    if sue_summaries:
        lines += ['', 'SUE另核对信号日前最新已披露合并利润表的企业类型；非工业类型沿用旧工业值'
                  '会列为问题。详见sue_report_context.parquet。']
    (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result
