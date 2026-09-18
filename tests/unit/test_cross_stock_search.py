import datetime as dt

import polars as pl
import pytest

from quant.research.cross_stock_search import stock_groups, group_fitness


def test_stock_groups_are_disjoint_order_independent_and_bounded():
    symbols = [f's{i}' for i in range(1000)]
    groups = stock_groups(symbols, groups=3, per_group=300, seed=42)
    assert groups == stock_groups(list(reversed(symbols)), groups=3, per_group=300, seed=42)
    assert [list(groups.values()).count(i) for i in range(3)] == [300]*3
    with pytest.raises(ValueError, match='Insufficient'):
        stock_groups(symbols[:899], groups=3, per_group=300, seed=42)


def test_one_reversed_group_cannot_hide_behind_strong_pooled_ic():
    assignments = {f'{g}_{s}': g for g in range(3) for s in range(100)}
    rows = [{'symbol': symbol, 'trade_date': dt.date(2020, 1, 31),
             'candidate': float(symbol.split('_')[1]),
             'label': float(symbol.split('_')[1])*(1 if group < 2 else -1)}
            for symbol, group in assignments.items()]
    config = {'version': 'fixture', 'sample_groups': 3, 'minimum_symbols_per_month': 100,
              'minimum_paired_coverage': .8, 'minimum_valid_months_per_group': 1,
              'complexity_penalty': .0005}
    result = group_fitness(pl.from_dicts(rows), assignments, config=config, complexity=2,
                           maximum_correlation=0)
    assert result['direction'] == 1 and result['worst_directional_mean_ic'] == -1
    assert result['fitness'] == -1.001
    config['minimum_valid_months_per_group'] = 48
    with pytest.raises(ValueError, match='valid training months'):
        group_fitness(pl.from_dicts(rows), assignments, config=config, complexity=2, maximum_correlation=0)
