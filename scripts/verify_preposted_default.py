"""Compare disabled limit matching with the exact pre-R2 simulator source."""
import hashlib
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import types

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from quant.backtest.daily_simulator import simulate_daily_targets
from quant.backtest.rules import DailyMarketState
from tests.unit.test_daily_simulator import (
    SESSION,STOCK,_calendar,_instruments,_bar,_target,_initial_position,_stock_costs_scaled,_etf_costs,
)


def digest(frame):
    buffer=io.BytesIO()
    frame.write_parquet(buffer)
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-current',type=Path)
    parser.add_argument('--full-baseline',type=Path,default=Path('artifacts/research/account_portfolio_q10_300k_20261104_01'))
    cli=parser.parse_args()
    ref='0f31e537'
    source=subprocess.check_output(['git','show',ref+':src/quant/backtest/daily_simulator.py'])
    old=types.ModuleType('pre_r2_daily_simulator')
    sys.modules[old.__name__]=old
    exec(compile(source,'pre_r2_daily_simulator.py','exec'),old.__dict__)
    cases=[]
    for side in ('BUY','SELL'):
        for cost in (.5,1.,2.):
            args=dict(calendar=_calendar(SESSION),bars=_bar(open_price=10.,close_price=10.5),
                scheduled_targets=_target(1. if side=='BUY' else 0.),instruments=_instruments(),
                market_states={(SESSION,STOCK):DailyMarketState()},initial_cash=10000.,
                initial_positions=_initial_position(quantity=200,settled_quantity=200) if side=='SELL' else None,
                etf_costs=_etf_costs(),stock_costs=_stock_costs_scaled(cost),strategy='m2-u1')
            baseline=old.simulate_daily_targets(**args)
            current=simulate_daily_targets(**args)
            explicit_none=simulate_daily_targets(**args,preposted_limits=None)
            hashes={key:digest(getattr(baseline,key)) for key in ('nav','positions','trades','rejections')}
            for key,value in hashes.items():
                assert digest(getattr(current,key))==value,(side,cost,key)
                assert digest(getattr(explicit_none,key))==value,(side,cost,key,'None')
            cases.append({'side':side,'cost_multiplier':cost,'parquet_hashes':hashes})
    output=Path('artifacts/research/top15_limit_default_verification_20261104')
    output.mkdir(parents=True,exist_ok=True)
    result={'baseline_commit':ref,'baseline_source_sha256':hashlib.sha256(source).hexdigest(),
        'cases':cases,'default_and_explicit_none_byte_identical':True}
    if cli.full_current:
        complete=json.loads((cli.full_current/'stock_leg_status.json').read_text())
        assert complete['status']=='stock_leg_complete'
        paths=[*cli.full_baseline.glob('budgeted/cost_*/*/*.parquet'),
               *cli.full_baseline.glob('budgeted/cost_*/*/account.json'),
               *cli.full_baseline.glob('cost_*/*.parquet')]
        hashes={}
        for baseline in paths:
            relative=baseline.relative_to(cli.full_baseline)
            current=cli.full_current/relative
            expected=hashlib.sha256(baseline.read_bytes()).hexdigest()
            assert hashlib.sha256(current.read_bytes()).hexdigest()==expected,str(relative)
            hashes[str(relative)]=expected
        assert len(hashes)>=100
        result['full_replay']={'files_compared':len(hashes),'economic_files_and_account_checkpoints_byte_identical':True,
            'baseline':str(cli.full_baseline),'current':str(cli.full_current),'hashes':hashes,
            'purpose':'Verification only; not a new strategy result; wall-clock metadata excluded'}
    (output/'summary.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'cases':len(cases),'default_and_explicit_none_byte_identical':True,'output':str(output)}))


if __name__=='__main__':
    main()
