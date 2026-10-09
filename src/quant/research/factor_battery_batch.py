"""Batch statistical evaluation for the factor battery, with reusable yearly inputs."""
import argparse
import datetime as dt
import json
import os
import time
import tomllib
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import polars as pl

from quant.data.factor_battery_inputs import read_battery_factor_year, read_battery_year
from quant.data.factor_panels import available_sessions
from quant.factors.library import FactorDefinition, load_library
from quant.research.factor_battery_evaluation import evaluate_factor_year, summarize_factor_statistics


def prepare_inputs(*, data_root: Path, settings: dict, as_of: dt.date, output: Path) -> list[int]:
    years = list(range(settings["start"].year,as_of.year+1))
    for year in years:
        folder = output/"inputs"/str(year)
        if all((folder/name).is_file() for name in ("universe.parquet","monthly_labels.parquet")):
            continue
        universe,monthly = read_battery_year(data_root=data_root,
            refresh_config=Path(settings["data"]["refresh_config"]),
            limits_snapshot=settings["data"]["limits_snapshot"],
            start=max(settings["start"],dt.date(year,1,1)),end=min(as_of,dt.date(year,12,31)),known_through=as_of,
            **{key:settings["universe"][key] for key in ("minimum_listing_days","amount_window_sessions",
                "amount_exclude_bottom_fraction")})
        folder.mkdir(parents=True,exist_ok=True)
        universe.write_parquet(folder/"universe.parquet")
        monthly.write_parquet(folder/"monthly_labels.parquet")
        print(json.dumps({"input_year":year,"stock_days":universe.height,
                          "eligible":universe["eligible"].sum()}),flush=True)
    return years


def _factor_worker(data_root: Path, definition: FactorDefinition, settings: dict,
                   as_of: dt.date, output: Path, years: list[int]) -> dict:
    folder = output/"factors"/definition.id
    result_path = folder/"statistics.json"
    files = ("daily_ic.parquet","monthly_ic.parquet","monthly_groups.parquet","monthly_scores.parquet","persistence.parquet")
    if result_path.is_file() and all((folder/name).is_file() for name in files):
        cached=json.loads(result_path.read_text(encoding="utf-8"))
        if cached["definition"]!=asdict(definition):
            raise ValueError("Choose a new output directory for changed factor definitions")
        return cached
    began=time.perf_counter()
    parts=[]
    for year in years:
        input_folder=output/"inputs"/str(year)
        values,labels=read_battery_factor_year(data_root,factor=definition.id,year=year,known_through=as_of)
        parts.append(evaluate_factor_year(universe=pl.read_parquet(input_folder/"universe.parquet"),
            monthly_labels=pl.read_parquet(input_folder/"monthly_labels.parquet"),values=values,
            daily_labels=labels,direction=definition.direction,settings=settings))
    summaries,persistence=summarize_factor_statistics(parts,sessions=available_sessions(data_root,as_of),settings=settings)
    folder.mkdir(parents=True,exist_ok=True)
    for name in ("daily_ic","monthly_ic","monthly_groups","monthly_scores"):
        pl.concat([getattr(part,name) for part in parts]).write_parquet(folder/f"{name}.parquet")
    persistence.write_parquet(folder/"persistence.parquet")
    result={"definition":asdict(definition),"statistics":summaries,"seconds":time.perf_counter()-began}
    result_path.write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result


def battery_snapshot(config_bytes: bytes, *, as_of: dt.date, selected: str) -> bytes:
    """Merge existing run metadata while preserving legacy base-config bytes."""
    settings = tomllib.loads(config_bytes.decode('utf-8'))
    if 'run' not in settings:
        return config_bytes + f'\n[run]\nas_of = {as_of.isoformat()}\nselected = {json.dumps(selected)}\n'.encode('utf-8')
    from quant.data.nightly_month_inputs import _toml_text
    settings['run'] = {**settings['run'], 'as_of': as_of, 'selected': selected}
    return _toml_text(settings).encode('utf-8')


def run_statistics(*, data_root: Path, config: Path, library: Path, as_of: dt.date,
                   output: Path, selected: str = "all", workers: int = 4) -> dict:
    """Compute all registered statistics; admission and executable costs follow."""
    config_bytes=config.read_bytes()
    settings=tomllib.loads(config_bytes.decode("utf-8"))
    snapshot=battery_snapshot(config_bytes, as_of=as_of, selected=selected)
    if workers<1 or as_of<settings["start"]:
        raise ValueError("Invalid battery execution range or worker count")
    calendar=available_sessions(data_root,as_of+dt.timedelta(days=40))
    index=calendar.index(as_of) if as_of in calendar else -1
    if index<0 or index+1>=len(calendar) or calendar[index+1].month==as_of.month:
        raise ValueError("Battery as-of must be a completed exchange month end")
    output.mkdir(parents=True,exist_ok=True)
    saved=output/"battery.toml"
    if saved.is_file() and saved.read_bytes()!=snapshot:
        raise ValueError("Choose a new output directory for changed battery settings")
    if not saved.exists():
        saved.write_bytes(snapshot)
    definitions=load_library(library,selected)
    years=prepare_inputs(data_root=data_root,settings=settings,as_of=as_of,output=output)
    results=[]
    if workers==1:
        for definition in definitions:
            result=_factor_worker(data_root,definition,settings,as_of,output,years)
            results.append(result)
            print(json.dumps({"factor":definition.id,"seconds":result["seconds"],"completed":len(results)}),flush=True)
    else:
        # Bound each process's native pools to avoid nested oversubscription.
        os.environ["POLARS_MAX_THREADS"]="4"
        for variable in ("OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","OMP_NUM_THREADS"):
            os.environ[variable]="1"
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures={pool.submit(_factor_worker,data_root,d,settings,as_of,output,years):d.id for d in definitions}
            for future in as_completed(futures):
                result=future.result()
                results.append(result)
                print(json.dumps({"factor":futures[future],"seconds":result["seconds"],"completed":len(results)}),flush=True)
    rows=[]
    for result in sorted(results,key=lambda r:r["definition"]["id"]):
        for row in result["statistics"]:
            rows.append({"factor":result["definition"]["id"],"family":result["definition"]["family"],
                         "direction":result["definition"]["direction"],**row})
    table=pl.from_dicts(rows,infer_schema_length=None)
    table.write_parquet(output/"statistics.parquet")
    summary={"as_of":str(as_of),"factors":len(definitions),"variant_rows":len(rows),"years":len(years),
        "output":str(output),"scope":"statistical inputs for scorecard; costs and admission not yet applied"}
    (output/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    return summary


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of",type=dt.date.fromisoformat,required=True)
    parser.add_argument("--data-root",type=Path,default=Path("data"))
    parser.add_argument("--config",type=Path,default=Path("configs/factors/battery.toml"))
    parser.add_argument("--library",type=Path,default=Path("configs/factors/library"))
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--factors",default="all")
    parser.add_argument("--workers",type=int,default=4)
    args=parser.parse_args()
    print(json.dumps(run_statistics(data_root=args.data_root,config=args.config,library=args.library,
        as_of=args.as_of,output=args.output,selected=args.factors,workers=args.workers)),flush=True)


if __name__=="__main__":
    main()
