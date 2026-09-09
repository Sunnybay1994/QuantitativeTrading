import sys
from pathlib import Path

import polars as pl
import pytest

from quant.reporting.paper_monthly import compare_monthly, main, read_nav


def nav(dates: list[str], values: list[float]) -> pl.DataFrame:
    return pl.DataFrame({"date": dates, "unit_nav": values})


def test_first_cost_and_monthly_compounding() -> None:
    dates = ["2026-07-13", "2026-07-31", "2026-08-03", "2026-08-31", "2026-09-08"]
    monthly, daily = compare_monthly(nav(dates, [.98, .99, 1.01, 1.089, 1.1]),
                                     nav(dates, [.99, 1., 1.02, 1.05, 1.06]))
    assert monthly["paper_return"].to_list() == pytest.approx([-.01, .1, 1.1 / 1.089 - 1])
    assert monthly["partial_month"].to_list() == [True, False, True]
    assert monthly["return_difference_pp"][0] == pytest.approx(-1)
    assert daily["paper_comparison_nav"][0] == .98
    assert daily["nav_difference"][-1] == pytest.approx(.04)
    assert monthly["base_date"][0] is None


def test_single_day_keeps_inception_cost() -> None:
    monthly, _ = compare_monthly(nav(["2026-09-10"], [.997]), nav(["2026-09-10"], [.999]))
    assert monthly["paper_return"][0] == pytest.approx(-.003)
    assert monthly["partial_month"][0]


def test_missing_dates_use_shared_endpoints_and_are_reported() -> None:
    monthly, daily = compare_monthly(
        nav(["2026-07-31", "2026-08-03", "2026-08-31", "2026-09-01"], [1., 1.02, 1.1, 1.2]),
        nav(["2026-07-31", "2026-08-03", "2026-08-04", "2026-08-31", "2026-09-01"],
            [1., 1.03, 1.04, 1.05, 1.06]))
    assert daily.height == 4
    assert monthly["unmatched_dates"].to_list() == [0, 1, 0]
    assert monthly["coverage_note"][1] == "unmatched_dates"
    assert monthly["paper_return"][1] == pytest.approx(.1)


@pytest.mark.parametrize("values", [[float("nan")], [float("inf")], [0.], [-1.]])
def test_bad_nav_rejected(values: list[float]) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        compare_monthly(nav(["2026-09-10"], values), nav(["2026-09-10"], [1.]))


def test_initial_interval_mismatch_and_no_overlap() -> None:
    with pytest.raises(ValueError, match="Initial return intervals differ"):
        compare_monthly(nav(["2026-09-10"], [1.]),
                        nav(["2026-09-09", "2026-09-10"], [1., 1.1]))
    with pytest.raises(ValueError, match="no common dates"):
        compare_monthly(nav(["2026-09-10"], [1.]), nav(["2026-09-11"], [1.]))
    with pytest.raises(ValueError, match="entire month"):
        compare_monthly(nav(["2026-07-31", "2026-09-01"], [1., 1.1]),
                        nav(["2026-07-31", "2026-09-01"], [1., 1.1]))


def test_empty_and_multi_fold_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No NAV"):
        compare_monthly(nav([], []), nav(["2026-09-10"], [1.]))
    path = tmp_path / "nav.parquet"
    nav(["2026-09-10", "2026-09-10"], [.99, .98]).with_columns(
        pl.Series("fold", [1, 2])).write_parquet(path)
    with pytest.raises(ValueError, match="Select one fold"):
        read_nav(path, [])
    assert read_nav(path, ["fold=2"])["unit_nav"][0] == .98
    with pytest.raises(ValueError, match="unique"):
        compare_monthly(nav(["2026-09-10", "2026-09-10"], [1., 1.]),
                        nav(["2026-09-10"], [1.]))


def test_cli_writes_rehearsal_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "nav.csv"
    nav(["2026-09-10"], [.99]).write_csv(source)
    out = tmp_path / "report"
    monkeypatch.setattr(sys, "argv", ["paper_monthly", "--ledger", str(source),
        "--benchmark", str(source), "--mode", "rehearsal", "--output", str(out)])
    main()
    assert "历史演练（非前向记录）" in (out / "report.md").read_text(encoding="utf-8")
    assert pl.read_csv(out / "monthly.csv")["paper_return"][0] == pytest.approx(-.01)
    assert (out / "common_nav.csv").exists()
    with pytest.raises(FileExistsError):
        main()
