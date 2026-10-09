"""The one audited recovery stays discoverable without scanning other recoveries."""
import json
from pathlib import Path
import shutil
import tomllib

import pytest

from quant.reporting import daily_forecast_monitor as monitor
from tests.unit.test_daily_forecast_monitor import setup
from tests.unit.test_model_forecast_scoring import EXIT


CONFIG = Path("configs/research/daily_observation_q2_sue_v2_20260930.toml")
RECOVERY = "daily_recovery/20260929_dependency_fix/model/forecast/summary.json"


def recovery_fixture(setup):
    config, original, root, record = setup
    production = tomllib.loads(CONFIG.read_text(encoding="utf8"))["forecast_monitor"]
    assert production["patterns"] == ["daily/sue_v2/**/model/forecast/summary.json", RECOVERY]
    artifacts = root / "artifacts"
    folder = (artifacts / RECOVERY).parent
    shutil.copytree(original, folder)
    config.write_text(
        "[forecast_monitor]\nauto_trade=false\nselection=" + json.dumps(record["source_selection"])
        + "\nroots=" + json.dumps([str(artifacts)])
        + "\npatterns=" + json.dumps(production["patterns"]) + "\n",
        encoding="utf8",
    )
    return config, folder, root, record


def test_only_named_recovery_enters_production_discovery(setup):
    config, folder, root, _ = recovery_fixture(setup)
    # An identical sibling still must not be discovered or deduplicated.
    sibling = root / "artifacts/daily_recovery/unreviewed_rehearsal/model/forecast"
    shutil.copytree(folder, sibling)
    settings = tomllib.loads(config.read_text(encoding="utf8"))["forecast_monitor"]
    found = monitor.discover(settings=settings, known_through=EXIT)
    assert found["forecasts"] == [str(folder.resolve())]
    assert not found["duplicates"] and not found["errors"] and not found["conflicts"]


@pytest.mark.parametrize("change", [
    {"rehearsal": True}, {"recorded_at": "2026-02-02T09:30:00+08:00"},
])
def test_explicit_recovery_does_not_override_forward_qualification(setup, change):
    config, folder, root, record = recovery_fixture(setup)
    (folder / "summary.json").write_text(json.dumps(record | change), encoding="utf8")
    result = monitor.run(config=config, known_through=EXIT, output=root / "monitor")
    assert result["forward_scored_series_months"] == 0
    assert result["series"][0]["historical_months"] == 1


def test_recovery_scan_retains_prediction_date_validation(setup):
    config, folder, root, record = recovery_fixture(setup)
    (folder / "summary.json").write_text(json.dumps(record | {"as_of": "2026-02-27"}), encoding="utf8")
    result = monitor.run(config=config, known_through=EXIT, output=root / "monitor")
    assert result["status"] == "failed" and result["requires_review"]
    assert "differs from saved record" in result["error"]
