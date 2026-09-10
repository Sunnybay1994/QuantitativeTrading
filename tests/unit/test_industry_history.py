import datetime as dt
import json
from pathlib import Path

import polars as pl

from quant.data.industry_history import attach_industry, membership_intervals, publish_industry_history
from quant.data.factor_panels import read_factor_industry


def taxonomy():
    rows = []
    for version, prefix in (("SW2014", "old"), ("SW2021", "new")):
        for level, code, parent in (("L1", prefix, "0"), ("L2", prefix + "2", prefix),
                                    ("L3", prefix + "3", prefix + "2")):
            rows.append({"src": version, "level": level, "industry_code": code,
                         "parent_code": parent, "index_code": "shared" if level == "L3" else code})
    return pl.DataFrame(rows)


def test_version_availability_parent_changes_and_exit_boundary():
    members = pl.DataFrame([{"con_code": "000001.SZ", "index_code": "shared",
                             "in_date": "19910403", "out_date": "20220104", "is_new": "N"}])
    out, stats = membership_intervals(taxonomy(), members, as_of=dt.date(2022, 1, 10))
    assert out["valid_from"].to_list() == [dt.date(2014, 1, 1), dt.date(2021, 12, 13)]
    assert out["valid_to"].to_list() == [dt.date(2021, 12, 13), dt.date(2022, 1, 4)]
    assert out["industry_l1"].to_list() == ["SW2014:old", "SW2021:new"]
    assert stats["conflict_calendar_days"] == 0


def test_conflicting_members_are_omitted_only_during_overlap():
    tree = taxonomy()
    other = tree.filter((pl.col("src") == "SW2021") & (pl.col("level") == "L3")).with_columns(
        pl.lit("other").alias("index_code"), pl.lit("other3").alias("industry_code"))
    members = pl.DataFrame([
        {"con_code": "000001.SZ", "index_code": "shared", "in_date": "20220101", "out_date": None, "is_new": "Y"},
        {"con_code": "000001.SZ", "index_code": "other", "in_date": "20220103", "out_date": "20220106", "is_new": "N"},
    ])
    out, stats = membership_intervals(pl.concat([tree, other]), members, as_of=dt.date(2022, 1, 10))
    assert out["valid_from"].to_list() == [dt.date(2022, 1, 1), dt.date(2022, 1, 6)]
    assert out["valid_to"].to_list() == [dt.date(2022, 1, 3), dt.date(2022, 1, 11)]
    assert stats["conflict_calendar_days"] == 3
    # Duplicated source rows must not create a conflict with themselves.
    duplicated, _ = membership_intervals(tree, pl.concat([members.head(1)] * 2), as_of=dt.date(2022, 1, 10))
    assert duplicated.height == 1


def test_asof_join_preserves_gaps_and_cannot_use_future_membership():
    members = pl.DataFrame([
        {"con_code": "000001.SZ", "index_code": "shared", "in_date": "20220103", "out_date": "20220105", "is_new": "N"},
        {"con_code": "000001.SZ", "index_code": "shared", "in_date": "20220108", "out_date": None, "is_new": "Y"},
    ])
    intervals, _ = membership_intervals(taxonomy(), members, as_of=dt.date(2022, 1, 10))
    panel = pl.DataFrame({"symbol": ["000001.SZ"] * 6,
                          "trade_date": [dt.date(2022, 1, d) for d in (2, 3, 5, 7, 8, 11)]})
    joined = attach_industry(panel, intervals)
    assert joined["industry_l1"].to_list() == [None, "SW2021:new", None, None, "SW2021:new", None]
    assert joined.height == panel.height


def test_source_version_prevents_stale_current_and_backdated_new_classification():
    members = pl.DataFrame([
        {"con_code": "000001.SZ", "index_code": "shared", "in_date": "19910403", "out_date": None, "is_new": "Y", "source_version": "SW2014"},
        {"con_code": "000001.SZ", "index_code": "shared", "in_date": "20230101", "out_date": None, "is_new": "Y", "source_version": "SW2021"},
    ])
    out, _ = membership_intervals(taxonomy(), members, as_of=dt.date(2023, 1, 3))
    assert out["valid_from"].to_list() == [dt.date(2014, 1, 1), dt.date(2023, 1, 1)]
    assert out["valid_to"].to_list() == [dt.date(2021, 12, 13), dt.date(2023, 1, 4)]
    assert out["industry_l1"].to_list() == ["SW2014:old", "SW2021:new"]


def test_publish_reads_both_supplier_schemas_and_requires_complete_pages(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    tree = taxonomy()
    for version in ("SW2014", "SW2021"):
        for level in ("L1", "L2", "L3"):
            tree.filter((pl.col("src") == version) & (pl.col("level") == level)).write_parquet(
                raw / f"index_classify_{level}_{version}.parquet")
    old = pl.DataFrame({"index_code": ["shared"], "con_code": ["000001.SZ"],
                        "in_date": ["19910403"], "out_date": [None], "is_new": ["Y"]})
    old.write_parquet(raw / "index_member_shared_Y_0.parquet")
    pl.DataFrame().write_parquet(raw / "index_member_shared_N_0.parquet")
    new = old.rename({"index_code": "l3_code", "con_code": "ts_code"})
    new.write_parquet(raw / "index_member_all_shared_Y_0.parquet")
    # Missing terminal page must fail before creating any clean output.
    import pytest
    with pytest.raises(FileNotFoundError):
        publish_industry_history(raw, tmp_path / "clean", as_of=dt.date(2022, 1, 1), with_current=True)
    assert not (tmp_path / "clean").exists()
    pl.DataFrame().write_parquet(raw / "index_member_all_shared_N_0.parquet")
    result = publish_industry_history(raw, tmp_path / "clean", as_of=dt.date(2022, 1, 1), with_current=True)
    output = pl.read_parquet(Path(result["output"]) / "intervals.parquet")
    assert result["with_current"] and result["symbols"] == 1
    assert output["industry_l1"].to_list() == ["SW2014:old", "SW2021:new"]


def test_factor_reader_uses_complete_source_versions_only(tmp_path: Path):
    import pytest
    panel = pl.DataFrame({"symbol": ["000001.SZ"], "trade_date": [dt.date(2022, 1, 1)]})
    with pytest.raises(ValueError, match="with-current"):
        read_factor_industry(tmp_path, panel)
    root = tmp_path / "clean/tushare_industry/20220901"
    root.mkdir(parents=True)
    members = pl.DataFrame({"con_code": ["000001.SZ"], "index_code": ["shared"],
                            "in_date": ["19910403"], "out_date": [None], "is_new": ["Y"]})
    intervals, _ = membership_intervals(taxonomy(), members, as_of=dt.date(2022, 1, 1))
    intervals.write_parquet(root / "intervals.parquet")
    (root / "summary.json").write_text(json.dumps({"with_current": True}))
    joined = read_factor_industry(tmp_path, panel)
    assert joined["industry_l1"].to_list() == ["SW2021:new"]
