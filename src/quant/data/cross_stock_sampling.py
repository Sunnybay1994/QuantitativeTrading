"""Stable disjoint historical stock cohorts, independent of returns."""
import hashlib


def stock_groups(symbols: list[str], *, groups: int, per_group: int, seed: int) -> dict[str, int]:
    if groups < 2 or per_group < 100:
        raise ValueError('Cross-stock search requires multiple groups with at least 100 stocks each')
    ordered = sorted(set(symbols), key=lambda symbol: (
        hashlib.sha256(f'{seed}:{symbol}'.encode('utf-8')).hexdigest(), symbol))
    if len(ordered) < groups*per_group:
        raise ValueError('Insufficient distinct stocks for disjoint training groups')
    return {symbol: index//per_group for index, symbol in enumerate(ordered[:groups*per_group])}
