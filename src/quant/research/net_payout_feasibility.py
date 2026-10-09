"""Bounded local-source feasibility audit; never substitute a proxy for cash payout."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tomllib

import polars as pl


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str, allow_nan=False)


def dividend_inventory(directory: Path) -> tuple[dict, list[Path]]:
    """Count receipt fields without deduplicating or asserting historical availability."""
    paths = sorted(directory.glob('*/data.parquet'))
    if not paths:
        raise ValueError(f'No dividend receipts in declared directory: {directory}')
    frame = pl.concat([pl.read_parquet(p) for p in paths], how='diagonal_relaxed')
    frame = frame.with_columns(
        pl.col('base_share', 'cash_div_tax').cast(pl.Float64, strict=False),
        pl.col('div_proc').str.strip_chars())
    cash = frame.filter((pl.col('div_proc') == '实施') & (pl.col('cash_div_tax') > 0))
    dated = cash.filter((pl.col('base_share') > 0) & pl.col('imp_ann_date').is_not_null()
                        & pl.col('pay_date').is_not_null())
    return {
        'source_directory': str(directory), 'receipt_count': len(paths), 'rows': frame.height,
        'cash_implemented_rows': cash.height, 'cash_implemented_symbols': cash['ts_code'].n_unique(),
        'positive_base_share_rows': cash.filter(pl.col('base_share') > 0).height,
        'base_and_dates_present_rows': dated.height,
        'base_and_dates_present_symbols': dated['ts_code'].n_unique(),
        'fields_present': frame.columns,
        'qualification': 'Receipt rows, not unique events: revisions, actual cash, eligible base shares, publication vintages and full-universe PIT coverage remain unverified',
    }, paths


def source_observations(extract: list[dict]) -> list[dict]:
    rows = []
    for source in extract:
        if digest(Path(source['file'])) != source['sha256']:
            raise ValueError('Source PDF identity changed')
        text = ''.join(page['text'] for page in source['pages'])
        match = re.search(r'(?:累计支付总金额|支付的总金额)为([\d,]+\.\d{2})(?:元)?（(不含|含)交易费用）', text)
        if not match:
            raise ValueError('Expected official cash disclosure not found')
        amount = float(match[1].replace(',', ''))
        publication = re.search(r'finalpage/(\d{4}-\d{2}-\d{2})/', source['url'])[1]
        end = re.search(r'截至(\d{4})年(\d{1,2})月(\d{1,2})日', text)
        if not end:
            raise ValueError('Missing cumulative cutoff')
        cutoff = dt.date(*map(int, end.groups()))
        rows.append({
            'symbol': '000813.SZ', 'announcement_date': publication,
            'cumulative_through': cutoff, 'amount_cny': amount,
            'fee_basis': 'excluding' if match[2] == '不含' else 'including',
            'stage': 'completed' if '2019-002' in text else 'in_progress',
            'plan_identity': '000813_2018-07-06_shareholder_approval',
            'amount_basis': 'plan_cumulative_actual_not_single_period_flow',
            'available_time_precision': 'publication_date_only_use_strict_prior_date',
            'source_url': source['url'], 'source_file': source['file'],
            'source_sha256': source['sha256'],
            'repurchase_ttm_cash_yield': None, 'net_shareholder_cash_payout_yield': None,
            'unknown_reason': 'No complete trailing-window coverage or matched dividends/issuance; fee basis differs between updates',
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    cfg = tomllib.loads(args.config.read_text(encoding='utf-8'))
    out = args.output or Path(cfg['output'])
    out.mkdir(parents=True, exist_ok=False)
    inputs = [args.config, Path(cfg['financial']), Path(cfg['dividend_sample']),
              Path(cfg['source_extract']), Path(cfg['battery_config'])]
    cf = pl.read_parquet(cfg['financial'])
    changes = Path(cfg['share_changes'])
    events = pl.read_parquet(changes / 'events.parquet')
    coverage = pl.read_parquet(changes / 'request_coverage.parquet')
    dividend = pl.read_parquet(cfg['dividend_sample'])
    extended_dividend = None
    if cfg.get('dividend_directory'):
        extended_dividend, dividend_paths = dividend_inventory(Path(cfg['dividend_directory']))
        inputs += dividend_paths
    inputs += [changes / 'events.parquet', changes / 'request_coverage.parquet']
    cf_symbols, covered_symbols = set(cf['symbol']), set(coverage['symbol'])
    financial_profile = {
        'rows': cf.height, 'symbols': len(cf_symbols),
        'end_date_min': cf['end_date'].min(), 'end_date_max': cf['end_date'].max(),
        'available_date_min': cf['available_date'].min(), 'available_date_max': cf['available_date'].max(),
        'source_observed_on_missing': cf['source_observed_on'].null_count(),
        'meaning': 'Counts describe saved financial history, not point-in-time cash-payout coverage',
        'fields': {field: {'non_null': cf[field].len() - cf[field].null_count(),
                           'definition_limitation': reason} for field, reason in {
            'c_pay_dist_dpcp_int_exp': 'Mixes dividends/profits/interest',
            'incl_dvd_profit_paid_sc_ms': 'Subsidiary minority distributions only; subtraction does not remove interest/preferred',
            'c_recp_cap_contrib': 'Not isolated parent common-share financing',
            'incl_cash_rec_saims': 'Subsidiary minority financing; subtracting it does not prove common-share net cash',
            'oth_cashpay_ral_fnc_act': 'Other financing payments are not isolated common-share repurchases',
        }.items()},
    }
    db = Path('data/run_state/tushare_bulk/state.sqlite')
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        ledger = conn.execute("SELECT dataset,status,count(*),sum(rows),max(updated_at) FROM requests WHERE dataset IN ('repurchase','cashflow','dividend') GROUP BY dataset,status").fetchall()
        leases = conn.execute('SELECT owner,expires_at FROM lease').fetchall()
    observations = source_observations(json.loads(Path(cfg['source_extract']).read_text(encoding='utf-8')))
    pl.DataFrame(observations).write_parquet(out / 'official_cash_observations.parquet')
    rows = []
    for component, issue in [
        ('repurchase_cash', 'No local Tushare repurchase raw; two official cumulative examples do not establish history/coverage'),
        ('common_issuance_cash', 'CNINFO table has dated event codes, no cash proceeds; existing signal is boolean'),
        ('common_dividend_cash',
         'Implemented cash-dividend receipt fields exist in m3_g1 including base_share, implementation announcement and payment date; eligible base, revisions, cash evidence and full-universe PIT coverage remain unverified'
         if extended_dividend else
         'Inspected dividend raw lacks eligible base_share; financial cash outflow mixes interest and non-common distributions'),
    ]:
        rows.append({'component': component, 'coverage_sufficient_for_existing_battery': False, 'reason': issue})
    raw_present = Path('data/raw/tushare/repurchase').exists()
    if raw_present:
        raise ValueError('Repurchase inventory changed; reassess bounded audit instead of reusing closure')
    local = {
        'financial': financial_profile,
        'share_changes': {'event_rows': events.height, 'event_columns': events.columns,
                          'coverage_rows': coverage.height, 'covered_symbols': len(covered_symbols),
                          'request_start': coverage['start'].min(), 'request_end': coverage['end'].max(),
                          'intersection_with_financial_symbols': len(cf_symbols & covered_symbols),
                          'financial_symbols_not_in_share_change_scope': len(cf_symbols - covered_symbols),
                          'scope': 'Declared 800-name request universe, not full market'},
        'dividend_sample': {'rows': dividend.height, 'columns': dividend.columns,
                            'has_base_share': 'base_share' in dividend.columns,
                            'scope': 'One original raw response; not a full raw dividend census'},
        'repurchase_raw_directory_present': raw_present,
        'additional_dividend_receipts': extended_dividend,
        'bulk_ledger_dataset_status_count_rows_updated_at': ledger,
        'bulk_lease_rows': leases,
        'writer_check_limit': 'Lease table read only; no collection started; process enumeration was unavailable',
    }
    calendar = Path('legacy/quant/data/tushare_bulk_ingest.py').read_text(encoding='utf-8')
    calendar_issue = 'base | {"trade_date": value.strftime("%Y%m%d")}' in calendar
    summary = {
        'id': cfg['id'], 'generated_at': dt.datetime.now(dt.timezone.utc),
        'supersedes_inventory_only': cfg.get('supersedes'),
        'dividend_inventory_correction': extended_dividend,
        'decision': 'CLOSE_CURRENT_DATA_ROUTE',
        'interpretation': 'Insufficient cash amount identity and point-in-time coverage; not a failed alpha backtest',
        'formula': cfg['formula'], 'family_definitions': {k: cfg[k] for k in ['family', 'directions', 'controls', 'window', 'zero_rule', 'issuance_rule', 'repurchase_rule', 'dividend_rule']},
        'components': rows, 'official_samples': observations,
        'official_sample_fee_basis_consistent': len({r['fee_basis'] for r in observations}) == 1,
        'cumulative_sum_or_delta_valid': False,
        'collector_trade_date_parameter_found': calendar_issue,
        'collector_limitation': 'Configured repurchase per_trade_date uses exchange sessions and trade_date; documented endpoint filters ann_date/start_date/end_date. Cannot infer complete announcement coverage or rely on default row caps',
        'usable_family_battery_months_established': 0,
        'statistical_result': None, 'incremental_result': None, 'three_cost_result': None,
        'new_queue_entries': 0, 'new_accounts': 0, 'auto_trade': False,
        'next_action': 'Close this data route without broad collection/platform work; continue existing independent-family mining and battery. Do not repackage dividend yield or the existing issuance boolean as new cash signals',
        'prior_wording_correction': 'Dividends enter positively: D + R - I. Supersedes ambiguous next-direction prose only, no historical result changed',
        'sources': ['https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2007.01226.x',
                    'https://tushare.pro/document/2?doc_id=124', 'https://tushare.pro/document/2?doc_id=44',
                    'https://tushare.pro/document/2?doc_id=103', 'https://tushare.pro/document/2?doc_id=494'],
    }
    write_json(out / 'local_inventory.json', local)
    write_json(out / 'summary.json', summary)
    for source in observations:
        inputs.append(Path(source['source_file']))
    inputs += [Path(__file__), Path('legacy/quant/data/tushare_bulk_ingest.py'), Path('configs/data/tushare_bulk_v1.toml')]
    write_json(out / 'manifest.json', {'inputs': [{'path': str(p), 'sha256': digest(p)} for p in inputs]})
    lines = ['# 净股东现金回报家族：一轮数据可行性核验', '',
             '结论：关闭当前数据路线；现金金额身份和历史可用时间不足，不提交电池、不新增账户。这不是收益检验失败。', '',
             f"公式：{cfg['formula']}", '',
             f"已检查现金流表 {cf.height:,} 行、{len(cf_symbols):,} 个代码；股本变动请求仅覆盖 {len(covered_symbols)} 个代码，不代表全市场。", '',
             '|组成|无法建立可用历史的原因|', '|---|---|']
    lines += [f"|{r['component']}|{r['reason']}|" for r in rows]
    if extended_dividend:
        d = extended_dividend
        lines += ['', '本版更正原清单漏查的 data/raw/m3_g1/tushare/dividend；原报告保留。', '',
                  f"该目录有 {d['receipt_count']} 份回执、{d['rows']:,} 行；实施且正现金分红 {d['cash_implemented_rows']:,} 行、{d['cash_implemented_symbols']} 个证券，其中分红基数大于零 {d['positive_base_share_rows']:,} 行，基数及实施公告日、派息日字段齐全 {d['base_and_dates_present_rows']:,} 行。", '',
                  '这些是原始回执行数，尚未去重或排除修订；字段存在不证明基数适格、实际现金支付、历史 PIT 或全市场覆盖。分红基数在本地存在，不能再把其缺失列为全局关闭理由，也不据此断言供应商永久不可得。回购实际现金和普通股融资现金的历史缺口仍使整族不可评估。']
    lines += ['', '## 官方公告实测', '', '|公告公开日|累计截止|实际累计元|费用口径|', '|---|---|---:|---|']
    lines += [f"|[{r['announcement_date']}]({r['source_url']})|{r['cumulative_through']}|{r['amount_cny']:,.2f}|{r['fee_basis']}|" for r in observations]
    lines += ['', '两份公告属于同一计划，金额为累计实际支付额；费用口径不同，不可求和，也不能直接差分为新增现金。董事会签署日与公开日不同，信号只能在已公开后使用，不能回填至累计截止日。', '',
              '已有发行列只是事件布尔值，包含转股和期权行权；现金流的资本投入及其他筹资现金也不是普通股现金金额的替代。供应商增发接口的实际融资字段仍需排除非现金认购、校验收款日期和历史修订，当前本地没有该历史。', '',
              '当前回购采集器生成 trade_date，且只取交易日；接口使用公告日期参数。未启动这项采集，也未改动运行中的挖掘批次。', '',
              '全家族定义、正方向及既有分红/发行控制保存在 summary.json；可用历史未建立，统计、增量和三档成本结果均为未知。继续原独立机制队列，不新增此家族账户、不用零补缺。', '',
              '更正旧诊断的下一方向文字：现金分红为加项 D + R - I。旧回测、持仓、成本及其数值结论均不改写。']
    with (out / 'report.md').open('x', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')
    print(json.dumps({'output': str(out), 'decision': summary['decision'], 'financial_rows': cf.height,
                      'official_examples': len(observations), 'new_queue_entries': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
