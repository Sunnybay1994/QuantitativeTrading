from quant.reporting.research_dashboard import artifact_path, is_research_process


def test_overview_counts_registry_without_result_enrichment(tmp_path, monkeypatch):
    import subprocess
    import polars as pl
    from quant.reporting import research_dashboard, strategy_review, mining_status

    registry = tmp_path/'artifacts/registry/experiments.parquet'
    registry.parent.mkdir(parents=True)
    pl.DataFrame({'variant': ['a', 'b', 'c']}).write_parquet(registry)
    monkeypatch.setattr(strategy_review, 'enrich', lambda *a: (_ for _ in ()).throw(
        AssertionError('Overview must not load result evidence')))
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: type('Result', (), {'stdout': '[]'})())
    monkeypatch.setattr(mining_status, 'schedule_snapshot', lambda: {})
    result = research_dashboard.snapshot(tmp_path, include_results=False)
    assert result['result_count'] == 3 and result['results'] == []


def test_overview_route_has_independent_cache_and_inventory_is_lazy(monkeypatch):
    import json
    import threading
    from urllib.request import urlopen
    from quant.reporting import research_dashboard, data_inventory

    calls = []
    monkeypatch.setattr(research_dashboard, 'snapshot', lambda **kw:
        calls.append(kw.get('include_results', True)) or {'results': [], 'result_count': 3})
    monkeypatch.setattr(data_inventory.DataInventory, 'get', lambda *a, **kw:
        (_ for _ in ()).throw(AssertionError('Do not scan inventory on startup')))
    server = research_dashboard.create_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        for path in ('/api/status?view=overview', '/api/status?view=overview',
                     '/api/status?view=results', '/api/status?view=overview&refresh=1'):
            with urlopen(base+path, timeout=3) as response:
                assert json.load(response)['result_count'] == 3
        assert calls == [False, True, False]
        with urlopen(base+'/navigation.js', timeout=3) as response:
            assert b'dashboard:page' in response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_multiprocessing_descendants_are_counted_but_unrelated_python_is_not():
    from quant.reporting.research_dashboard import research_process_tree
    rows = [
        {'pid': 3, 'parent_pid': 2, 'command': 'python -c spawn_main'},
        {'pid': 2, 'parent_pid': 1, 'command': 'python -c spawn_main'},
        {'pid': 1, 'parent_pid': 0, 'command': 'python -m quant research mining'},
        {'pid': 4, 'parent_pid': 0, 'command': 'python -m quant report dashboard'},
        {'pid': 5, 'parent_pid': 4, 'command': 'python -c spawn_main'},
    ]
    assert {p['pid'] for p in research_process_tree(rows)} == {1, 2, 3}


def test_dashboard_does_not_count_itself_as_mining():
    assert not is_research_process('python -m quant report dashboard')
    assert not is_research_process('python -m quant.reporting.research_dashboard')
    assert is_research_process('python -m quant research mining --slice-hours 2')
    assert is_research_process('python -m quant.research.nightly --worker N4')


def test_artifact_route_cannot_read_outside_artifacts(tmp_path):
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    report = artifacts / 'report.md'
    report.write_text('evidence')
    (tmp_path / 'secret.json').write_text('{}')
    assert artifact_path(tmp_path, 'artifacts/report.md') == report
    assert artifact_path(tmp_path, 'artifacts/../secret.json') is None
    assert artifact_path(tmp_path, str(tmp_path / 'secret.json')) is None
    assert artifact_path(tmp_path, 'artifacts/missing.json') is None
