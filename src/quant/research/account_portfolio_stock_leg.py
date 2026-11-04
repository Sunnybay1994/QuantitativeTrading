"""Replay frozen Q10 at R1's capital using the existing yearly account engine."""
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import tomllib

import polars as pl

from quant.backtest.share_exchanges import validate_exchanges
from quant.data.factor_panels import available_sessions
from quant.research.factor_battery_costs import run_cost_plans
from quant.research.factor_battery_cost_report import load_cost_history
from quant.research.run_multifactor_replay import model_target_plans


def run(*, config: Path, output: Path, data_root: Path = Path('data'), resume=False):
    payload = config.read_bytes()
    spec = tomllib.loads(payload.decode('utf-8'))
    if spec['auto_trade'] is not False or spec['capital_cny'] != 300000:
        raise ValueError('Require preregistered 300k paper-only account')
    if output.exists() and not resume:
        raise FileExistsError('Existing replay requires explicit --resume')
    output.mkdir(parents=True,exist_ok=True)
    source, predictions = Path(spec['stock_source']), Path(spec['predictions'])
    battery = (source/'battery.toml').read_text(encoding='utf-8')
    battery = re.sub(r'(?m)^initial_cash\s*=.*$', 'initial_cash = 300000', battery)
    settings = tomllib.loads(battery)
    if settings['portfolio']['initial_cash'] != spec['capital_cny']:
        raise ValueError('Failed to freeze registered capital')
    model = tomllib.loads((predictions/'model.toml').read_text(encoding='utf-8'))
    settings['share_exchanges'] = validate_exchanges(tomllib.loads(
        (source/'share_exchanges.toml').read_text(encoding='utf-8'))['share_exchanges'])
    context = {'config.toml':payload, 'battery.toml':battery.encode(),
        'model.toml':(predictions/'model.toml').read_bytes(),
        'share_exchanges.toml':(source/'share_exchanges.toml').read_bytes()}
    for name,content in context.items():
        path=output/name
        if path.exists() and path.read_bytes()!=content:
            raise ValueError(f'Frozen replay changed: {name}')
        if not path.exists():
            path.write_bytes(content)
    sessions = available_sessions(data_root,model['walk_forward']['test_end']+dt.timedelta(days=40))
    scores = pl.read_parquet(predictions/'monthly_predictions.parquet')
    name,targets = model_target_plans(scores,model=model,sessions=sessions)['lightgbm_top50']
    snapshot = json.loads((source/'summary.json').read_text(encoding='utf-8'))['execution_snapshot']
    receipt={'status':'running','auto_trade':False,'account_portfolio_replayed':False,
        'capital_cny':300000,'execution_snapshot':snapshot,'rows':[]}
    def save():
        (output/'stock_leg_status.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    save()
    manifest = {str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in
        [config,source/'battery.toml',source/'summary.json',predictions/'model.toml',
         predictions/'monthly_predictions.parquet',Path(__file__)]}
    if not resume:
        (output/'source_hashes.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    elif json.loads((output/'source_hashes.json').read_text(encoding='utf-8'))!=manifest:
        raise ValueError('Source provenance differs from frozen run')
    try:
        # Keep original cash-only years so the first signal sees the same prior
        # account close. R1 measurement subsequently starts at first stock holding.
        run_cost_plans(settings=copy.deepcopy(settings),plans={'budgeted':(name,targets)},
            sessions=sessions,output=output,data_root=data_root,execution_snapshot=snapshot,
            factor='account_portfolio_v1_q10_300k',start=model['walk_forward']['test_start'],
            turnover_budgets={'budgeted':.5},resume=resume)
        for cost in spec['cost_multipliers']:
            nav,trades = load_cost_history(output,'budgeted',cost,spec['end'])
            active=nav.filter(pl.col('market_value')>0)['date'].min()
            if active is None or active.year != 2019:
                raise ValueError('R1 requires the original continuous stock interval starting in 2019')
            folder=output/f'cost_{cost:g}'
            folder.mkdir(exist_ok=True)
            nav.write_parquet(folder/'nav.parquet')
            trades.write_parquet(folder/'trades.parquet')
            receipt['rows'].append({'cost_multiplier':cost,'active_start':str(active),
                'last_date':str(nav['date'][-1]),'sessions':nav.height,'trades':trades.height})
        receipt['status']='stock_leg_complete'
    except Exception as exc:
        receipt.update(status='failed',error=f'{type(exc).__name__}: {exc}')
        save()
        raise
    save()
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('configs/research/account_portfolio_v1.toml'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    print(json.dumps(run(config=args.config,output=args.output,resume=args.resume)))
