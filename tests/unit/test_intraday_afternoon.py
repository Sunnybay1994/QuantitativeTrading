import datetime as dt

from quant.research.intraday_afternoon import execution_bar, signal, valid_day, quality_issues


def test_signal_cannot_read_future_bars():
    at=dt.datetime(2026,9,21,13,30)
    rows=[dict(bar_end=at,open=10,close=11,amount=1050,volume=100)]
    assert signal(rows,at)
    rows.append(dict(bar_end=at+dt.timedelta(minutes=5),open=11,close=1,amount=100000,volume=100))
    assert signal(rows,at)
    assert not signal(rows,at-dt.timedelta(minutes=5))


def test_execution_includes_confirmation_and_manual_delay():
    at=dt.datetime(2026,9,21,13,30)
    rows=[dict(bar_start=at+dt.timedelta(minutes=i)) for i in range(7)]
    assert execution_bar(rows,at,120,63)['bar_start']==at+dt.timedelta(minutes=4)
    assert execution_bar(rows,at,180,63)['bar_start']==at+dt.timedelta(minutes=5)
    assert execution_bar(rows,at,600,63) is None


def test_missing_duplicate_or_invalid_sessions_rejected():
    rows=[]
    for hour in (9,10,11,13,14):
        for minute in range(0,60,5):
            if (hour==9 and minute<30) or (hour==11 and minute>=30):
                continue
            start=dt.datetime(2026,9,21,hour,minute)
            rows.append(dict(bar_start=start,bar_end=start+dt.timedelta(minutes=5),open=10,high=11,low=9,close=10,volume=100,amount=1000))
    assert valid_day(rows,5)
    assert quality_issues(rows,5,'2026-09-21')==[]
    assert not valid_day(rows[:-1],5)
    assert not valid_day(rows+[rows[-1]],5)
    rows[0]['amount']=2000
    assert not valid_day(rows,5)
    issues=quality_issues(rows,5,'2026-09-21')
    assert [r['reason'] for r in issues]==['amount_implied_price_outside_bar']
    rows[1]['volume']=0
    assert 'nonpositive_volume' in [r['reason'] for r in quality_issues(rows,5,'2026-09-21')]
