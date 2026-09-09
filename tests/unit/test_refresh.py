import datetime as dt
from pathlib import Path

import pytest

from quant.data import refresh


def test_completed_session_cutoff_and_future_date():
    now = dt.datetime(2026, 9, 8, 8, 59, tzinfo=dt.timezone.utc)
    assert refresh.completed_date("today", now) == dt.date(2026, 9, 7)
    assert refresh.completed_date("today", now + dt.timedelta(minutes=1)) == dt.date(2026, 9, 8)
    assert refresh.completed_date("2026-09-04", now) == dt.date(2026, 9, 4)
    with pytest.raises(ValueError, match="future"):
        refresh.completed_date("2026-09-09", now)


def test_failure_stops_before_etf_refresh(monkeypatch, tmp_path: Path):
    config = tmp_path / "refresh.toml"
    config.write_text('etf_config = "configs/research/m2_s2_volatility_target.toml"')
    monkeypatch.setattr(refresh, "latest_session", lambda **kw: dt.date(2026, 9, 8))

    def failed(**kwargs):
        raise RuntimeError("unavailable stock response")

    def unexpected(**kwargs):
        pytest.fail("ETF refresh must not run after a failed stock stage")

    monkeypatch.setattr(refresh, "refresh_stocks", failed)
    monkeypatch.setattr(refresh, "refresh_etfs", unexpected)
    with pytest.raises(RuntimeError, match="unavailable stock response"):
        refresh.run_refresh(to="2026-09-08", data_root=tmp_path, artifact_root=tmp_path,
                            config=config, now=dt.datetime(2026, 9, 8, 20, tzinfo=refresh.SHANGHAI))


def test_refresh_minutes_uses_requested_day_when_mainland_closed(monkeypatch, tmp_path):
    config = tmp_path / "refresh.toml"
    config.write_text('etf_config = "configs/research/m2_s2_volatility_target.toml"')
    monkeypatch.setattr(refresh, "latest_session", lambda **kw: dt.date(2026, 9, 8))
    monkeypatch.setattr(refresh, "refresh_stocks", lambda **kw: {"new_dates": 0, "new_rows": 0})
    monkeypatch.setattr(refresh, "refresh_etfs", lambda **kw: {"new_rows": 0, "new_bar_rows": 0})
    monkeypatch.setattr(refresh, "refresh_limits", lambda **kw: 0)
    dates = []

    def minutes(**kwargs):
        dates.append(kwargs["end"])
        return {"changed_rows": 15, "errors": []}

    monkeypatch.setattr(refresh, "refresh_intraday", minutes)
    result = refresh.run_refresh(to="2026-09-09", data_root=tmp_path, artifact_root=tmp_path,
        config=config, now=dt.datetime(2026, 9, 9, 20, tzinfo=refresh.SHANGHAI))
    assert dates == [dt.date(2026, 9, 9)]
    assert result["message"] == "updated" and result["intraday_changed_rows"] == 15
