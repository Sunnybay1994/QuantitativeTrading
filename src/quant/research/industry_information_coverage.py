"""Original-eligible, actual-N4 input coverage through the frozen cutoff; no IC test."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib

import numpy as np
import polars as pl
from polars.testing import assert_frame_equal

from quant.data.factor_industry_information_inputs import read_industry_information
from quant.data.factor_panels import available_sessions
from quant.data.monthly_open_inputs import digest
from quant.data.nightly_genetic_inputs import admitted_controls, read_raw_monthly
from quant.data.refresh_stocks import TABLES
from quant.factors.industry_information import SIGNALS, CONTROL
from quant.research.factor_battery_evaluation import score_factor_sections
from quant.research.nightly_steps import admission_reference
from quant.research.turnover_reference_family import save

KEYS=['symbol','trade_date']


def finite(names):
    return pl.all_horizontal(pl.col(c).is_finite().fill_null(False) for c in names)


def residual_available(section: pl.DataFrame, controls: list[str]) -> tuple[int,bool]:
    """Use N4's exact rank projection, without calculating target correlation or t."""
    paired=section.filter(finite(['candidate','label',*controls]))
    if paired.height<max(100,len(controls)+2):
        return paired.height,False
    ranks=paired.select(pl.col(c).rank('average') for c in ['candidate',*controls]).to_numpy()
    ranks=(ranks-ranks.mean(axis=0))/np.maximum(ranks.std(axis=0),1e-12)
    design=np.column_stack([np.ones(paired.height),ranks[:,1:]])
    residual=ranks[:,0]-design@np.linalg.lstsq(design,ranks[:,0],rcond=None)[0]
    return paired.height, bool(np.std(residual)>=1e-10 and paired['label'].n_unique()>1)


