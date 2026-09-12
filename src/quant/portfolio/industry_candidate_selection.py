"""Nominate score-ranked stocks needed by fixed industry lower bounds."""
import math

import polars as pl


def select_industry_candidates(*, scores: pl.DataFrame, market: pl.DataFrame,
                               benchmark: pl.DataFrame, current: pl.DataFrame,
                               previous: list[str], top_k: int = 50,
                               retention_multiplier: float = 1.5,
                               single_stock_weight: float = .03,
                               industry_active_band: float = .05,
                               minimum_signal_stocks: int = 100) -> tuple[pl.DataFrame, dict]:
    """Return nomination rows and diagnostics; no account changes or IO.

    scores: as_of/symbol/score; market: as_of/known_at/symbol/industry_l1,
    total_market_value/adv20/can_buy/can_sell; benchmark/current: as_of/symbol/weight.
    All inputs refer to one signal close. UNKNOWN benchmark names retain their
    full weight, but are not new buy candidates. Positive unsellable holdings
    are retained even without a score/market record, and consume the name cap.
    Sector quotas are necessary nominal counts, not sufficient executable
    capacity; the unchanged relative projection must validate the final weights.
    previous is the previous NOMINEE set for the existing rank buffer, not a
    substitute for actual current holdings. On failure the partial diagnostic
    nominations retain every forced holding; callers must reject feasible=False.
    """
    if (type(top_k) is not int or top_k < 1 or minimum_signal_stocks < top_k
            or not math.isfinite(retention_multiplier) or retention_multiplier < 1
            or not 0 < single_stock_weight <= 1 or not 0 <= industry_active_band <= 1):
        raise ValueError('Invalid industry nomination parameters')
    if scores.is_empty() or scores['as_of'].n_unique() != 1 or scores['as_of'].null_count():
        raise ValueError('Require one nonempty signal-date score pool')
    day = scores['as_of'][0]
    for frame in (scores, market, benchmark, current):
        if frame['symbol'].null_count() or frame['symbol'].is_duplicated().any():
            raise ValueError('Duplicate or null nomination symbols')
        if frame.height and (frame['as_of'].null_count() or (frame['as_of'] != day).any()):
            raise ValueError('Nomination inputs must share signal date')
    if market['known_at'].null_count() or (market['known_at'] > day).any():
        raise ValueError('Nomination market information is not PIT')
    for column in ('can_buy', 'can_sell'):
        if market[column].dtype != pl.Boolean or market[column].null_count():
            raise ValueError('Require explicit buy/sell permissions')
    for frame in (benchmark, current):
        if any(w is None or not math.isfinite(w) or w < 0 for w in frame['weight']):
            raise ValueError('Invalid nomination portfolio weights')
        if frame['weight'].sum() > 1+1e-10:
            raise ValueError('Nomination weights exceed equity')
    if benchmark.is_empty() or not math.isclose(benchmark['weight'].sum(), 1., rel_tol=0, abs_tol=1e-10):
        raise ValueError('Require full benchmark without dropping unknown members')
    observations = {r['symbol']: r for r in market.iter_rows(named=True)}

    def industry(symbol: str) -> str:
        raw = observations.get(symbol, {}).get('industry_l1')
        return raw.strip() if isinstance(raw, str) and raw.strip() else 'UNKNOWN'

    def buyable(symbol: str) -> bool:
        row = observations.get(symbol)
        return bool(row and row['can_buy'] and industry(symbol) != 'UNKNOWN'
            and all(row[k] is not None and math.isfinite(row[k]) and row[k] > 0
                    for k in ('total_market_value', 'adv20')))

    ranked = scores.filter(pl.col('score').is_finite()).sort(['score', 'symbol'], descending=[True, False])
    ranked_names = ranked['symbol'].to_list()
    values = dict(ranked.select('symbol', 'score').iter_rows())
    candidates = [s for s in ranked_names if buyable(s)]
    current_weights = dict(current.select('symbol', 'weight').iter_rows())
    forced = sorted(s for s, w in current_weights.items() if w > 0
                    and not observations.get(s, {}).get('can_sell', False))
    selected = dict.fromkeys(forced, 'unsellable_actual_holding')
    failures = []
    if len(forced) > top_k:
        failures.append('unsellable_holdings_exceed_name_cap')
    if len(candidates) < minimum_signal_stocks:
        failures.append('insufficient_buyable_scored_pool')
    benchmark_industries: dict[str, float] = {}
    for symbol, weight in sorted(benchmark.select('symbol', 'weight').iter_rows()):
        key = industry(symbol)
        benchmark_industries[key] = benchmark_industries.get(key, 0.)+weight
    quotas: list[dict] = []
    for key, weight in sorted(benchmark_industries.items()):
        lower = max(0., weight-industry_active_band)
        count = math.ceil(lower/single_stock_weight-1e-12)
        existing = sum(industry(s) == key for s in selected)
        needed = max(0, count-existing)
        available = [s for s in candidates if industry(s) == key and s not in selected]
        for symbol in available[:needed]:
            selected[symbol] = 'industry_lower_bound'
        if len(available) < needed:
            failures.append(f'insufficient_industry_candidates:{key}')
        quotas.append({'industry': key, 'benchmark_weight': weight, 'minimum_weight': lower,
            'minimum_names': count, 'forced_names': existing,
            'available_additional_names': len(available), 'missing_names': max(0, needed-len(available))})
    if sum(q['minimum_names'] for q in quotas) > top_k:
        failures.append('industry_minimum_names_exceed_name_cap')
    required_total = len(selected)
    if required_total > top_k:
        failures.append('mandatory_nominees_exceed_name_cap')
    if not failures:
        # Use the original score ranking for Top75 membership, then require
        # executable known controls for entry; do not move rank boundaries.
        previous_names, candidate_names = set(previous), set(candidates)
        buffered = [s for s in ranked_names[:math.floor(top_k*retention_multiplier)]
                    if s in previous_names and s in candidate_names]
        for reason, names in (('rank_buffer', buffered), ('score_rank', candidates)):
            for symbol in names:
                if len(selected) >= top_k:
                    break
                selected.setdefault(symbol, reason)
        if len(selected) < top_k:
            failures.append('insufficient_names_after_required_nominees')
    rows = [{'as_of': day, 'symbol': s, 'score': values.get(s), 'industry_l1': industry(s),
             'selection_reason': reason, 'current_weight': current_weights.get(s, 0.)}
            for s, reason in sorted(selected.items())]
    result = pl.from_dicts(rows, schema={'as_of': scores.schema['as_of'], 'symbol': pl.String,
        'score': pl.Float64, 'industry_l1': pl.String, 'selection_reason': pl.String, 'current_weight': pl.Float64})
    return result, {'as_of': str(day), 'feasible': not failures, 'failures': failures,
        'top_k': top_k, 'selected_names': result.height, 'buyable_scored_pool': len(candidates),
        'forced_holdings': forced, 'minimum_required_nominees_with_forced': required_total,
        'industry_quotas': quotas, 'unknown_benchmark_weight': benchmark_industries.get('UNKNOWN', 0.),
        'capacity_statement': 'Nominal name lower bound only; full weight projection still required'}
