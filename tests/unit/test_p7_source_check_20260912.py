from quant.data.p7_source_check_20260912 import select_samples


def row(code, ann, period, reason='positive', path='raw-a', index=0):
    return dict(ts_code=code, ann_date=ann, end_date=period, change_reason=reason,
                first_ann_date=None, input_path=path, row_index=index)


def test_selection_uses_announcement_year_and_stable_order_not_sentiment():
    rows=[row('002000.SZ','20200102','20191231','negative'),
          row('001000.SZ','20200102','20191231','positive'),
          row('000100.SZ','20200101','20191231',''),
          row('003000.SZ','20200103','20191231','very negative')]
    selected=select_samples(list(reversed(rows)))
    assert [(s['ts_code'],s['selection']) for s in selected]==[
        ('001000.SZ','year_2020'),('002000.SZ','year_2020')]
    assert all(s['first_ann_date'] is None for s in selected)


def test_revision_candidates_require_distinct_dates_and_same_issuer_period():
    rows=[row('A','20141024','20141231',index=0),row('A','20141024','20141231',index=1),
          row('A','20141224','20141231'),row('B','20141025','20141231'),
          row('B','20150125','20141231'),row('C','20141026','20140930'),
          row('C','20150126','20141231')]
    selected=select_samples(rows)
    assert len(selected)==4
    assert [s['pair_id'] for s in selected]==['pair_1','pair_1','pair_2','pair_2']
    assert [s['ann_date'] for s in selected]==['20141024','20141224','20141025','20150125']
