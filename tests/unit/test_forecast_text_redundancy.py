from concurrent.futures import Future
from dataclasses import asdict
import datetime as dt
import json

import polars as pl
import pytest

from quant.factors.library import load_library
from quant.research import forecast_text_redundancy as module

VARIANTS = ["raw", "size_industry_neutral"]
TEXT = "text_operating_improvement"
END = dt.date(2024, 12, 28)


@pytest.fixture
def setup(tmp_path):
    text, peers, library = (tmp_path / name for name in ("text", "peers", "library"))
    library.mkdir()
    for factor in ("old_a", "old_b"):
        (library / f"{factor}.toml").write_text(
            f'id="{factor}"\nexpr="close"\nfamily="fixture"\ndirection=1\nsource_ref="synthetic"\n')
    config = (module.TEXT_LIBRARY.parents[2] / "configs/factors/battery.toml").read_text(encoding="utf-8")
    config = config.replace("start = 2010-01-01", "start = 2017-01-01")
    config += '\n[run]\nas_of = 2024-12-28\nselected = "all"\n'
    dates = [dt.date(year, month, 28) for year in range(2017, 2025) for month in range(1, 13)]
    values = {TEXT: [float(i) for i in range(100)],
        "text_nonrecurring_gain_dependency": [float(i * 37 % 101) for i in range(100)],
        "text_operating_pressure": [float(i * 61 % 101) for i in range(100)],
        "old_a": [float(i) for i in range(100)], "old_b": [float(i % 7) for i in range(100)]}
    icirs = {"old_a": .9, TEXT: .6, "text_nonrecurring_gain_dependency": .5,
             "text_operating_pressure": .4, "old_b": .1}
    for root, definitions in ((text, load_library(module.TEXT_LIBRARY)), (peers, load_library(library))):
        root.mkdir()
        (root / "battery.toml").write_text(config, encoding="utf-8")
        summaries = []
        for definition in definitions:
            folder = root / "factors" / definition.id
            folder.mkdir(parents=True)
            rows = [{"variant": variant, "icir": icirs[definition.id]} for variant in VARIANTS]
            (folder / "statistics.json").write_text(json.dumps({"definition": asdict(definition), "statistics": rows}))
            summaries.extend({"factor": definition.id, **row} for row in rows)
            pl.DataFrame({"trade_date": [date for date in dates for _ in range(100)],
                "symbol": [f"{i:06d}.SH" for i in range(100)] * len(dates),
                **{variant: values[definition.id] * len(dates) for variant in VARIANTS}}).write_parquet(
                    folder / "monthly_scores.parquet")
        pl.from_dicts(summaries).write_parquet(root / "statistics.parquet")
    return dict(statistics=text, peer_statistics=peers, peer_library=library, output=tmp_path / "result", workers=1)


def test_cross_library_duplicate_is_found_without_text_internal_duplicates(setup):
    summary = module.run_redundancy(**setup)
    pairs = pl.read_parquet(setup["output"] / "pairwise_correlations.parquet")
    maxima = pl.read_parquet(setup["output"] / "correlation_maxima.parquet")
    assert summary["pair_variant_rows"] == 18 and maxima.height == 6
    assert set(maxima["factor"]) == {f"text_{name}" for name in module.DIMENSIONS}
    assert not pairs.filter(pl.col("left").str.starts_with("old_")).height
    internal = pairs.filter(pl.col("right").str.starts_with("text_"))
    assert internal["mean_absolute_rank_correlation"].max() < .7
    matched = maxima.filter(pl.col("factor") == TEXT)
    assert matched["all_most_correlated_factor"].to_list() == ["old_a"] * 2
    assert matched["higher_most_correlated_factor"].to_list() == ["old_a"] * 2
    assert matched["redundant_with_higher"].all()
    assert matched["comparison_primary_rank"].to_list() == [1, 1]
    assert pairs["comparison_qualified"].all() and pairs["months"].min() == 96
    assert pairs["missing_month_count"].sum() == 0
    assert (setup["output"] / "battery.toml").read_bytes() == (setup["statistics"] / "battery.toml").read_bytes()


def test_one_undercovered_month_cannot_qualify_perfect_duplicate(setup):
    path = setup["peer_statistics"] / "factors/old_a/monthly_scores.parquet"
    frame = pl.read_parquet(path).filter(~((pl.col("trade_date") == END) & (pl.col("symbol") == "000099.SH")))
    frame.write_parquet(path)
    module.run_redundancy(**setup)
    pairs = pl.read_parquet(setup["output"] / "pairwise_correlations.parquet")
    pair = pairs.filter((pl.col("left") == TEXT) & (pl.col("right") == "old_a")).row(0, named=True)
    assert pair["months"] == 95 and pair["comparison_qualified"] is False
    assert pair["mean_absolute_rank_correlation"] == pytest.approx(1.)
    assert pair["missing_months"] == ["2024-12"] and pair["below_minimum_symbols_months"] == 1
    maxima = pl.read_parquet(setup["output"] / "correlation_maxima.parquet").filter(pl.col("factor") == TEXT)
    assert maxima["qualified_higher_peer_count"].to_list() == [0, 0]
    assert maxima["higher_max_absolute_rank_correlation"].null_count() == 2
    assert not maxima["redundant_with_higher"].any()
    assert maxima["comparison_primary_rank"].to_list() == [1, 1]


