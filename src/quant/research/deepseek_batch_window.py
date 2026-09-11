"""Off-peak admission for non-urgent DeepSeek research requests.

Official pricing checked 2026-09-12: Monday-Friday 01-04 and 06-10 UTC
are peak hours. https://api-docs.deepseek.com/quick_start/pricing/
This schedules requests; budget accounting still uses configured peak prices.
"""
import datetime as dt


def request_window(now: dt.datetime | None = None) -> dict:
    instant = now if now is not None else dt.datetime.now(dt.timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('Request window requires a timezone-aware timestamp')
    instant = instant.astimezone(dt.timezone.utc)
    if instant.weekday() < 5:
        for start, end in ((1, 4), (6, 10)):
            if start <= instant.hour < end:
                return {'allowed': False, 'next_allowed_at': instant.replace(
                    hour=end, minute=0, second=0, microsecond=0).isoformat()}
    return {'allowed': True, 'next_allowed_at': instant.isoformat()}
