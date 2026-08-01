from __future__ import annotations

import math
import json
from pathlib import Path

import polars as pl
import pytest

from quant.research.m3.features import (
    canonical_row_keys_sha256,
    f64_matrix_sha256,
    feature_schema_sha256,
    feature_segment_content_sha256,
)
from quant.research.m3.qlib_adapter import build_development_example_alpha158


def test_f64_matrix_digest_is_stable_for_nan_and_preserves_signed_zero() -> None:
    left = f64_matrix_sha256(columns=("a", "b"), rows=((math.nan, -0.0),))
    right = f64_matrix_sha256(columns=("a", "b"), rows=((None, -0.0),))
    positive_zero = f64_matrix_sha256(columns=("a", "b"), rows=((None, 0.0),))

    assert left == right
    assert left != positive_zero


def test_matrix_and_row_digests_preserve_frozen_order() -> None:
    assert canonical_row_keys_sha256((("2026-01-05", "000001.SZ"),)) != (
        canonical_row_keys_sha256((("000001.SZ", "2026-01-05"),))
    )
    assert f64_matrix_sha256(columns=("a", "b"), rows=((1.0, 2.0),)) != (
        f64_matrix_sha256(columns=("b", "a"), rows=((1.0, 2.0),))
    )


def test_matrix_digest_rejects_infinity_width_and_non_numeric_values() -> None:
    with pytest.raises(ValueError, match="infinity"):
        f64_matrix_sha256(columns=("a",), rows=((math.inf,),))
    with pytest.raises(ValueError, match="width"):
        f64_matrix_sha256(columns=("a",), rows=((1.0, 2.0),))
    with pytest.raises(ValueError, match="value"):
        f64_matrix_sha256(columns=("a",), rows=(("1",),))  # type: ignore[list-item]


def test_schema_and_segment_content_bind_order_and_selected_schema() -> None:
    schema = feature_schema_sha256(names=("a", "b"))
    swapped = feature_schema_sha256(names=("b", "a"))
    rows = canonical_row_keys_sha256((("2026-01-05", "000001.SZ"),))
    matrix = f64_matrix_sha256(columns=("a", "b"), rows=((1.0, 2.0),))

    assert schema != swapped
    assert feature_segment_content_sha256(
        name="train",
        feature_row_keys_sha256=rows,
        feature_matrix_sha256=matrix,
        selected_schema_sha256=schema,
    ) != feature_segment_content_sha256(
        name="train",
        feature_row_keys_sha256=rows,
        feature_matrix_sha256=matrix,
        selected_schema_sha256=swapped,
    )


def test_development_feature_worker_emits_strict_158_shape(tmp_path: Path) -> None:
    request = {
        "schema_version": "m3-feature-worker-request-v1",
        "worker_protocol_version": "m3-qlib-worker-v1",
        "release_kind": "development_example",
        "formal_gate_eligible": False,
        "example_id": "development-example-test",
        "experiment_key": "a" * 64,
        "experiment_manifest_sha256": "b" * 64,
        "g1_release_id": "c" * 64,
        "g1_release_manifest_sha256": "d" * 64,
        "snapshot_id": "e" * 64,
        "snapshot_manifest_sha256": "f" * 64,
        "provider_key": "1" * 64,
        "provider_manifest_sha256": "2" * 64,
        "provider_receipt_sha256": "3" * 64,
        "fold": "fold_001",
        "planned_fold_sha256": "4" * 64,
        "scientific_config_sha256": "5" * 64,
        "feature_version": "alpha158_v1",
        "qlib_version": "0.9.7",
        "segments": {
            "train": ["2026-01-05"],
            "validation": ["2026-01-06"],
            "test": ["2026-01-07"],
        },
        "eligible_rows": [
            ["test", "2026-01-07", "000001.SZ"],
            ["train", "2026-01-05", "000001.SZ"],
            ["validation", "2026-01-06", "000001.SZ"],
        ],
    }
    request["eligible_rows"] = sorted(request["eligible_rows"])
    request_path = tmp_path / "request.json"
    output = tmp_path / "output"
    output.mkdir()
    request_path.write_text(
        json.dumps(request, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    build_development_example_alpha158(request_path, output)

    train = pl.read_parquet(output / "raw_train.parquet")
    response = json.loads((output / "worker-response.json").read_text("utf-8"))
    assert train.columns[:2] == ["as_of", "symbol"]
    assert len(train.columns) == 160
    assert train["ALPHA158"].null_count() == train.height
    assert len(response["input_names"]) == len(response["expressions"]) == 158
    assert response["release_kind"] == "development_example"
