from dataclasses import asdict

from quant.factors.library import load_library


def test_auto_library_source_does_not_change_cached_computation_definition(tmp_path):
    content = 'id="example"\nexpr="adj_close"\nfamily="price"\ndirection=1\nsource_ref="test"\n'
    (tmp_path/'existing.toml').write_text(content)
    original = asdict(load_library(tmp_path)[0])
    (tmp_path/'existing.toml').write_text(content+'source="nightly_gp"\n')
    assert asdict(load_library(tmp_path)[0]) == original
    (tmp_path/'auto').mkdir()
    (tmp_path/'auto/new.toml').write_text(content.replace('example', 'new')+'source="nightly_gp"\n')
    assert {d.id for d in load_library(tmp_path)} == {'example', 'new'}
