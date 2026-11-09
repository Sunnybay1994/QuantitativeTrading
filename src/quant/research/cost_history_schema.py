"""Assemble economic cost histories without inventing legacy reconciliation evidence."""
import hashlib
import io
from pathlib import Path

import polars as pl

from quant.backtest.account_reconciliation import validate_nav

RECONCILIATION = frozenset({'reconciliation_expected_equity', 'reconciliation_previous_equity',
                          'reconciliation_unexplained_return'})


def action_compatibility(path):
    """Fail closed when the November 8 share-action changes can affect old blocks."""
    if path is None:
        raise ValueError('Mixed NAV diagnostics require the original execution action snapshot')
    payload = Path(path).read_bytes()
    actions = pl.read_parquet(io.BytesIO(payload))
    if 'share_ratio' not in actions.columns:
        raise ValueError('Missing original share-action schema for mixed NAV history')
    if 'adjust_share_price' not in actions.columns and actions.filter(pl.col('share_ratio') > 0).height:
        raise ValueError('Mixed NAV positive share actions lack explicit price-adjustment semantics')
    if 'adjust_share_price' in actions.columns:
        if actions.schema['adjust_share_price'] != pl.Boolean:
            raise ValueError('Mixed NAV action price-adjustment semantics are not Boolean')
        if actions.filter((pl.col('share_ratio') > 0) & pl.col('adjust_share_price').is_null()).height:
            raise ValueError('Mixed NAV history spans changed null share-price adjustment semantics')
    if 'action_type' in actions.columns and actions.filter(
            (pl.col('share_ratio') < 0) & pl.col('action_type').is_in(
                ['SHARE_CONSOLIDATION', 'SHARE_CONVERSION'])).height:
        raise ValueError('Mixed NAV history spans changed economic share-action semantics')
    return {'path': str(path), 'sha256': hashlib.sha256(payload).hexdigest(),
            'rows': actions.height, 'changed_action_semantics_present': False}


def concat_nav_history(frames, *, execution_dividends=None):
    """Return NAV and explicit coverage; preserve the annual frames unchanged.

    Only the three known, independently checked diagnostic columns may differ.
    Mixed histories expose their shared economic columns, without zero/null
    padding. Such a view cannot pass validate_nav as a fully reconciled ledger.
    """
    if not frames:
        raise ValueError('No annual NAV histories')
    economic = [c for c in frames[0].columns if c not in RECONCILIATION]
    counts = {'legacy_rows': 0, 'diagnostic_rows': 0, 'legacy_chunks': 0, 'diagnostic_chunks': 0}
    for frame in frames:
        diagnostic = set(frame.columns) & RECONCILIATION
        if diagnostic and diagnostic != RECONCILIATION:
            raise ValueError('Partial annual reconciliation schema; retain original output')
        if set(frame.columns)-RECONCILIATION != set(economic):
            raise ValueError('Annual economic NAV schema changed; numerical review required')
        if diagnostic:
            validate_nav(frame, label='annual cost history')
            counts['diagnostic_rows'] += frame.height
            counts['diagnostic_chunks'] += 1
        else:
            counts['legacy_rows'] += frame.height
            counts['legacy_chunks'] += 1
    mixed = bool(counts['legacy_chunks'] and counts['diagnostic_chunks'])
    compatibility = action_compatibility(execution_dividends) if mixed else None
    columns = economic if mixed else frames[0].columns
    result = pl.concat([frame.select(columns) for frame in frames], how='vertical_relaxed')
    return result, {**counts, 'mixed_diagnostic_schema': mixed,
                    'full_reconciliation_evidence': counts['legacy_chunks'] == 0,
                    'economic_columns': economic, 'annual_sources_unchanged': True,
                    'action_compatibility': compatibility}
