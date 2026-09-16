"""Local, read-only research dashboard backed by saved runs and live processes."""
import argparse
import datetime as dt
import json
import mimetypes
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import polars as pl

ROOT = Path(__file__).resolve().parents[3]


def is_research_process(command: str) -> bool:
    return bool(re.search(r'-m\s+quant(?:\s+(?:research|factors|paper)\s|\.(?:research|factors|execution)\.)', command))


def read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def snapshot(root: Path = ROOT) -> dict:
    continuous = root/'artifacts/research/continuous'
    status = read(continuous/'status.json')
    run = root/status.get('run', 'artifacts/research/continuous/missing')
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
    registry = root/'artifacts/registry/experiments.parquet'
    results = []
    registry_error = None
    if registry.exists():
        try:
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
    runtime = {}
    import tomllib
    runtime_path = root/'configs/runtime.toml'
    if runtime_path.exists():
        runtime = tomllib.loads(runtime_path.read_text(encoding='utf-8')).get('runtime', {})
    processes, process_error = [], None
    try:
        script = "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'quant.*(research|factors|paper)' } | ForEach-Object { $p=Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; [pscustomobject]@{pid=$_.ProcessId; command=$_.CommandLine; cpu_seconds=$p.CPU; memory_mb=[math]::Round($p.WorkingSet64/1MB)} } | ConvertTo-Json -Compress"
        text = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
                              capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        parsed = json.loads(text) if text else []
        processes = parsed if isinstance(parsed, list) else [parsed]
        processes = [p for p in processes if is_research_process(p.get('command') or '')]
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
    return {'updated': dt.datetime.now().isoformat(timespec='seconds'), 'status': status,
            'scheduler': read(continuous/'scheduler.json'), 'processes': processes,
            'process_error': process_error, 'gpu': gpu, 'device': runtime.get('device', 'cpu'),
            'gp': read(run/'N2/search_progress.json'), 'admission_done': len(progress.get('rows', [])),
            'admission_total': len(progress.get('candidates', [])), 'batches': batches,
            'daily': daily, 'daily_report': str(reports[-1].parent.relative_to(root)/'report.md') if reports else '',
            'results': results, 'registry_error': registry_error,
            'queue_files': len(list((root/'configs/factors/queue').glob('*.toml'))),
            'completed_costs': len(list(costs.glob('*/summary.json'))) if costs else None}


def artifact_path(root: Path, requested: str) -> Path | None:
    path = (root/requested).resolve()
    allowed = (root/'artifacts').resolve()
    return path if path.is_relative_to(allowed) and path.is_file() and path.suffix in {'.md', '.json', '.csv', '.html'} else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    cache = {'at': 0., 'body': b''}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = urlparse(self.path)
            if route.path == '/api/status':
                if route.query == 'refresh=1' or time.monotonic() - cache['at'] > 15:
                    payload = snapshot()
                    # Dates and non-finite experimental values must remain valid JSON.
                    body = json.dumps(payload, ensure_ascii=False, default=str)
                    body = body.replace(': NaN', ': null').replace(': Infinity', ': null').replace(': -Infinity', ': null')
                    cache.update(at=time.monotonic(), body=body.encode('utf-8'))
                body, mime = cache['body'], 'application/json'
            elif route.path == '/':
                body = Path(__file__).with_name('research_dashboard.html').read_bytes()
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
            self.end_headers()
            self.wfile.write(body)

    print(f'Research dashboard: http://127.0.0.1:{args.port}', flush=True)
    HTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
