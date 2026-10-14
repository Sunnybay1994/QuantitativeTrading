"""Incompatible benchmark fingerprints must rebuild, not brick continuous mining."""
from pathlib import Path

from quant.research.factor_battery_benchmarks import _retire_incompatible_benchmarks


def test_retire_incompatible_benchmarks_moves_stage(tmp_path: Path):
    output = tmp_path / "benchmarks"
    output.mkdir()
    (output / "benchmark_inputs.json").write_text('{"version": 1}', encoding="utf-8")
    (output / "summary.json").write_text("{}", encoding="utf-8")
    _retire_incompatible_benchmarks(output)
    assert not output.exists()
    stale = list(tmp_path.glob("benchmarks_incompatible_*"))
    assert len(stale) == 1
    assert (stale[0] / "benchmark_inputs.json").is_file()


def test_retire_missing_output_is_noop(tmp_path: Path):
    _retire_incompatible_benchmarks(tmp_path / "missing")
    assert not list(tmp_path.iterdir())
