import datetime as dt
from pathlib import Path

import pandera.errors
import polars as pl
import pytest

from quant.domain import ForwardReturnLabelSchema, PredictionScoreSchema
from quant.research.m3 import DatasetSnapshot, load_m3_config
from quant.research.m3.contracts import DateSegment, TemporalFold


def test_m3_example_config_parses_and_stays_disabled_before_runtime_gate() -> None:
    config = load_m3_config(Path("configs/research/m3_qlib_example.toml")).document
    assert config["meta"]["enabled"] is False
    assert config["runtime"]["qlib"]["supported_python"] == ">=3.8,<3.13"
    assert len(config["runtime"]["qlib"]["dump_script_sha256"]) == 64
    assert config["labels"]["horizons_sessions"] == (5, 10)
    assert config["walk_forward"]["embargo_sessions"] >= max(
        config["labels"]["horizons_sessions"]
    )


def _label(**overrides: object) -> pl.DataFrame:
    row = {
        "as_of": dt.date(2026, 1, 5),
        "symbol": "000001.SZ",
        "benchmark": "510300.SH",
        "horizon_sessions": 5,
        "return_start_date": dt.date(2026, 1, 6),
        "return_end_date": dt.date(2026, 1, 12),
        "available_as_of": dt.date(2026, 1, 12),
        "raw_return": 0.03,
        "benchmark_return": 0.01,
        "relative_return": 0.02,
        "label_version": "next_open_to_h_close_relative_v1",
    }
    row.update(overrides)
    return pl.DataFrame([row])


def test_forward_label_contract_enforces_availability_and_reconciliation() -> None:
    ForwardReturnLabelSchema.validate(_label())
    ForwardReturnLabelSchema.validate(_label(benchmark="000300.SH"))
    with pytest.raises(pandera.errors.SchemaError):
        ForwardReturnLabelSchema.validate(
            _label(available_as_of=dt.date(2026, 1, 9))
        )
    with pytest.raises(pandera.errors.SchemaError):
        ForwardReturnLabelSchema.validate(_label(relative_return=0.03))


def test_prediction_contract_requires_unique_rank_per_cross_section() -> None:
    rows = pl.DataFrame({
        "as_of": [dt.date(2026, 1, 5)] * 2,
        "symbol": ["000001.SZ", "000002.SZ"],
        "score": [0.2, 0.1],
        "rank": [1, 2],
        "model": ["lightgbm"] * 2,
        "model_version": ["alpha158_lgb_v1"] * 2,
        "dataset_snapshot_id": ["sha256:fixture"] * 2,
        "fold": ["fold_001"] * 2,
        "horizon_sessions": [5] * 2,
    })
    PredictionScoreSchema.validate(rows)
    with pytest.raises(pandera.errors.SchemaError):
        PredictionScoreSchema.validate(rows.with_columns(pl.lit(1).alias("rank")))


def test_temporal_fold_rejects_overlap() -> None:
    fold = TemporalFold(
        name="fold_001",
        train=DateSegment(dt.date(2020, 1, 1), dt.date(2022, 12, 31)),
        validation=DateSegment(dt.date(2023, 1, 1), dt.date(2023, 12, 31)),
        test=DateSegment(dt.date(2024, 1, 1), dt.date(2024, 12, 31)),
    )
    assert fold.name == "fold_001"
    with pytest.raises(ValueError, match="训练段必须早于验证段"):
        TemporalFold(
            name="bad",
            train=DateSegment(dt.date(2020, 1, 1), dt.date(2023, 1, 1)),
            validation=DateSegment(dt.date(2023, 1, 1), dt.date(2023, 12, 31)),
            test=DateSegment(dt.date(2024, 1, 1), dt.date(2024, 12, 31)),
        )


def test_dataset_snapshot_requires_non_empty_counts() -> None:
    snapshot = DatasetSnapshot(
        snapshot_id="a" * 64,
        manifest_path=Path("manifest.json"),
        source_fingerprint="b" * 64,
        row_count=100,
        symbol_count=10,
        start=dt.date(2020, 1, 1),
        end=dt.date(2024, 12, 31),
    )
    assert snapshot.symbol_count == 10
    with pytest.raises(ValueError, match="行数和证券数"):
        DatasetSnapshot(
            snapshot_id="a" * 64,
            manifest_path=Path("manifest.json"),
            source_fingerprint="b" * 64,
            row_count=0,
            symbol_count=10,
            start=dt.date(2020, 1, 1),
            end=dt.date(2024, 12, 31),
        )
    with pytest.raises(ValueError, match="hex"):
        DatasetSnapshot(
            snapshot_id="sha256:fixture",
            manifest_path=Path("manifest.json"),
            source_fingerprint="b" * 64,
            row_count=1,
            symbol_count=1,
            start=dt.date(2020, 1, 1),
            end=dt.date(2024, 12, 31),
        )
    with pytest.raises(TypeError):
        DatasetSnapshot(
            snapshot_id="a" * 64,
            manifest_path=Path("manifest.json"),
            provider_path=Path("provider"),  # type: ignore[call-arg]
            source_fingerprint="b" * 64,
            row_count=1,
            symbol_count=1,
            start=dt.date(2020, 1, 1),
            end=dt.date(2024, 12, 31),
        )
