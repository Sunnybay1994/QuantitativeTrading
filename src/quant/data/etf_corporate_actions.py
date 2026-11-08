"""Versioned, source-backed ETF cash and share actions for the shared daily account."""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import tomllib

import polars as pl

from quant.data.stock_paper_inputs import DIVIDEND_SCHEMA

SCHEMA={**DIVIDEND_SCHEMA,'adjust_share_price':pl.Boolean,'action_type':pl.String,
    'source_path':pl.String,'source_sha256':pl.String,'source_url':pl.String,
    'observed_at':pl.String,'version':pl.String}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cash_actions(raw, end):
    """Preserve implemented fund_div cash terms; never infer a distribution."""
    rows=[]
    if raw.is_empty():
        return rows
    for row in raw.filter(pl.col('div_proc')=='实施').iter_rows(named=True):
        if not row.get('ex_date'):
            continue
        def day(field):
            return dt.datetime.strptime(str(row[field]),'%Y%m%d').date()
        ex=day('ex_date')
        if ex>end:
            continue
        ann=day('imp_anndate') if row.get('imp_anndate') else day('ann_date')
        record,pay,amount=day('record_date'),day('pay_date'),float(row['div_cash'])
        if not ann<=record<ex<=pay or not math.isfinite(amount) or amount<0:
            raise ValueError('Incomplete or noncausal ETF cash action')
        rows.append(dict(symbol=row['ts_code'],ann_date=ann,record_date=record,ex_date=ex,
            pay_date=pay,share_list_date=None,div_cash=amount,share_ratio=0.))
    rows=list({tuple(row.items()):row for row in rows}.values())
    if len({(r['symbol'],r['ex_date']) for r in rows})!=len(rows):
        raise ValueError('Conflicting ETF cash action terms')
    return rows


def publish(*, capture, sources, output, panel=None):
    """Publish a new immutable version from captured raw and issuer notices.

    Cash source inventories include zero-row responses. Notice-announced terms
    determine share quantities; prices only provide a continuity diagnostic.
    Historical announcement dates do not establish original data-arrival vintages.
    """
    capture,sources,output=Path(capture),Path(sources),Path(output)
    if output.exists():
        raise FileExistsError('Use a new ETF corporate-action version')
    original=json.loads((capture/'summary.json').read_text(encoding='utf-8'))
    spec=tomllib.loads((capture/'config.toml').read_text(encoding='utf-8'))
    terms_path=capture/'corporate_actions.toml'
    assert sha(terms_path)==original['events_sha256']
    terms=tomllib.loads(terms_path.read_text(encoding='utf-8'))['splits']
    notices=json.loads(sources.read_text(encoding='utf-8'))
    now=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat()
    rows,inventory,diagnostics=[],[],[]
    for key,item in original['requests'].items():
        if '/fund_div/' not in key:
            continue
        path=Path(item['raw_path'])
        if sha(path)!=item['sha256']:
            raise ValueError('Captured fund_div raw changed')
        raw=pl.read_parquet(path)
        inventory.append({'symbol':key.split('/')[0],'kind':'fund_div','rows':raw.height,
            'path':str(path),'sha256':item['sha256']})
        for row in cash_actions(raw,dt.date.fromisoformat(now[:10])):
            rows.append({**row,'adjust_share_price':True,'action_type':'CASH_DIVIDEND',
                'source_path':str(path),'source_sha256':item['sha256'],'source_url':'tushare:fund_div',
                'observed_at':now,'version':output.name})
    for term in terms:
        expected={term['notice'],term['result']}
        selected=[v for v in notices.values() if v['url'] in expected]
        if {v['url'] for v in selected}!=expected or any(sha(v['path'])!=v['sha256'] for v in selected):
            raise ValueError('Require saved issuer notice and result with matching hashes')
        ratio=float(term['ratio'])
        if not math.isfinite(ratio) or ratio<=0 or ratio==1:
            raise ValueError('Invalid official ETF share conversion')
        source=next(v for v in selected if v['url']==term['notice'])
        for v in selected:
            inventory.append({'symbol':term['symbol'],'kind':'issuer_notice',**v})
        rows.append(dict(symbol=term['symbol'],ann_date=term['announcement_date'],
            record_date=term['record_date'],ex_date=term['effective_date'],
            pay_date=term['effective_date'],share_list_date=term['tradable_date'],div_cash=0.,
            share_ratio=ratio-1,adjust_share_price=True,
            action_type='SHARE_SPLIT' if ratio>1 else 'SHARE_CONSOLIDATION',
            source_path=source['path'],source_sha256=source['sha256'],source_url=source['url'],
            observed_at=now,version=output.name))
        if panel is not None:
            quotes=pl.read_parquet(Path(panel)/'bars.parquet').filter(pl.col('symbol')==term['symbol'])
            before=quotes.filter(pl.col('trade_date')<term['effective_date']).sort('trade_date').tail(1)
            after=quotes.filter(pl.col('trade_date')>=term['tradable_date']).sort('trade_date').head(1)
            if before.is_empty() or after.is_empty():
                raise ValueError('Missing prices for official action continuity check')
            pre,post=float(before['close'][0]),float(after['close'][0])
            diagnostics.append(dict(symbol=term['symbol'],date=str(term['effective_date']),
                official_share_factor=ratio,prior_market_close=pre,
                suspended_carried_mark=pre/ratio,reopening_market_close=post,
                economic_reopening_return=post*ratio/pre-1,
                suspended_tradable_bar_synthesized=False,ratio_inferred_from_price=False))
    frame=pl.from_dicts(rows,schema=SCHEMA).sort('symbol','ex_date')
    if frame.select('symbol','ex_date').is_duplicated().any():
        raise ValueError('Conflicting ETF actions require explicit source reconciliation')
    output.mkdir(parents=True,exist_ok=False)
    data=output/'actions.parquet';frame.write_parquet(data)
    (output/'terms.toml').write_bytes(terms_path.read_bytes())
    (output/'sources.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    summary=dict(status='complete',observed_at=now,version=output.name,rows=frame.height,
        symbols=sorted(r['symbol'] for r in inventory if r['kind']=='fund_div'),
        data_sha256=sha(data),sources_sha256=sha(output/'sources.json'),terms_sha256=sha(output/'terms.toml'),
        continuity=diagnostics,auto_trade=False,
        timing='Reconstructed historical issuer terms; observed_at is actual ingestion, not original PIT arrival',
        source_scope='Account ETFs and registered 510300 proxy only; no whole-market completeness claim')
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary


def load(root, *, symbols=None, end=None):
    """Return ledger events with explicit semantics and unchanged source versions."""
    root=Path(root);summary=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    if summary['status']!='complete' or sha(root/'actions.parquet')!=summary['data_sha256']:
        raise ValueError('Invalid ETF action master')
    if sha(root/'sources.json')!=summary['sources_sha256'] or sha(root/'terms.toml')!=summary['terms_sha256']:
        raise ValueError('ETF corporate-action provenance changed')
    frame=pl.read_parquet(root/'actions.parquet')
    if symbols is not None:
        if not set(symbols)<=set(summary['symbols']):
            raise ValueError('Requested ETF lacks a captured action-source inventory')
        frame=frame.filter(pl.col('symbol').is_in(symbols))
    if end is not None:
        frame=frame.filter(pl.col('ex_date')<=end)
    return frame


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',type=Path,required=True);p.add_argument('--sources',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--panel',type=Path)
    print(json.dumps(publish(**vars(p.parse_args())),ensure_ascii=False))
