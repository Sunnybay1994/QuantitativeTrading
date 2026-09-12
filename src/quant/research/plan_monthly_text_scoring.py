"""Select actual monthly text inputs before allocating the research API budget."""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib

import polars as pl

from quant.data.forecast_text_scores import read_corpus
from quant.data.forecast_text_evaluation import attach_forecast_controls, read_forecast_controls, read_sue_control
from quant.factors.forecast_text_score import input_token_bound, score_key
from quant.research.score_forecast_text import cost_for, load_design, load_settings


def monthly_selection(panel: pl.DataFrame, *, count: int, seed: str) -> pl.DataFrame:
    if count < 1 or panel.select('symbol','trade_date').is_duplicated().any():
        raise ValueError('Require positive count and unique monthly universe')
    rank = pl.DataFrame({'symbol':sorted(set(panel['symbol']))}).with_columns(
        pl.col('symbol').map_elements(lambda s: hashlib.sha256(f'{seed}:{s}'.encode()).hexdigest(),
                                      return_dtype=pl.String).alias('sampling_rank'))
    return panel.join(rank,on='symbol',validate='m:1').sort('trade_date','sampling_rank').group_by(
        'trade_date',maintain_order=True).head(count)


def run(*, config: Path, output: Path, data_root: Path) -> dict:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    if spec['auto_trade'] is not False:
        raise ValueError('Research sampling only')
    design, settings = load_design(Path(spec['design'])), load_settings(Path(spec['scoring']))
    corpus = read_corpus(Path(spec['source']))
    numeric = read_forecast_controls(Path(spec['source']))
    events = corpus.sort('symbol','publication_date','report_period').unique(
        subset=['symbol','publication_date'],keep='last',maintain_order=True)
    events = events.select('symbol','publication_date','input_id','reason_text','same_day_conflict')
    panels = []
    for year in range(design['start'].year,design['end'].year+1):
        folder = Path(spec['statistics'])/f'inputs/{year}'
        # Only dates, never label values or label availability, enter selection.
        dates = pl.read_parquet(folder/'monthly_labels.parquet',columns=['trade_date'])['trade_date'].unique()
        universe = pl.scan_parquet(folder/'universe.parquet').filter(pl.col('trade_date').is_in(dates.implode())).select(
            'symbol','trade_date','eligible','total_market_value','industry_l1').collect()
        panel = attach_forecast_controls(universe,numeric,max_age_days=design['maximum_age_calendar_days'])
        panel = panel.sort('trade_date').join_asof(events.sort('publication_date'),
            left_on='trade_date',right_on='publication_date',by='symbol',strategy='backward',check_sortedness=False)
        panel = panel.join(read_sue_control(data_root,year=year,sue_factor='pit_sue8_context_v2'),
                           on=['symbol','trade_date'],how='left',validate='1:1')
        valid = (pl.col('eligible') & pl.col('reason_text').is_not_null() & ~pl.col('same_day_conflict')
            & ((pl.col('trade_date')-pl.col('publication_date')).dt.total_days() < design['maximum_age_calendar_days'])
            & pl.col('forecast_p_change_midpoint').is_finite() & pl.col('pit_sue8').is_finite()
            & pl.col('total_market_value').is_finite() & (pl.col('total_market_value') > 0)
            & pl.col('industry_l1').is_not_null() & (pl.col('industry_l1').str.strip_chars() != ''))
        panels.append(panel.filter(valid.fill_null(False)).select('symbol','trade_date','input_id','reason_text'))
    panel = pl.concat(panels)
    output.mkdir(parents=True,exist_ok=False)
    (output/'config.toml').write_bytes(config.read_bytes())
    frontier = []
    for size in spec['monthly_sizes']:
        selected = monthly_selection(panel,count=size,seed=spec['seed'])
        selected.write_parquet(output/f'monthly_{size}.parquet')
        texts = selected['reason_text'].unique().to_list()
        bound = sum(cost_for(input_token_bound(t,format_version=settings['format_version']),settings['max_tokens'],settings) for t in texts)
        counts = selected.group_by('trade_date').len()
        frontier.append({'monthly_size':size,'stock_months':selected.height,'unique_texts':len(texts),
            'months_at_least_100':counts.filter(pl.col('len') >= 100).height,'one_attempt_upper_usd':bound})
    selected = pl.read_parquet(output/f"monthly_{spec['primary_monthly_size']}.parquet")
    texts = sorted(set(selected['reason_text']),key=lambda t:hashlib.sha256((spec['seed']+':'+t).encode()).hexdigest())
    chosen = texts[:spec['first_batch_unique_texts']]
    # This is only a scoring request batch, not a substitute publication corpus.
    batch = corpus.filter(pl.col('reason_text').is_in(chosen) & ~pl.col('same_day_conflict'))
    batch.write_parquet(output/'scoring_batch.parquet')
    selected.with_columns(pl.col('reason_text').is_in(chosen).alias('first_batch_selected')).drop('reason_text').write_parquet(output/'selected_members.parquet')
    summary = {'frontier':frontier,'first_batch_unique_texts':len(chosen),'first_batch_rows':batch.height,
        'first_batch_upper_usd':sum(cost_for(input_token_bound(t,format_version=settings['format_version']),settings['max_tokens'],settings) for t in chosen),
        'selected_request_keys':[score_key(t,settings) for t in chosen],
        'scope':'Potential support only; score failures, uncertainty and unavailable labels reduce usable coverage',
        'full_publication_corpus':spec['source'],'api_calls':0}
    (output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--data-root',type=Path,default=Path('data'))
    result = run(**vars(parser.parse_args()))
    print(json.dumps({k:v for k,v in result.items() if k != 'selected_request_keys'}))


if __name__ == '__main__':
    main()