def test_month_absent_on_both_sides_is_missing_not_zero(setup):
    for root in (setup["statistics"], setup["peer_statistics"]):
        for path in root.glob("factors/*/monthly_scores.parquet"):
            pl.read_parquet(path).filter(pl.col("trade_date") != END).write_parquet(path)
    summary = module.run_redundancy(**setup)
    pairs = pl.read_parquet(setup["output"] / "pairwise_correlations.parquet")
    maxima = pl.read_parquet(setup["output"] / "correlation_maxima.parquet")
    assert summary["qualified_pair_variant_rows"] == 0
    assert pairs["observed_months"].to_list() == [95] * 18
    assert pairs["missing_month_count"].to_list() == [1] * 18
    assert maxima["all_max_absolute_rank_correlation"].null_count() == 6


@pytest.mark.parametrize("change", ["peer_missing", "text_missing", "variant_missing", "definition", "icir",
                                   "settings", "old_window", "selected", "overlap", "dates"])
def test_incomplete_or_mismatched_runs_rejected_before_output(setup, change):
    peer = setup["peer_statistics"]
    table_path = peer / "statistics.parquet"
    if change in {"peer_missing", "variant_missing", "text_missing"}:
        if change == "text_missing":
            table_path = setup["statistics"] / "statistics.parquet"
        table = pl.read_parquet(table_path)
        table = table.slice(1) if change == "variant_missing" else table.filter(pl.col("factor") != table["factor"][0])
        table.write_parquet(table_path)
    elif change in {"definition", "icir"}:
        path = peer / "factors/old_a/statistics.json"
        saved = json.loads(path.read_text())
        if change == "definition":
            saved["definition"]["direction"] = -1
        else:
            saved["statistics"][0]["icir"] = 1.9
        path.write_text(json.dumps(saved))
    elif change == "overlap":
        path = setup["peer_library"] / "overlap.toml"
        path.write_bytes((module.TEXT_LIBRARY / f"{TEXT}.toml").read_bytes())
    elif change == "dates":
        path = peer / "factors/old_a/monthly_scores.parquet"
        frame = pl.read_parquet(path).with_columns(pl.when(pl.col("trade_date") == dt.date(2017, 1, 28))
            .then(dt.date(2010, 1, 28)).otherwise(pl.col("trade_date")).alias("trade_date"))
        frame.write_parquet(path)
    else:
        roots = (peer,) if change == "settings" else (peer, setup["statistics"])
        for root in roots:
            path = root / "battery.toml"
            content = path.read_text(encoding="utf-8")
            old, new = {"settings": ("as_of = 2024-12-28", "as_of = 2024-11-28"),
                "old_window": ("start = 2017-01-01", "start = 2010-01-01"),
                "selected": ('selected = "all"', 'selected = "old_a"')}[change]
            path.write_text(content.replace(old, new), encoding="utf-8")
    with pytest.raises(ValueError):
        module.run_redundancy(**setup)
    assert not setup["output"].exists()


def test_parallel_jobs_are_bounded_to_three_texts(setup, monkeypatch):
    submissions = []

    class Pool:
        def __init__(self, max_workers):
            assert max_workers == 3

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, fn, *args):
            submissions.append(args[1])
            future = Future()
            future.set_result(fn(*args))
            return future

    monkeypatch.setattr(module, "ProcessPoolExecutor", Pool)
    result = module.run_redundancy(**{**setup, "workers": 8})
    assert len(submissions) == 3 and result["maxima_variant_rows"] == 6


def test_comparison_rank_uses_primary_icir_and_factor_id_ties(setup):
    root = setup["statistics"]
    path = root / f"factors/{TEXT}/statistics.json"
    saved = json.loads(path.read_text())
    for row in saved["statistics"]:
        row["icir"] = 100. if row["variant"] == "raw" else .9
    path.write_text(json.dumps(saved))
    table = pl.read_parquet(root / "statistics.parquet").with_columns(
        pl.when(pl.col("factor") == TEXT).then(
            pl.when(pl.col("variant") == "raw").then(100.).otherwise(.9))
        .otherwise(pl.col("icir")).alias("icir"))
    table.write_parquet(root / "statistics.parquet")
    module.run_redundancy(**setup)
    maxima = pl.read_parquet(setup["output"] / "correlation_maxima.parquet").filter(pl.col("factor") == TEXT)
    # old_a wins the primary ICIR tie lexically even though text raw ICIR is larger.
    assert maxima["comparison_primary_rank"].to_list() == [1, 1]
    assert maxima["higher_most_correlated_factor"].to_list() == ["old_a", "old_a"]
