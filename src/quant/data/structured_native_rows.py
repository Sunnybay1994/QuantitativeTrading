"""Keep supplier non-record messages in raw, outside consumable margin rows."""
import hashlib
import json

import polars as pl

MARGIN_AMOUNTS=('rzye','rqye','rzrqye','rzmre','rzche')


def native_row_id(row):
    return hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def split_native_rows(table,frame):
    if table!='margin_detail' or frame.is_empty():
        return frame,frame.head(0)
    # Bare six-digit and special T-prefixed identifiers occur in native history.
    invalid=~pl.col('ts_code').str.contains(r'^T?[0-9]{6}(?:\.(?:SH|SZ|BJ))?$').fill_null(False)
    candidates=frame.filter(invalid)
    if candidates.is_empty():return frame,candidates
    marker=pl.col('ts_code').str.contains(r'^(?:没有找到符合条件的数据！(?:\.(?:SH|SZ|BJ))?|日期[：:][0-9]{4}-[0-9]{2}-[0-9]{2}(?:\.(?:SH|SZ|BJ))?)$').fill_null(False)
    missing=pl.all_horizontal([pl.col(c).is_null() for c in MARGIN_AMOUNTS]) if set(MARGIN_AMOUNTS)<=set(frame.columns) else pl.lit(False)
    if candidates.filter(~(marker&missing)).height:
        raise ValueError('Unknown invalid margin security record; inspect immutable raw before publication')
    return frame.filter(~invalid),candidates
