import hashlib
import json

import pytest

from quant.data.factor_panels import check_definition


def test_rediscovered_gp_keeps_original_record_but_accepts_search_family(tmp_path):
    expr='rank(close)'
    identifier='ngp_'+hashlib.sha256(expr.encode()).hexdigest()[:16]
    original=dict(id=identifier,expr=expr,direction=1,family='nightly_mixed',source_ref='first')
    check_definition(tmp_path,identifier,original)
    check_definition(tmp_path,identifier,{**original,'family':'nightly_price_volume','source_ref':'later'})
    path=tmp_path/'factors'/identifier/'definition.json'
    assert json.loads(path.read_text()) == original
    for change in ({'direction':-1},{'expr':'rank(open)'},{'family':'manual'}):
        with pytest.raises(ValueError,match='Definition changed'):
            check_definition(tmp_path,identifier,{**original,**change})


def test_non_content_addressed_factor_still_requires_same_family(tmp_path):
    row=dict(id='manual',expr='rank(close)',direction=1,family='nightly_mixed',source_ref='first')
    check_definition(tmp_path,'manual',row)
    with pytest.raises(ValueError):
        check_definition(tmp_path,'manual',{**row,'family':'nightly_price_volume'})
