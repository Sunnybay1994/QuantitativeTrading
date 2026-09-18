"""Full-history rank equivalence audit before executable factor cost replays."""
import argparse
import hashlib
import io
import json
import tomllib
from pathlib import Path

import polars as pl


def canonical_scores(scores: pl.DataFrame, variants: list[str]) -> pl.DataFrame:
    """Preserve dates, symbols, missing masks and all ties; ignore score scale."""
    keys = ['trade_date', 'symbol']
    if scores.select(keys).is_duplicated().any() or any(scores[k].null_count() for k in keys):
        raise ValueError('Signal equivalence requires unique non-null date/symbol keys')
    columns = []
    for variant in variants:
        value = pl.col(variant)
        # Keep null, NaN and signed infinity distinct even though none is traded.
        mask = (pl.when(value.is_null()).then(1).when(value.is_nan()).then(2)
                .when(value == float('inf')).then(3).when(value == float('-inf')).then(4)
                .otherwise(0).cast(pl.UInt8))
        columns.extend([mask.alias(variant + '_mask'),
                        pl.when(value.is_finite()).then(value).otherwise(None)
                        .rank('average').over('trade_date').alias(variant)])
    return scores.select(*keys, *columns).sort(keys).rechunk()


def audit_duplicates(statistics: Path, factors: list[str] | None = None) -> dict:
    """Within one frozen battery only; never authorize reuse across snapshots."""
    config = (statistics/'battery.toml').read_bytes()
    settings = tomllib.loads(config.decode('utf-8'))
    if factors is None:
        factors = sorted(pl.read_parquet(statistics/'statistics.parquet', columns=['factor'])
                         ['factor'].unique().to_list())
    if len(factors) != len(set(factors)):
        raise ValueError('Duplicate factor IDs in equivalence audit')
    buckets, representatives, aliases, fingerprints = {}, [], {}, {}
    for factor in factors:
        if Path(factor).name != factor or factor in ('.', '..'):
            raise ValueError('Invalid factor ID')
        folder = statistics/'factors'/factor
        definition = json.loads((folder/'statistics.json').read_text(encoding='utf-8'))['definition']
        if definition['id'] != factor or definition['direction'] not in (-1, 1):
            raise ValueError('Factor definition identity or direction is invalid')
        frame = canonical_scores(pl.read_parquet(folder/'monthly_scores.parquet'), settings['variants'])
        buffer = io.BytesIO()
        frame.write_ipc(buffer, compression='uncompressed')
        digest = hashlib.sha256(config + str(definition['direction']).encode() + buffer.getvalue()).hexdigest()
        fingerprints[factor] = digest
        # Hash narrows comparisons; exact equality is still required.
        representative = None
        for previous in buckets.get(digest, []):
            other = canonical_scores(pl.read_parquet(statistics/'factors'/previous/'monthly_scores.parquet'),
                                     settings['variants'])
            if frame.equals(other):
                representative = previous
                break
        if representative is None:
            representatives.append(factor)
            buckets.setdefault(digest, []).append(factor)
        else:
            aliases[factor] = representative
    return {'version': 1, 'statistics': str(statistics.resolve()),
            'battery_sha256': hashlib.sha256(config).hexdigest(),
            'scope': 'same frozen battery; all variants, full date/symbol grid, direction and missing masks',
            'execution_reuse_enabled': False, 'factors': len(factors),
            'representatives': representatives, 'aliases': aliases, 'fingerprints': fingerprints,
            'potential_saved_factor_replays': len(aliases),
            'potential_saved_variant_cost_replays': len(aliases)*len(settings['variants'])*len(
                settings['portfolio']['cost_multipliers']),
            'actual_saved_replays': 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--statistics', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit_duplicates(args.statistics)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
