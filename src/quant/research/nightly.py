"""Recoverable N1-N6 nightly research with bounded subprocesses and real digests."""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from quant.research.nightly_steps import dump


def wait_bounded(process: subprocess.Popen, *, run: Path, timeout: float,
                 minimum_free_gb: float, interval: float = 30) -> int:
    """Check available space throughout a worker, killing its children on failure."""
    deadline = time.monotonic() + timeout
    try:
        while True:
            code = process.poll()
            if code is not None:
                return code
            free = shutil.disk_usage(run.resolve()).free / (1024**3)
            if free < minimum_free_gb:
                raise RuntimeError(f'Disk guard: {free:.1f} GiB < {minimum_free_gb} GiB')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f'Worker exceeded {timeout:.0f} seconds')
            try:
                return process.wait(timeout=min(interval, remaining))
            except subprocess.TimeoutExpired:
                continue
    except (RuntimeError, TimeoutError, OSError):
        if sys.platform == 'win32':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, check=False)
        if process.poll() is None:
            process.kill()
        process.wait()
        raise


def failed_streak(root: Path, day: dt.date, step: str) -> int:
    streak=0
    # Only real, distinct, completed nightly runs count; no synthetic calendar rows.
    for path in sorted(root.glob('*/summary.json'), reverse=True):
        if path.parent.name>day.isoformat():
            continue
        row=json.loads(path.read_text(encoding='utf-8'))
        state=row.get('steps',{}).get(step,{})
        if state.get('ok') is False:
            streak+=1
        else:
            break
    return streak


