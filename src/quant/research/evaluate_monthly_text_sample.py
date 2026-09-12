"""Evaluate a frozen monthly sample from existing API responses, without publication."""
import argparse
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.monthly_text_sample import cache_snapshot, membership_panel
from quant.data.forecast_text_evaluation import read_forecast_controls, attach_forecast_controls, read_sue_control
from quant.research.score_forecast_text import load_design, load_settings
from quant.research.forecast_text_incremental import diagnose_sections
from quant.research.evaluate_forecast_text import write_incremental


def run(*, plan: Path, cache: Path, output: Path, data_root: Path) -> dict:
    spec = tomllib.loads((plan/'config.toml').read_text(encoding='utf-8'))
    saved = json.loads((plan/'summary.json').read_text())
    design, settings = load_design(Path(spec['design'])),load_settings(Path(spec['scoring']))
    scores, status = cache_snapshot(source=Path(spec['source']),cache=cache,settings=settings,
                                     allowed_keys=set(saved['selected_request_keys']))
    members = pl.read_parquet(plan/'selected_members.parquet')
    text = membership_panel(scores,members,max_age_days=design['maximum_age_calendar_days'])
    numeric = read_forecast_controls(Path(spec['source']))
    battery = tomllib.loads((Path(spec['statistics'])/'battery.toml').read_text())
    output.mkdir(parents=True,exist_ok=False)
    (output/'sampling.toml').write_bytes((plan/'config.toml').read_bytes())
    scores.write_parquet(output/'full_event_scores.parquet')
    text.write_parquet(output/'monthly_text_panel.parquet')
    points,supports = [],[]
    for year in range(design['start'].year,design['end'].year+1):
        folder = Path(spec['statistics'])/f'inputs/{year}'
        annual = text.filter(pl.col('trade_date').dt.year() == year)
        universe = pl.read_parquet(folder/'universe.parquet').join(annual,on=['symbol','trade_date'],how='inner',validate='1:1')
        panel = attach_forecast_controls(universe,numeric,max_age_days=design['maximum_age_calendar_days'])
        panel = panel.join(read_sue_control(data_root,year=year,sue_factor='pit_sue8_context_v2'),
            on=['symbol','trade_date'],how='left',validate='1:1')
        labels = pl.read_parquet(folder/'monthly_labels.parquet').select('symbol','trade_date','label_rebalance')
        panel = panel.join(labels,on=['symbol','trade_date'],how='left',validate='1:1')
        part,support = diagnose_sections(panel,label='label_rebalance',frequency='monthly',settings=battery)
        points.append(part)
        supports.append(support)
    write_incremental(points,supports,output=output/'incremental',sessions=tuple(sorted(set(text['trade_date']))),
        settings=battery,design=design,synthetic=False)
    combined = pl.concat(points)
    counts = combined.filter(pl.col('comparator') == 'text').group_by('factor').agg(
        pl.col('text_count').max().alias('max_text_symbols'),
        pl.col('common_count').max().alias('max_common_symbols'),
        pl.col('rank_ic').is_not_null().sum().alias('usable_months'))
    result = {**status,'sample_rows':text.height,'coverage':counts.to_dicts(),
        'conclusion':'RESEARCH_ONLY','scope':'Partial monthly diagnostic; full timeline retained; frozen membership; no factor publication or trading changes'}
    (output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-root',type=Path,default=Path('data'))
    print(json.dumps(run(**vars(parser.parse_args()))))


if __name__ == '__main__':
    main()
