import json

from quant.data.market_latency import summarize


def test_confirmed_timestamp_excludes_future_and_unconfirmed(tmp_path):
    sample=dict(source='futu',operation='bars',symbol='518880.SH',attempt=1,
                received_at='2026-09-22T13:23:30+08:00',rows=3,elapsed_seconds=.02,
                provider_age_seconds=-30)
    (tmp_path/'report.json').write_text(json.dumps(dict(results=[sample])),encoding='utf-8')
    (tmp_path/'futu_bars_518880.SH_1.json').write_text(json.dumps([
        dict(time_key='2026-09-22 13:22:00'),dict(time_key='2026-09-22 13:23:00'),
        dict(time_key='2026-09-22 13:24:00')]),encoding='utf-8')
    summarize(tmp_path)
    row=json.loads((tmp_path/'report.json').read_text(encoding='utf-8'))['results'][0]
    assert row['future_label_rows']==1
    assert row['conservative_confirmed_label_age_seconds']==90
