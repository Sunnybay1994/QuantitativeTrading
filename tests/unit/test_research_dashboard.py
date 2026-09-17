from quant.reporting.research_dashboard import artifact_path, is_research_process


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
