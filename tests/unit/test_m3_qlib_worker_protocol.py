import hashlib
import json
from pathlib import Path

import pytest

from quant.research.m3.qlib_adapter import (
    _require_feature_frame_contract,
    reconcile_labels,
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _request(provider: Path) -> dict[str, object]:
    rows = [[
        "2026-01-05", "000001.SZ", "510300.SH", 5, "label-v1",
        "2026-01-06", "2026-01-12",
    ]]
    key_rows = [row[:5] for row in rows]
    provider_key = "8" * 64
    return {
        "schema_version": "m3-label-reconciliation-worker-request-v1",
        "worker_protocol_version": "m3-qlib-worker-v1",
        "reconciliation_key": "1" * 64,
        "experiment_key": "2" * 64,
        "provider_validation_receipt_sha256": "3" * 64,
        "label_manifest_sha256": "4" * 64,
        "label_reconciliation_config_sha256": "5" * 64,
        "dependency_fingerprint_sha256": "6" * 64,
        "code_version": "g3b-v1",
        "snapshot_id": "7" * 64,
        "provider_key": provider_key,
        "qlib_version": "0.9.7",
        "provider_uri": str(provider),
        "provider_uri_sha256": _sha([provider_key, "provider"]),
        "horizon_sessions": 5,
        "qlib_expression": "Ref($close,-5)/Ref($open,-1)-1",
        "label_rows": rows,
        "row_key_sha256": _sha(key_rows),
    }


@pytest.mark.parametrize(
    "field", [
        "row_key_sha256", "provider_uri_sha256",
        "label_reconciliation_config_sha256",
        "dependency_fingerprint_sha256",
    ],
)
def test_worker_rejects_identity_drift_before_qlib_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str,
) -> None:
    provider = tmp_path / "provider"
    provider.mkdir()
    request = _request(provider)
    request[field] = (
        "0" * 64
        if field in {"row_key_sha256", "provider_uri_sha256"}
        else "not-a-sha"
    )
    request_path = tmp_path / "request.json"
    request_path.write_bytes(_canonical(request))
    imported: list[str] = []
    original_import = __import__

    def guarded_import(name: str, *args: object, **kwargs: object):
        if name == "qlib" or name.startswith("qlib."):
            imported.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded_import)
    with pytest.raises(ValueError):
        reconcile_labels(
            request_path, tmp_path / "response.json", tmp_path / "details.parquet"
        )
    assert imported == []
    assert not (tmp_path / "response.json").exists()
    assert not (tmp_path / "details.parquet").exists()


def test_worker_request_schema_requires_complete_key_preimage(tmp_path: Path) -> None:
    provider = tmp_path / "provider"
    provider.mkdir()
    request = _request(provider)
    del request["code_version"]
    request_path = tmp_path / "request.json"
    request_path.write_bytes(_canonical(request))
    with pytest.raises(ValueError, match="request schema"):
        reconcile_labels(
            request_path, tmp_path / "response.json", tmp_path / "details.parquet"
        )


def test_worker_rejects_wrong_multiindex_order() -> None:
    pandas = pytest.importorskip("pandas")
    index = pandas.MultiIndex.from_tuples(
        [(pandas.Timestamp("2026-01-05"), "SZ000001")],
        names=("datetime", "instrument"),
    )
    frame = pandas.DataFrame({"$close": [10.0]}, index=index)
    with pytest.raises(ValueError, match="MultiIndex"):
        _require_feature_frame_contract(frame, ["$close"])
