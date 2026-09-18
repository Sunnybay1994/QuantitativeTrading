from quant.reporting.sample_provenance import config_evidence, describe_sample


def test_mutable_config_cannot_certify_old_run(tmp_path):
    path = tmp_path/'model.toml'
    path.write_text('[walk_forward]\ntest_start=2015-01-01\ntest_end=2026-08-31')
    assert config_evidence(path, tmp_path)['sources'] == []


def test_frozen_configuration_is_not_actual_training_or_unseen_test(tmp_path):
    path = tmp_path/'artifacts'/'model.toml'
    path.parent.mkdir()
    path.write_text('[walk_forward]\nhistory_start=2010-01-01\ntraining="expanding_history"\n'
                    'test_start=2015-01-01\ntest_end=2026-08-31')
    evidence = config_evidence(path, tmp_path)
    result = describe_sample({'kind': 'strategy', 'sample_evidence': evidence}, ['2019-01-02', '2026-08-31'])
    assert '2010-01-01' in result['lines'][0]
    assert '实际训练首末日未' in result['lines'][0]
    assert '2015-01-01' in result['lines'][1]
    assert '2019-01-02' in result['lines'][2]
    assert '未提供独立性证明' in result['lines'][3]
    assert result['sources'] == [str(path)]


def test_paper_and_missing_evidence_are_explicit():
    result = describe_sample({'kind': 'paper', 'sample_evidence': None}, ['2026-09-14', '2026-09-17'])
    assert result['lines'][0].startswith('未知')
    assert '模拟净值记录覆盖' in result['lines'][2]
    assert '未在本页面核验' in result['lines'][3]
