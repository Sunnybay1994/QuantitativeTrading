"""Natural N3 value/mask/IC consistency check for newly versioned GP output."""
from pathlib import Path
import json

import numpy as np
import polars as pl

from quant.data.gp_context_inputs import dump, sha256
from quant.research.gp_full_context import VERSION


def _finite_number(value) -> float | None:
    return float(value) if value is not None and np.isfinite(value) else None


def compare_values(training: pl.DataFrame, computed: pl.DataFrame, labels: pl.DataFrame,
                   *, factor: str, direction: int) -> dict:
    from quant.research.factor_battery_statistics import rank_ic_by_date
    from quant.research.nightly_gp import preprocess_training_scores
    keys = ['symbol', 'trade_date']
    expected = training.join(labels.select(*keys, 'label'), on=keys, how='left', validate='1:1').sort(keys)
    actual = expected.select(*keys, 'label').join(computed.select(*keys, 'candidate'),
        on=keys, how='left', validate='1:1').sort(keys)
    masks = expected['candidate'].is_null().equals(actual['candidate'].is_null())
    a, b = actual['candidate'].to_numpy(), expected['candidate'].to_numpy()
    finite_masks = bool(np.array_equal(np.isfinite(a), np.isfinite(b)))
    nonfinite_masks = all(np.array_equal(kind(a), kind(b))
                         for kind in (np.isnan, np.isposinf, np.isneginf))
    finite = np.isfinite(a) & np.isfinite(b)
    # Do not hide overflow or one-sided missingness by dropping it from the check.
    with np.errstate(over='ignore', invalid='ignore'):
        differences = np.abs(a[finite] - b[finite])
        maximum_abs = _finite_number(np.max(differences)) if finite.any() else None
        maximum_scaled = (_finite_number(np.max(differences / np.maximum(1., np.abs(b[finite]))))
                          if finite.any() else None)
    series = []
    for frame in (actual, expected):
        scores = preprocess_training_scores(frame.with_columns((pl.col('candidate') * direction).alias('candidate')))
        series.append(rank_ic_by_date(scores, score='candidate', label='label',
            minimum_symbols=100, minimum_paired_coverage=.8).sort('trade_date'))
    same_months = series[0]['trade_date'].equals(series[1]['trade_date'])
    ic_actual, ic_expected = (s['rank_ic'].to_numpy() for s in series)
    ic_masks = same_months and np.array_equal(np.isfinite(ic_actual), np.isfinite(ic_expected))
    # rank_ic_by_date retains planned months with null IC for insufficient pairs
    # or zero variance. Compare availability first, then the observed IC values.
    # Null months remain null; they are never zero-filled or counted as evidence.
    valid_ic = np.isfinite(ic_actual) & np.isfinite(ic_expected) if same_months else np.zeros(0, dtype=bool)
    delta = (_finite_number(np.max(np.abs(ic_actual[valid_ic] - ic_expected[valid_ic])))
             if valid_ic.any() else None)
    reasons = []
    for ok, reason in (
        (masks, 'candidate_null_mask_mismatch'),
        (finite_masks, 'candidate_finite_mask_mismatch'),
        (nonfinite_masks, 'candidate_nonfinite_kind_mismatch'),
        (maximum_abs is not None and maximum_scaled is not None, 'candidate_difference_unavailable'),
        # Scaled as abs(diff)/max(1, abs(n2)). 1e-6 absorbs N2/N3 float noise
        # (observed ~1e-9..2e-7 with identical IC); still rejects meaningful drift.
        (maximum_scaled is None or maximum_scaled <= 1e-6, 'candidate_value_mismatch'),
        (same_months, 'ic_month_mismatch'),
        (ic_masks, 'ic_missing_mask_mismatch'),
        (valid_ic.any(), 'no_comparable_ic_months'),
        (delta is None or delta <= 1e-12, 'ic_value_mismatch'),
    ):
        if not ok:
            reasons.append(reason)
    return {'factor': factor, 'direction': direction, 'rows': expected.height, 'missing_mask_equal': masks,
            'finite_mask_equal': finite_masks, 'nonfinite_kind_mask_equal': bool(nonfinite_masks),
            'maximum_absolute_difference': maximum_abs, 'maximum_scaled_difference': maximum_scaled,
            'months': series[0].height, 'valid_ic_months': int(valid_ic.sum()),
            'ic_months_equal': same_months, 'ic_missing_mask_equal': bool(ic_masks),
            'n2_mean_ic': _finite_number(series[1]['rank_ic'].mean()),
            'n3_same_sample_mean_ic': _finite_number(series[0]['rank_ic'].mean()),
            'maximum_month_ic_difference': delta, 'failure_reasons': reasons, 'passed': not reasons}


def verify_new_gp_values(definitions: list, *, data_root: Path, output: Path) -> dict:
    """Skip legacy definitions; compare each new factor with its own N2 receipt."""
    sources = {}
    checks = []
    for definition in definitions:
        ref = Path(definition.source_ref)
        if ref.name != 'search.json' or not ref.is_file():
            continue
        if ref not in sources:
            record = json.loads(ref.read_text(encoding='utf-8'))
            matching = [r for r in record.get('candidates', []) if r.get('calculation_context') == VERSION]
            if not matching:
                sources[ref] = None
            else:
                folder = ref.parent
                manifest = json.loads((folder/'training_values_manifest.json').read_text(encoding='utf-8'))
                values_path, labels_path = folder/'training_candidate_values.parquet', folder/'monthly_sample.parquet'
                if sha256(values_path) != manifest['values_sha256'] or sha256(labels_path) != manifest['labels_sha256']:
                    raise ValueError('GP_CONTEXT_ALIGNMENT: frozen N2 value/label receipt changed')
                sources[ref] = (manifest, pl.read_parquet(values_path), pl.read_parquet(labels_path))
        if sources[ref] is None:
            continue
        manifest, training, labels = sources[ref]
        if definition.id not in manifest['expressions']:
            continue
        if (manifest['expressions'][definition.id] != definition.expr
                or manifest['directions'][definition.id] != definition.direction):
            raise ValueError('GP_CONTEXT_ALIGNMENT: definition/direction differs from frozen N2')
        training_factor = training.filter(pl.col('factor') == definition.id).drop('factor')
        years = sorted(training_factor['trade_date'].dt.year().unique().to_list())
        paths = [data_root/'factors'/definition.id/f'year={year}'/'data.parquet' for year in years]
        computed = pl.scan_parquet(paths).select(pl.col('ts_code').alias('symbol'), 'trade_date',
            pl.col('value').alias('candidate')).collect()
        checks.append(compare_values(training_factor, computed, labels,
                                     factor=definition.id, direction=definition.direction))
    summary = {'scope': 'N2/N3 fixed sample/label/direction consistency, not alpha or admission',
               'factors_checked': len(checks), 'checks': checks, 'passed': all(r['passed'] for r in checks)}
    if checks:
        dump(output, summary)
    if not summary['passed']:
        raise ValueError(f'GP_CONTEXT_ALIGNMENT: N2/N3 factor values differ; see {output}')
    return summary