def digest(settings: dict, run: Path, summary: dict, *, rewrite_leaderboard: bool = True) -> None:
    from quant.factors.library import load_library
    from quant.reporting.leaderboard import write_leaderboard, DEFAULT_REGISTRY, DEFAULT_LEADERBOARD
    summary['library_after']=len(load_library(Path(settings['library'])))
    summary['finished_at']=dt.datetime.now().isoformat()
    dump(run/'summary.json',summary)
    alerts=[s for s in summary['steps'] if failed_streak(run.parent,dt.date.fromisoformat(run.name),s)>=3]
    lines=[f'# 夜间研究 {run.name}','']
    if alerts:
        lines+=['<strong style="color:red">连续三夜失败：'+', '.join(alerts)+'</strong>','']
    n1=summary['steps'].get('N1',{}).get('result',{})
    n2=summary['steps'].get('N2',{}).get('result',{})
    n4=summary['steps'].get('N4',{}).get('result',{})
    admission = '入库判定未完成'
    if (summary['steps'].get('N4', {}).get('ok')
            and 'admitted' in n4 and 'rejected' in n4):
        admission = f"通过 {n4['admitted']}，拒绝 {n4['rejected']}"
    lines += [f"候选：队列 {n1.get('queued_candidates',0)}，GP {n2.get('candidates',0)}；"
              f"{admission}；"
              f"库规模 {summary['library_before']} → {summary['library_after']}。",'']
    for name,state in summary['steps'].items():
        lines.append(f"- {name}：{'完成' if state['ok'] else '未完成'}；{state.get('error',state.get('result',{}))}")
    monthly = summary['steps'].get('N5', {})
    monthly_result = monthly.get('result', {})
    if monthly.get('ok') and monthly_result.get('completed'):
        model_note = '月度模型已完成，见 N5 产物。'
    elif monthly.get('ok') and monthly_result.get('skipped'):
        model_note = '本夜无需月度重训，最佳模型未重估。'
    else:
        model_note = '月度步骤未完成，后续继续；本夜无完整模型结果。'
    lines += ['', '模型变化：'+model_note]
    (run/'digest.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (run/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    if rewrite_leaderboard:
        write_leaderboard(DEFAULT_REGISTRY,DEFAULT_LEADERBOARD)


def record_deferred(config: Path, reason: str) -> dict:
    """Record a skipped scheduler attempt without changing another writer's results."""
    from quant.factors.library import load_library
    settings = tomllib.loads(config.read_text(encoding='utf-8'))
    now = dt.datetime.now()
    run = Path(settings['output_root'])/now.date().isoformat()
    run.mkdir(parents=True, exist_ok=True)
    attempt = {'date': now.date().isoformat(), 'attempted_at': now.isoformat(), 'reason': reason}
    stamp = now.strftime('%H%M%S_%f')
    dump(run/f'deferred_attempt_{stamp}.json', attempt)
    if not (run/'summary.json').exists():
        summary = {'date': run.name, 'started_at': now.isoformat(), 'execution_deferred': True,
                   'library_before': len(load_library(Path(settings['library']))),
                   'steps': {'scheduler': {'ok': False, 'error': reason}}}
        digest(settings, run, summary, rewrite_leaderboard=False)
    else:
        (run/f'deferred_digest_{stamp}.md').write_text(
            f'# 夜间调度延后 {now.isoformat()}\n\n{reason}\n', encoding='utf-8')
    return attempt


def reopen_empty_evaluation(run: Path, summary: dict, search_result: dict, *, settings: dict|None=None) -> None:
    """A resumed GP can supply candidates after an earlier empty downstream pass."""
    result = run/'N3'/'result.json'
    if not search_result.get('candidates') or not result.exists():
        return
    previous = json.loads(result.read_text(encoding='utf-8'))
    if previous.get('evaluated') != 0:
        return
    if settings and settings.get('compute_allocation'):
        from quant.research.compute_allocation import may_enqueue
        folder=Path(search_result.get('gp_output',str(run/'N2')))/'library'
        if not any(may_enqueue(tomllib.loads(p.read_text(encoding='utf-8')),settings)
                   for p in folder.glob('*.toml')):
            return
    stamp = dt.datetime.now().strftime('%H%M%S_%f')
    for step in ('N3', 'N4'):
        path = run/step/'result.json'
        if path.exists():
            path.rename(path.with_name(f'result_before_gp_resume_{stamp}.json'))
        summary['steps'].pop(step, None)


def work_order(settings: dict, day: dt.date) -> tuple[str, ...]:
    """Resume monthly work before another GP/battery consumes the night's budget."""
    from quant.research.nightly_monthly import pending_month
    if pending_month(settings, Path(settings['output_root'])/day.isoformat()) is not None:
        return ('N1', 'N5', 'N2', 'N3', 'N4')
    return ('N1', 'N2', 'N3', 'N4', 'N5')


def prioritize_queued_battery(order: tuple[str, ...], settings: dict, run: Path) -> tuple[str, ...]:
    """Do not let a resumable GP use every slice ahead of registered candidates.

    Keep monthly prerequisites first. GP candidates arriving after a nonempty
    completed N3 remain in the existing processing queue for the next batch;
    preserve_gp_candidates already owns that handoff.
    """
    if not {'N2','N3','N4'} <= set(order):
        return order
    roots = [run/'candidates']
    if settings.get('queue'):
        roots.extend([Path(settings['queue']),Path(settings['queue'])/'processing'])
    if not any(next(root.glob('*.toml'),None) is not None for root in roots):
        return order
    result = []
    for step in order:
        if step == 'N2':
            result.extend(['N3','N4','N2'])
        elif step not in ('N3','N4'):
            result.append(step)
    return tuple(result)


def execute(config: Path, *, now: dt.datetime|None=None, run_path: Path|None=None,
            session_hours: float|None=None, allocation_config: Path|None=None) -> dict:
    from quant.factors.library import load_library
    settings=tomllib.loads(config.read_text(encoding='utf-8'))
    now=now or dt.datetime.now()
    run=run_path or Path(settings['output_root'])/now.date().isoformat()
    run.mkdir(parents=True,exist_ok=True)
    frozen=run/'config.toml'
    if frozen.exists() and frozen.read_bytes()!=config.read_bytes():
        raise ValueError('Resume requires unchanged nightly configuration')
    if not frozen.exists():
        frozen.write_bytes(config.read_bytes())
    hours=settings['weekend_hours'] if now.weekday()>=5 else settings['weekday_hours']
    summary_path = run/'summary.json'
    summary: dict = json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.exists() else {
        'date': run.name, 'started_at': now.isoformat(),
        'library_before': len(load_library(Path(settings['library']))), 'steps': {}}
    if summary.pop('execution_deferred', False):
        summary['steps'].pop('scheduler', None)
    # Persist before spawning: restarting this night's process never buys a new timebox.
    started = dt.datetime.fromisoformat(summary['started_at'])
    summary.setdefault('deadline_at', (started+dt.timedelta(hours=hours)).isoformat())
    if session_hours is not None:
        if session_hours <= 0:
            raise ValueError('session_hours must be positive')
        summary['session_started_at'] = now.isoformat()
        summary['deadline_at'] = (now+dt.timedelta(hours=session_hours)).isoformat()
    deadline = time.monotonic() + (dt.datetime.fromisoformat(summary['deadline_at'])-now).total_seconds()
    dump(summary_path, summary)
    try:
        from quant.research.nightly_steps import resolve_settings
        settings = resolve_settings(settings, run)
        from quant.research.compute_allocation import apply as apply_allocation
        settings = apply_allocation(settings,allocation_config)
        settings['scheduler_day']=now.date().isoformat()
    except (RuntimeError, ValueError, OSError) as exc:
        summary['steps'] = {'N1': {'ok': False, 'error': f'Input preparation: {exc}'}}
        digest(settings, run, summary)
        return summary
    order = prioritize_queued_battery(work_order(settings, now.date()),settings,run)
    summary['step_order'] = list(order)
    dump(summary_path,summary)
    for step in order:
        from quant.core.capital_window import CapitalPathPause, checkpoint as capital_checkpoint
        try:
            capital_checkpoint()
        except CapitalPathPause as exc:
            summary['steps'][step]={'ok':False,'error':'Time slice yielded for capital-path priority: '+str(exc)}
            dump(summary_path,summary)
            break
        folder=run/step
        folder.mkdir(exist_ok=True)
        result=folder/'result.json'
        if step == 'N2':
            from quant.research.mining_retry import retired_gp_result
            retired = retired_gp_result(folder)
            if retired is not None:
                summary['steps'][step] = {'ok':True,'result':retired}
                dump(summary_path,summary)
                continue
        if step == 'N5' and result.exists():
            from quant.research.nightly_monthly import pending_month
            if pending_month(settings, run, day=now.date()) is not None:
                result.rename(folder/f'result_before_month_{now:%Y%m%d_%H%M%S_%f}.json')
        if result.exists():
            summary['steps'][step]={'ok':True,'result':json.loads(result.read_text(encoding='utf-8'))}
            if step == 'N2':
                from quant.research.nightly_steps import preserve_gp_candidates
                preserve_gp_candidates(settings, run, summary['steps'][step]['result'])
                reopen_empty_evaluation(run, summary, summary['steps'][step]['result'],settings=settings)
            continue
        if step == 'N2':
            from quant.research.compute_allocation import gp_permission
            permission=gp_permission(settings,folder)
            if not permission['allowed']:
                # Scheduling success is explicit, but is not a completed GP trial.
                summary['steps'][step]={'ok':True,'result':{'skipped':True,
                    'evaluated':False,'candidates':0,**permission}}
                dump(summary_path,summary)
                continue
        # A failed GP search must not strand existing queued candidates or monthly work.
        prerequisite = {'N4': 'N3'}.get(step)
        if prerequisite and not summary['steps'].get(prerequisite, {}).get('ok'):
            summary['steps'][step] = {'ok': False, 'error': f'{prerequisite} did not complete'}
            dump(summary_path, summary)
            continue
        free=shutil.disk_usage(run.resolve()).free/(1024**3)
        remaining=deadline-time.monotonic()
        if free<settings['minimum_free_gb'] or remaining<=0:
            summary['steps'][step]={'ok':False,'error':f'Time/disk guard: {remaining:.0f}s, {free:.1f} GiB'}
            continue
        grace = settings.get('slice_checkpoint_seconds', 0)
        if grace and remaining <= grace:
            summary['steps'][step] = {'ok': False, 'error': 'Time slice yielded before starting another worker'}
            continue
        timeout=min(remaining,settings['step_timeout_seconds'][step])
        worker_env = {**os.environ, 'QUANT_SCHEDULER_DAY': now.date().isoformat()}
        allocation_args=(['--allocation-config',settings['compute_allocation_config']]
                         if settings.get('compute_allocation_config') else [])
        worker_env.pop('QUANT_SLICE_SOFT_DEADLINE', None)
        if grace:
            worker_env['QUANT_SLICE_SOFT_DEADLINE'] = str(time.time()+timeout-min(grace, timeout/2))
        try:
            with (folder/'process.log').open('a',encoding='utf-8') as log:
                process=subprocess.Popen([sys.executable,'-m','quant.research.nightly','--config',str(frozen),
                    '--worker',step,'--run',str(run),*allocation_args],stdout=log,stderr=subprocess.STDOUT,
                    env=worker_env)
                code=wait_bounded(process, run=run, timeout=timeout,
                                  minimum_free_gb=settings['minimum_free_gb'])
            if code == 75:
                raise RuntimeError('Time slice yielded; resume retained checkpoints')
            if code or not result.exists():
                raise RuntimeError(f'{step} exit={code}; see {folder}/process.log')
            summary['steps'][step]={'ok':True,'result':json.loads(result.read_text(encoding='utf-8'))}
            if step == 'N2':
                from quant.research.nightly_steps import preserve_gp_candidates
                preserve_gp_candidates(settings, run, summary['steps'][step]['result'])
                reopen_empty_evaluation(run, summary, summary['steps'][step]['result'],settings=settings)
        except (RuntimeError,TimeoutError,OSError) as exc:
            summary['steps'][step]={'ok':False,'error':str(exc)}
        dump(run/'summary.json',summary)
    digest(settings,run,summary)
    return summary


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('configs/research/nightly.toml'))
    parser.add_argument('--worker',choices=['N1','N2','N3','N4','N5'])
    parser.add_argument('--run',type=Path)
    parser.add_argument('--deferred-reason')
    parser.add_argument('--allocation-config',type=Path)
    args=parser.parse_args()
    if args.deferred_reason:
        print(json.dumps(record_deferred(args.config, args.deferred_reason), ensure_ascii=False))
        raise SystemExit(2)
    if args.worker:
        from quant.research import nightly_steps
        from quant.research.run_genetic_factor_search import run_nightly
        if args.run is None:
            parser.error('--worker requires --run')
        settings=tomllib.loads(args.config.read_text(encoding='utf-8'))
        settings=nightly_steps.resolve_settings(settings,args.run)
        from quant.research.compute_allocation import apply as apply_allocation
        settings=apply_allocation(settings,args.allocation_config)
        settings['scheduler_day'] = os.environ.get('QUANT_SCHEDULER_DAY', args.run.name)
        functions={'N1':nightly_steps.ingest,'N2':lambda s,r:run_nightly(s,r/'N2'),
                   'N3':nightly_steps.evaluate,'N4':nightly_steps.admit,'N5':nightly_steps.monthly_models}
        from quant.research.slice_budget import SliceYield
        try:
            result=functions[args.worker](settings,args.run)
        except SliceYield as exc:
            print(str(exc), flush=True)
            raise SystemExit(75) from exc
        dump(args.run/args.worker/'result.json',result)
    else:
        summary = execute(args.config)
        print(json.dumps(summary,ensure_ascii=False,default=str))
        if any(not state.get('ok', False) for state in summary['steps'].values()):
            raise SystemExit(1)


if __name__=='__main__':
    main()
