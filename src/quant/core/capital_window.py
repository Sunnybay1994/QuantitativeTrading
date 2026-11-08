"""Cooperative background-writer yield for the existing evening paper-order path."""
import argparse
import datetime as dt
import json
import os
import uuid
from pathlib import Path

TZ = dt.timezone(dt.timedelta(hours=8))
PAUSE = Path('artifacts/runtime/capital_path_pause.json')


class CapitalPathPause(RuntimeError):
    """A completed background batch is durable; release locks and resume later."""


def reason(*, now=None, data_root=Path('data'), pause_path=PAUSE):
    clock = (now or dt.datetime.now(TZ)).astimezone(TZ)
    if not dt.time(20,30) <= clock.time() < dt.time(23,30):
        return None
    import polars as pl
    try:
        opened=[]
        for market in ('SH','SZ'):
            frame = pl.read_parquet(data_root/f'clean/trade_calendar/market={market}/data.parquet')
            day = frame.filter(pl.col('date')==clock.date())
            if day.height != 1 or day.schema['is_open'] != pl.Boolean:
                raise ValueError('Require one actual exchange session')
            opened.append(day['is_open'].item())
        if opened == [False,False]:
            return None
        if opened != [True,True]:
            raise ValueError('Exchange calendars disagree')
    except (OSError, ValueError, KeyError, pl.exceptions.PolarsError):
        return 'capital_window_calendar_unavailable'
    if pause_path.exists():
        try:
            saved = json.loads(pause_path.read_text(encoding='utf-8-sig'))
            start, end = map(dt.datetime.fromisoformat, (saved['requested_at'], saved['expires_at']))
            if start.tzinfo is None or end.tzinfo is None or not 0 < (end-start).total_seconds() <= 600:
                raise ValueError('Invalid bounded pause request')
            if start <= clock < end:
                return 'capital_path_pause_requested'
        except (OSError, ValueError, KeyError, TypeError):
            # A corrupt mutable hint cannot stop background work indefinitely.
            try:
                if 0 <= clock.timestamp()-pause_path.stat().st_mtime < 600:
                    return 'invalid_capital_pause_request'
            except OSError:
                pass
    return 'capital_path_2030_2330'


def checkpoint(**kwargs):
    if os.environ.get('QUANT_BACKGROUND_WRITER') == '1':
        why = reason(**kwargs)
        if why:
            raise CapitalPathPause(why)


def request(*, target, pause_path=PAUSE, now=None):
    clock = now or dt.datetime.now(TZ)
    dt.date.fromisoformat(target)
    pause_path.parent.mkdir(parents=True,exist_ok=True)
    value = dict(request_id=uuid.uuid4().hex, requested_at=clock.isoformat(),
        expires_at=(clock+dt.timedelta(seconds=600)).isoformat(), target=target, pid=os.getpid(), auto_trade=False)
    temporary = pause_path.with_suffix('.'+value['request_id']+'.tmp')
    temporary.write_text(json.dumps(value),encoding='utf-8')
    temporary.replace(pause_path)
    return value


def release(request_id, *, pause_path=PAUSE):
    if pause_path.exists():
        try:
            saved = json.loads(pause_path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            return
        if saved.get('request_id') == request_id:
            pause_path.unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['check','request','release'])
    parser.add_argument('--to')
    parser.add_argument('--request-id')
    args=parser.parse_args()
    if args.mode=='request':
        print(json.dumps(request(target=args.to)))
    elif args.mode=='release':
        release(args.request_id)
    else:
        why=reason()
        print(json.dumps(dict(status='paused' if why else 'ready',reason=why,auto_trade=False)))
        raise SystemExit(75 if why else 0)


if __name__=='__main__':
    main()
