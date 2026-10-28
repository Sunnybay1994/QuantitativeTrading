"""Published US cash-equity sessions, bounded to the verified calendar years."""
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import tomllib

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / 'configs/data/us_sessions.toml'


def _close(spec: dict, day: dt.date) -> dt.time | None:
    if not spec['valid_from'] <= day <= spec['valid_until']:
        raise ValueError(f'US session calendar does not cover {day}; update the published schedule')
    if day.weekday() >= 5 or day in spec['closed_dates']:
        return None
    return spec['early_close'] if day in spec['early_dates'] else spec['regular_close']


def session_close(day: dt.date, *, config: Path = DEFAULT_CONFIG) -> dt.time | None:
    return _close(tomllib.loads(config.read_text(encoding='utf-8')), day)


def expected_bars(day: dt.date, *, config: Path = DEFAULT_CONFIG) -> int:
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    close = _close(spec, day)
    if close is None:
        return 0
    return int((dt.datetime.combine(day, close)-dt.datetime.combine(day, spec['open']))
               .total_seconds()/60)


def latest_closed(*, through: dt.date, now: dt.datetime, config: Path = DEFAULT_CONFIG) -> dt.date:
    if now.tzinfo is None:
        raise ValueError('US session selection requires an aware timestamp')
    spec = tomllib.loads(config.read_text(encoding='utf-8'))
    zone = ZoneInfo(spec['timezone'])
    local = now.astimezone(zone)
    day = min(through, local.date())
    while True:
        close = _close(spec, day)
        if close is not None:
            ready = dt.datetime.combine(day, close, tzinfo=zone) + dt.timedelta(
                minutes=spec['settlement_minutes'])
            if ready <= local:
                return day
        day -= dt.timedelta(days=1)
