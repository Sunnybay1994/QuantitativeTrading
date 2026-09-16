from quant.reporting.research_dashboard import artifact_path, is_research_process


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