def run(*, output: Path, definition: Path, previous: Path, nightly: Path, as_of: dt.date) -> dict:
    output.mkdir(parents=True,exist_ok=False)
    spec=tomllib.loads(definition.read_text(encoding='utf-8'))
    settings=admission_reference({**tomllib.loads(nightly.read_text(encoding='utf-8')),'as_of':as_of})
    root=Path(settings['data_root'])
    stats=Path(settings['reference_statistics'])
    battery=tomllib.loads((stats/'battery.toml').read_text(encoding='utf-8'))
    if battery['run']['as_of']!=as_of or tuple(spec['signals'])!=SIGNALS:
        raise ValueError('Coverage must match the actual frozen reference and fixed family')
    scorecard=pl.read_parquet(settings['reference_scorecard'])
    admitted_rows=scorecard.filter(pl.col('factor_admitted')).select('factor','variant').unique()
    calendar=available_sessions(root,as_of+dt.timedelta(days=40))
    anchors=tuple(a for a,b in zip(calendar,calendar[1:]) if (a.year,a.month)!=(b.year,b.month)
        and dt.date(2014,1,1)<=a<=as_of)
    refresh=Path(settings['refresh_config'])
    recipe=tomllib.loads(refresh.read_text(encoding='utf-8'))
    files=[definition,refresh,stats/'battery.toml',Path(settings['reference_scorecard']),Path(__file__),
        previous/'signals.parquet',previous/'monthly_inputs.parquet',previous/'paired_summary.json',
        Path('src/quant/data/factor_industry_information_inputs.py'),Path('src/quant/factors/industry_information.py'),
        Path('src/quant/data/nightly_genetic_inputs.py'),Path('src/quant/research/nightly_steps.py'),
        root/'clean/tushare_industry'/spec['initial_industry_snapshot']/'intervals.parquet']
    for market in ('SH','SZ'):
        files.append(root/f'clean/trade_calendar/market={market}/data.parquet')
    for year in range(2014,as_of.year+1):
        files.extend(stats/f'inputs/{year}'/name for name in ('universe.parquet','monthly_labels.parquet'))
        for factor in spec['fixed_control_ids']:
            files.append(root/'factors'/factor/f'year={year}/data.parquet')
    for factor in admitted_rows['factor'].unique():
        files.extend(stats/'factors'/factor/name for name in ('monthly_scores.parquet','statistics.json'))
    for year in range(2025,as_of.year+1):
        files.extend([root/'clean/tushare_bulk/snapshots'/recipe['stock_snapshot']/f'bar_1d/asset=stock/year={year}/data.parquet',
            root/'clean/tushare_daily_basic/snapshots'/recipe['daily_basic_snapshot']/f'year={year}/data.parquet'])
    files.extend(p/f'{t}.parquet' for p in (root/'clean/tushare_incremental').glob('date=*')
        if '2025-06-01'<=p.name[5:]<=str(as_of) and all((p/f'{t}.parquet').exists() for t in TABLES) for t in TABLES)
    before={str(p):digest(p) for p in sorted(set(files))}
    # Preserve the historical computation already validated by the supplying run.
    historical_manifest=json.loads((previous/'source_manifest_after.json').read_text(encoding='utf-8'))
    for name,expected in historical_manifest.items():
        if Path(name)==definition:
            continue  # only explicit control IDs were added, checked below
        if digest(Path(name))!=expected:
            raise ValueError(f'Historical industry input changed: {name}')
    prior_registration=tomllib.loads((previous/'registration_before_control_ids.toml').read_text(encoding='utf-8'))
    if any(spec.get(k)!=v for k,v in prior_registration.items()):
        raise ValueError('Original industry definition changed')
    save(output/'source_manifest_before.json',before)
    newer,groups,inputs=read_industry_information(data_root=root,refresh_config=refresh,calendar=calendar,
        start=dt.date(2025,12,1),end=as_of,definition=definition)
    historical=pl.read_parquet(previous/'signals.parquet')
    assert_frame_equal(newer.filter(pl.col('trade_date')<dt.date(2026,1,1)).sort(KEYS),
        historical.filter(pl.col('trade_date')>=dt.date(2025,12,1)).sort(KEYS))
    prefix,_,_=read_industry_information(data_root=root,refresh_config=refresh,calendar=calendar,
        start=dt.date(2025,12,1),end=dt.date(2026,4,30),definition=definition)
    assert_frame_equal(prefix.sort(KEYS),newer.filter(pl.col('trade_date')<=dt.date(2026,4,30)).sort(KEYS))
    signals=pl.concat([historical,newer.filter(pl.col('trade_date')>=dt.date(2026,1,1))]).sort(KEYS)
    signals.write_parquet(output/'signals.parquet')
    inputs.write_parquet(output/'new_monthly_inputs.parquet')
    groups.write_parquet(output/'new_industry_months.parquet')
    universe=pl.concat([pl.scan_parquet(stats/f'inputs/{year}/universe.parquet').filter(pl.col('trade_date').is_in(anchors))
        .select(*KEYS,'eligible','total_market_value','industry_l1').collect() for year in range(2014,as_of.year+1)])
    controls,admitted=admitted_controls(stats,scorecard)
    original=read_raw_monthly(data_root=root,statistics=stats,factors=spec['fixed_control_ids'],
        start=dt.date(2014,1,1),end=as_of)
    mature=original.filter(pl.col('label_exit_date')<=as_of).join(controls,on=KEYS,how='left',validate='1:1').join(
        signals.select(*KEYS,CONTROL),on=KEYS,how='left',validate='1:1')
    names=list(dict.fromkeys([*admitted,CONTROL,*spec['fixed_control_ids']]))
    rows=[]
    for signal in SIGNALS:
        scores=score_factor_sections(universe=universe,values=signals.select(*KEYS,pl.col(signal).alias('value')),
            direction=1,settings=battery)
        scores.write_parquet(output/f'{signal}_preprocessed.parquet')
        joined=mature.join(scores,on=KEYS,how='left',validate='1:1')
        coverage=universe.filter(pl.col('eligible')).select(KEYS).join(signals.select(*KEYS,signal,CONTROL),
            on=KEYS,how='left',validate='1:1')
        for day in anchors:
            eligible=coverage.filter(pl.col('trade_date')==day)
            group=joined.filter(pl.col('trade_date')==day)
            raw=group.rename({'raw':'candidate'})
            n,available=residual_available(raw,names)
            basic=raw.filter(finite(['candidate','label']))
            neutral=group.filter(finite(['size_industry_neutral','label']))
            rows.append({'signal':signal,'trade_date':day,'eligible_stocks':eligible.height,
                'valid_signal':eligible.filter(finite([signal])).height,
                'matched_input':eligible.filter(finite([signal,CONTROL])).height,
                'mature_target_raw':basic.height,'fixed_and_admitted_paired':n,
                'original_battery_pair_coverage':basic.height/raw.filter(finite(['candidate'])).height
                    if raw.filter(finite(['candidate'])).height else 0.,
                'raw_variance_available':bool(basic.height>=100 and basic['candidate'].n_unique()>1 and basic['label'].n_unique()>1),
                'incremental_variance_month_available':available,
                'neutral_valid_paired':neutral.height})
    monthly=pl.from_dicts(rows).sort('signal','trade_date')
    monthly.write_parquet(output/'actual_n4_coverage.parquet')
    monthly.write_csv(output/'actual_n4_coverage.csv')
    annual=monthly.group_by('signal',pl.col('trade_date').dt.year().alias('year')).agg(
        (pl.col('valid_signal')>=100).sum().alias('signal_months'),
        (pl.col('fixed_and_admitted_paired')>=100).sum().alias('common_input_months'),
        pl.col('incremental_variance_month_available').sum().alias('projectable_months'))
    annual.sort('signal','year').write_csv(output/'annual_coverage.csv')
    summaries={name:{'signal_months':monthly.filter((pl.col('signal')==name)&(pl.col('valid_signal')>=100)).height,
        'common_input_months':monthly.filter((pl.col('signal')==name)&(pl.col('fixed_and_admitted_paired')>=100)).height,
        'projectable_months':monthly.filter((pl.col('signal')==name)&pl.col('incremental_variance_month_available')).height,
        'neutral_valid_paired':monthly.filter(pl.col('signal')==name)['neutral_valid_paired'].sum()} for name in SIGNALS}
    enough=summaries[SIGNALS[1]]['projectable_months']>=spec['minimum_formal_months']
    after={name:digest(Path(name)) for name in before}
    if before!=after:
        raise ValueError('Industry coverage source changed during audit')
    save(output/'source_manifest_after.json',after)
    result={'family':spec['family'],'as_of':str(as_of),'reference_statistics':str(stats),
        'signals':summaries,'admitted_variants':admitted_rows.to_dicts(),'admitted_controls':admitted,
        'fixed_controls':spec['fixed_control_ids'],'matched_control':CONTROL,
        'source_files_unchanged':len(before),'prefix_rows':prefix.height,'historical_december_2025_equal':True,
        'labels_read_for_availability':True,'ic_or_t_calculated':False,'battery_runs':0,'account_runs':0,'auto_trade':False,
        'whole_family_ready_for_original_pipeline':enough,
        'decision':'Integrate the complete two-signal family into original N1/N3/N4; momentum insufficiency retained'
            if enough else 'Common sample below 96 months; close this input route as unverified without dropping controls or changing definitions',
        'interpretation':'Industry allocation information, not independent stock alpha; neutral variant must remain without effective variance',
        'limitations':['Availability/projection counts are not IC, incremental t, original battery admission, profit or independent forward evidence',
            'Original supplier arrival vintages remain unestablished; no backcast taxonomy or missing-endpoint reweighting']}
    save(output/'summary.json',result)
    (output/'report.md').write_text('# 行业整族实际 N4 样本覆盖\n\n```json\n'+json.dumps(result,ensure_ascii=False,indent=2)+'\n```\n',encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--definition',type=Path,default=Path('configs/research/industry_information_family_v1.toml'))
    parser.add_argument('--previous',type=Path,default=Path('artifacts/research/industry_information_feasibility_20261005_01'))
    parser.add_argument('--nightly',type=Path,default=Path('configs/research/nightly.toml'))
    parser.add_argument('--as-of',type=dt.date.fromisoformat,default=dt.date(2026,9,30))
    print(json.dumps(run(**vars(parser.parse_args())),ensure_ascii=False))


if __name__=='__main__':
    main()
