"""Local research dashboard with guarded resume of the existing mining task."""
import argparse
import datetime as dt
import json
import mimetypes
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

import polars as pl

ROOT = Path(__file__).resolve().parents[3]


def is_research_process(command: str) -> bool:
    return bool(re.search(r'-m\s+quant(?:\s+(?:research|factors|paper)\s|\.(?:research|factors|execution)\.)', command))


def research_process_tree(processes: list[dict]) -> list[dict]:
    """Include multiprocessing descendants whose command lacks the quant module."""
    selected = {p['pid'] for p in processes if is_research_process(p.get('command') or '')}
    while True:
        expanded = selected | {p['pid'] for p in processes if p.get('parent_pid') in selected}
        if expanded == selected:
            return [p for p in processes if p['pid'] in selected]
        selected = expanded


def read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def snapshot(root: Path = ROOT, *, include_results: bool = True) -> dict:
    continuous = root/'artifacts/research/continuous'
    status = read(continuous/'status.json')
    run = root/status.get('run', 'artifacts/research/continuous/missing')
    current = read(run/'summary.json')
    if current.get('steps'):
        status = {**status, 'steps': current['steps']}
    progress = read(run/'N4/admission_progress.json')
    batches = []
    for batch in sorted(continuous.glob('batch_*')):
        for summary in batch.glob('????-??-??/summary.json'):
            value = read(summary)
            steps = value.get('steps', {})
            n4 = steps.get('N4', {}).get('result', {})
            batches.append({'name': batch.name, 'date': summary.parent.name,
                            'complete': bool(steps.get('N4', {}).get('ok')),
                            'admitted': n4.get('admitted'), 'rejected': n4.get('rejected'),
                            'report': str(summary.parent.relative_to(root)/'report.md')})
    reports = sorted((root/'artifacts/daily/sue_v2').glob('*/summary.json'))
    daily = read(reports[-1]) if reports else {}
    daily['input_progress'] = read(reports[-1].parent/'model/refresh_progress.json') if reports else {}
    registry = root/'artifacts/registry/experiments.parquet'
    results = []
    result_count = 0
    registry_error = None
    if registry.exists():
        try:
            result_count = pl.scan_parquet(registry).select(pl.len()).collect().item()
            if include_results:
                results = pl.read_parquet(registry).sort('result_time', descending=True).to_dicts()
            for row in results:
                target = Path(row.get('report_path') or '')
                if target.is_absolute():
                    try:
                        row['report_path'] = target.relative_to(root).as_posix()
                    except ValueError:
                        row['report_path'] = ''
        except (OSError, pl.exceptions.PolarsError) as exc:
            registry_error = type(exc).__name__
    from quant.reporting.strategy_review import enrich
    from quant.reporting.daily_attention import attention
    if results:
        results = enrich(results, root)
        from quant.reporting.result_groups import cached_annotations
        results = cached_annotations(results, root)
        from quant.reporting.dashboard_curves import catalog
        available = {(str(Path(e['run_path']).resolve()), e['variant']) for e in catalog(root)
                     if e['kind'] == 'strategy' and e.get('cost_multiplier') == 1.}
        for row in results:
            row['has_period_report'] = (str((root/row['run_path']).resolve()), row['variant']) in available
    runtime = {}
    import tomllib
    runtime_path = root/'configs/runtime.toml'
    if runtime_path.exists():
        runtime = tomllib.loads(runtime_path.read_text(encoding='utf-8')).get('runtime', {})
    processes, process_error = [], None
    try:
        script = "$ErrorActionPreference='Stop'; Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | ForEach-Object { $p=Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; [pscustomobject]@{pid=$_.ProcessId; parent_pid=$_.ParentProcessId; command=$_.CommandLine; cpu_seconds=$p.CPU; memory_mb=[math]::Round($p.WorkingSet64/1MB)} } | ConvertTo-Json -Compress"
        text = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
                              capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        parsed = json.loads(text) if text else []
        processes = parsed if isinstance(parsed, list) else [parsed]
        processes = research_process_tree(processes)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        process_error = type(exc).__name__
    gpu = '不可用'
    try:
        gpu = subprocess.run(['nvidia-smi', '--query-gpu=name,utilization.gpu,memory.used',
                              '--format=csv,noheader'], capture_output=True, text=True,
                             timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    evaluation = read(run/'N3/result.json')
    costs = root/evaluation['batch']/'evaluation/costs' if evaluation.get('batch') else None
    from quant.reporting.mining_status import describe, progress_snapshot, schedule_snapshot, step_snapshot
    scheduler = read(continuous/'scheduler.json')
    mining = describe(status, scheduler, processes, process_error, schedule_snapshot())
    mining['progress'] = progress_snapshot(run)
    mining.update(step_snapshot(status, current, read(run.parent/'attempt.json'),
                                processes, process_error, run))
    return {'updated': dt.datetime.now().isoformat(timespec='seconds'), 'status': status,
            'scheduler': scheduler, 'processes': processes, 'mining': mining,
            'process_error': process_error, 'gpu': gpu, 'device': runtime.get('device', 'cpu'),
            'gp': read(run/'N2/search_progress.json'), 'admission_done': len(progress.get('rows', [])),
            'admission_total': len(progress.get('candidates', [])), 'batches': batches,
            'daily': daily, 'daily_attention': attention(daily), 'daily_report': str(reports[-1].parent.relative_to(root)/'report.md') if reports else '',
            'results': results, 'result_count': result_count, 'registry_error': registry_error,
            'queue_files': len(list((root/'configs/factors/queue').glob('*.toml'))),
            'completed_costs': len(list(costs.glob('*/summary.json'))) if costs else None}


def artifact_path(root: Path, requested: str) -> Path | None:
    path = (root/requested).resolve()
    allowed = (root/'artifacts').resolve()
    return path if path.is_relative_to(allowed) and path.is_file() and path.suffix in {'.md', '.json', '.csv', '.html'} else None


def create_server(port: int) -> ThreadingHTTPServer:
    from quant.reporting.dashboard_cache import SnapshotCache
    from quant.reporting.data_inventory import DataInventory, collection_status
    from quant.reporting.data_sync import task_status
    cache = SnapshotCache(snapshot)
    overview_cache = SnapshotCache(lambda: snapshot(include_results=False))
    inventory = DataInventory(ROOT)
    data_tasks = SnapshotCache(task_status, ttl=15)
    import secrets
    mining_token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            from quant.reporting.mining_control import authorized, resume
            if self.path != '/api/mining/restart' and not self.path.startswith('/api/data/sync/'):
                self.send_error(404)
                return
            if not authorized(self.headers, mining_token, port):
                self.send_error(403)
                return
            try:
                if self.path.startswith('/api/data/sync/'):
                    from quant.reporting.data_sync import sync
                    payload, status = sync(self.path.removeprefix('/api/data/sync/')), 200
                    data_tasks.invalidate()
                else:
                    payload, status = resume(), 200
                    cache.invalidate()
                    overview_cache.invalidate()
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                payload, status = {'state': 'error', 'message': f'请求未确认（{type(exc).__name__}），请检查计划任务及权限'}, 503
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            route = urlparse(self.path)
            if route.path == '/api/data/inventory':
                payload = {**inventory.get(force=route.query == 'refresh=1'), 'collection': collection_status(ROOT)}
                body, mime = json.dumps(payload, ensure_ascii=False).encode('utf-8'), 'application/json'
            elif route.path == '/api/data/tasks':
                try:
                    payload = data_tasks.get()
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    payload = {'tasks': [], 'error': type(exc).__name__}
                body, mime = json.dumps(payload, ensure_ascii=False).encode('utf-8'), 'application/json'
            elif route.path == '/data.js':
                body = Path(__file__).with_name('dashboard_data.js').read_bytes()
                mime = 'text/javascript'
            elif route.path in ('/api/curves', '/api/curve', '/api/periods', '/api/period-report'):
                from quant.reporting.dashboard_curves import catalog, compare, period_report
                try:
                    entries = catalog(ROOT)
                    if route.path == '/api/curves':
                        payload = [{k:v for k,v in e.items() if k not in ('paths','code')} for e in entries]
                    else:
                        query = parse_qs(route.query)
                        ids = query.get('id', [])
                        selected = [e for e in entries if e['id'] in ids]
                        if len(selected) != len(set(ids)):
                            raise ValueError('曲线不存在，请刷新列表')
                        reader = period_report if route.path in ('/api/periods', '/api/period-report') else compare
                        payload = reader(selected,query.get('start',[''])[0],query.get('end',[''])[0])
                    if route.path == '/api/period-report':
                        from quant.reporting.period_metrics import render_html
                        body = render_html(payload, query.get('benchmark', [''])[0]).encode('utf-8')
                        mime = 'text/html'
                    else:
                        body = json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8')
                        mime = 'application/json'
                except (ValueError, OSError, KeyError, pl.exceptions.PolarsError) as exc:
                    body = json.dumps({'error':str(exc)},ensure_ascii=False).encode('utf-8')
                    mime = 'application/json'
            elif route.path == '/api/strategy-report':
                from quant.reporting.strategy_report import render
                try:
                    query = parse_qs(route.query)
                    body = render(ROOT, query.get('run', [''])[0], query.get('variant', [''])[0]).encode('utf-8')
                    mime = 'text/html'
                except (ValueError, OSError, KeyError, pl.exceptions.PolarsError) as exc:
                    body = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                    mime = 'application/json'
            elif route.path == '/api/health':
                body = json.dumps({'service': 'quant-research-dashboard', 'pid': os.getpid()}).encode('utf-8')
                mime = 'application/json'
            elif route.path == '/curves.js':
                body = Path(__file__).with_name('dashboard_curves.js').read_bytes()
                mime = 'text/javascript'
            elif route.path == '/navigation.js':
                body = Path(__file__).with_name('dashboard_navigation.js').read_bytes()
                mime = 'text/javascript'
            elif route.path == '/api/status':
                try:
                    query = parse_qs(route.query)
                    selected_cache = overview_cache if query.get('view') == ['overview'] else cache
                    payload = selected_cache.get(force=query.get('refresh') == ['1'])
                except Exception:
                    self.send_error(503, 'Status refresh unavailable')
                    return
                body = json.dumps(payload, ensure_ascii=False, default=str)
                body = body.replace(': NaN', ': null').replace(': Infinity', ': null').replace(': -Infinity', ': null')
                body, mime = body.encode('utf-8'), 'application/json'
            elif route.path == '/':
                body = Path(__file__).with_name('research_dashboard.html').read_text(encoding='utf-8').replace('__MINING_TOKEN__', mining_token).encode('utf-8')
                mime = 'text/html'
            elif route.path.startswith('/artifact/'):
                path = artifact_path(ROOT, unquote(route.path[len('/artifact/'):]))
                if path is None:
                    self.send_error(404)
                    return
                body = path.read_bytes()
                mime = mimetypes.guess_type(path.name)[0] or 'text/plain'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime+'; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            if route.path == '/api/period-report' and mime == 'text/html':
                self.send_header('Content-Disposition', 'attachment; filename="strategy-period-report.html"')
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    print(f'Research dashboard: http://127.0.0.1:{args.port}', flush=True)
    create_server(args.port).serve_forever()


if __name__ == '__main__':
    main()
