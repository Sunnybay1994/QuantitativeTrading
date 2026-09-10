"""Conservative annual issuance signal from dated CNINFO capital-change events."""

import datetime as dt

import polars as pl

# New placements, rights issues, convertible conversion and option exercises
# explicitly create common shares. Bonus shares and transfers are separate.
ISSUANCE_CODES = frozenset({'015004', '015005', '015012', '015992'})
NON_ISSUANCE_CODES = frozenset({'015009', '015010', '015011', '015013', '015016',
    '015019', '015021', '015023', '015027', '015043', '015997', '015998'})
# Listing, merger, incentive-plan and "other" labels alone do not establish
# whether new common shares were issued. They remain unknown, not zero.


def compute_no_common_equity_issue(
    events: pl.DataFrame, coverage: pl.DataFrame, anchors: pl.DataFrame, *, as_of: dt.date,
) -> pl.DataFrame:
    """Use the anchor fiscal year, with announcement strictly before the signal."""
    requests = {r['symbol']: r for r in coverage.iter_rows(named=True)}
    known: dict[str, list[dict]] = {}
    for row in events.filter((pl.col('ann_date') < as_of) & (pl.col('event_date') <= as_of)).iter_rows(named=True):
        known.setdefault(row['symbol'], []).append(row)
    rows = []
    for symbol, end in anchors.select('symbol', 'end_date').iter_rows():
        value, status, issues, unknown = None, 'MISSING_EVENT_COVERAGE', 0, 0
        if end is not None:
            if (end.month, end.day) != (12, 31) or end >= as_of:
                raise ValueError('Issuance signal requires a completed annual period')
            start = dt.date(end.year, 1, 1)
            request = requests.get(symbol)
            history = [r for r in known.get(symbol, []) if r['event_date'] <= end]
            if (request is not None and not request['empty_response'] and history
                and request['start'] <= start and request['end'] >= end):
                period = [r for r in history if r['event_date'] >= start]
                for event in period:
                    codes = set(event['change_type_codes'].split(','))
                    issues += bool(codes & ISSUANCE_CODES)
                    notice_date = event.get('notice_available_date')
                    resolved = (event.get('notice_non_issuance') is True
                        and isinstance(notice_date, dt.date) and notice_date < as_of)
                    unknown += bool(codes - ISSUANCE_CODES - NON_ISSUANCE_CODES) and not resolved
                if issues:
                    value, status = 0.0, 'COMMON_SHARES_ISSUED'
                elif unknown:
                    status = 'AMBIGUOUS_CAPITAL_CHANGE'
                else:
                    value, status = 1.0, 'NO_REPORTED_COMMON_ISSUE'
        rows.append(dict(symbol=symbol, no_common_equity_issue=value,
            issuance_status=status, issuance_events=issues, ambiguous_events=unknown))
    return pl.DataFrame(rows, schema={'symbol': pl.String, 'no_common_equity_issue': pl.Float64,
        'issuance_status': pl.String, 'issuance_events': pl.Int64, 'ambiguous_events': pl.Int64})
