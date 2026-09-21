import json

import pytest

from quant.data.factor_panels import check_definition


def definition():
    return dict(id="test_factor", expr="rank(close)", direction=1,
                family="nightly_mixed", source_ref="batch_11/search.json")


def test_new_provenance_reuses_panel_without_overwriting_original(tmp_path):
    row = definition()
    check_definition(tmp_path, row["id"], row)
    path = tmp_path / "factors/test_factor/definition.json"
    original, modified = path.read_bytes(), path.stat().st_mtime_ns
    check_definition(tmp_path, row["id"], {**row, "source_ref": "batch_19/search.json"})
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == modified
    assert json.loads(original) == row


@pytest.mark.parametrize("change", [
    {"expr": "rank(volume)"}, {"direction": -1}, {"id": "another"},
    {"family": "other"}, {"new_computational_setting": 1},
])
def test_changed_definition_still_rejected(tmp_path, change):
    row = definition()
    check_definition(tmp_path, row["id"], row)
    with pytest.raises(ValueError, match="Definition changed"):
        check_definition(tmp_path, row["id"], {**row, **change, "source_ref": "new"})
    assert json.loads((tmp_path / "factors/test_factor/definition.json").read_text()) == row
