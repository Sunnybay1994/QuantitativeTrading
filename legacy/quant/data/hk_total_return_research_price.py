"""Development-only HK close gross-total-return research-price publication."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import io
import json
import math
import os
import stat
from decimal import Context, Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
from pathlib import Path
from typing import Any, Never, SupportsIndex, cast

import pandera.errors
import polars as pl

from quant.data.hk_total_return_schedule import (
    HkTotalReturnFreshContext,
    VerifiedHkTotalReturnApplicationPlan,
    verify_hk_total_return_application_plan,
)
from quant.domain import ResearchPrice1dSchema

HK_GROSS_TOTAL_RETURN_V1 = "HK_GROSS_TOTAL_RETURN_V1"
FORMULA_POLICY = "HK_GROSS_TOTAL_RETURN_CLOSE_V1"
ROUNDING_POLICY = "DECIMAL50_HALF_EVEN_OUTPUT_12DP_V1"
SOURCE = "derived_hk_bar_and_ca_v1"
CLASSIFICATION = "development"
ARTIFACT_KIND = "hk_gross_total_return_research_price"
GATE_CLAIM = "development_contract_only"

_NAMESPACE = "hk_gross_total_return_v1"
_FILES = frozenset({"request.json", "research_price_1d.parquet", "manifest.json", "receipt.json"})
_QUANTUM = Decimal("0.000000000001")
_HEX = frozenset("0123456789abcdef")
_ERROR_CODES = frozenset(
    {
        "HK_TOTAL_RETURN_PRICE_INPUT_INVALID",
        "HK_TOTAL_RETURN_GROUP_UNSUPPORTED",
        "HK_TOTAL_RETURN_PRICE_INVALID",
        "HK_TOTAL_RETURN_PUBLICATION_INVALID",
        "HK_TOTAL_RETURN_IO_FAILED",
        "HK_TOTAL_RETURN_VERIFY_FAILED",
    }
)
_ATTESTATION_KEY = os.urandom(32)


class HkTotalReturnResearchPriceError(ValueError):
    """Stable, path-free public error for research-price publication."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("unknown HK total-return research-price error")
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"HkTotalReturnResearchPriceError({self.code!r})"


def _fail(code: str) -> HkTotalReturnResearchPriceError:
    return HkTotalReturnResearchPriceError(code)


class VerifiedDevelopmentHkGrossTotalReturnPublication:
    """Exact-final, process-local capability for one verified development artifact."""

    __slots__ = (
        "_research_prices",
        "artifact_id",
        "publication_root",
        "receipt_sha256",
        "as_of",
        "classification",
        "_attestation",
    )

    _research_prices: pl.DataFrame
    artifact_id: str
    publication_root: Path
    receipt_sha256: str
    as_of: dt.datetime
    classification: str
    _attestation: bytes

    def __new__(
        cls, *_args: object, **_kwargs: object
    ) -> VerifiedDevelopmentHkGrossTotalReturnPublication:
        del cls
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID") from None

    def __init_subclass__(cls, **_kwargs: object) -> None:
        del cls
        raise TypeError("VerifiedDevelopmentHkGrossTotalReturnPublication is final")

    def __setattr__(self, _name: str, _value: object) -> Never:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID") from None

    @property
    def research_prices(self) -> pl.DataFrame:
        return self._research_prices.clone()

    def __reduce_ex__(self, protocol: SupportsIndex) -> Never:
        del protocol
        raise TypeError("verified development HK gross-total-return publication is process-local")


def publish_development_hk_gross_total_return(
    *,
    application_plan: VerifiedHkTotalReturnApplicationPlan,
    context: HkTotalReturnFreshContext,
    development_root: Path,
) -> VerifiedDevelopmentHkGrossTotalReturnPublication:
    """Fresh-build and no-clobber publish one development-only four-file artifact."""

    result: VerifiedDevelopmentHkGrossTotalReturnPublication | None = None
    error_code: str | None = None
    try:
        _fresh_verify(application_plan, context, "HK_TOTAL_RETURN_PRICE_INPUT_INVALID")
        material = _build_material(application_plan, context)
        root = _validate_development_root(development_root)
        development_identity = _directory_identity(root)
        artifact_root = root / _NAMESPACE / material["artifact_id"]
        result = _publish_or_replay(
            artifact_root,
            material,
            development_root=root,
            development_identity=development_identity,
        )
    except HkTotalReturnResearchPriceError as error:
        error_code = error.code
    except Exception:
        error_code = "HK_TOTAL_RETURN_PUBLICATION_INVALID"
    if error_code is not None:
        raise _fail(error_code) from None
    if result is None:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID") from None
    return result


def verify_development_hk_gross_total_return(
    *,
    publication_root: Path,
    application_plan: VerifiedHkTotalReturnApplicationPlan,
    context: HkTotalReturnFreshContext,
) -> VerifiedDevelopmentHkGrossTotalReturnPublication:
    """Fresh-rebuild all logical content and verify an existing four-file artifact."""

    result: VerifiedDevelopmentHkGrossTotalReturnPublication | None = None
    error_code: str | None = None
    try:
        _fresh_verify(application_plan, context, "HK_TOTAL_RETURN_VERIFY_FAILED")
        material = _build_material(application_plan, context)
        root = _validate_publication_root(publication_root, material["artifact_id"])
        result = _verify_artifact(root, material)
    except HkTotalReturnResearchPriceError as error:
        error_code = error.code
    except Exception:
        error_code = "HK_TOTAL_RETURN_PUBLICATION_INVALID"
    if error_code is not None:
        raise _fail(error_code) from None
    if result is None:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID") from None
    return result


def _fresh_verify(
    plan: VerifiedHkTotalReturnApplicationPlan,
    context: HkTotalReturnFreshContext,
    failure_code: str,
) -> None:
    try:
        verify_hk_total_return_application_plan(plan, context=context)
    except Exception:
        raise _fail(failure_code) from None


def _build_material(
    plan: VerifiedHkTotalReturnApplicationPlan, context: HkTotalReturnFreshContext
) -> dict[str, Any]:
    try:
        if (
            type(plan) is not VerifiedHkTotalReturnApplicationPlan
            or type(context) is not HkTotalReturnFreshContext
            or plan.as_of != context.as_of
            or not _is_utc(context.as_of)
        ):
            raise _fail("HK_TOTAL_RETURN_PRICE_INPUT_INVALID")
        schedule = plan.schedule
        bars = context.bar_bundle.bars.clone().select("symbol", "trade_date", "close")
        prices, logical_rows = _calculate_prices(schedule, bars)
        logical_hash = _hash_payload(
            {
                "algorithm": "hk-gross-total-return-logical-content-v1",
                "columns": prices.columns,
                "rows": logical_rows,
            },
            "HK_TOTAL_RETURN_PRICE_INVALID",
        )
        inputs = _input_identities(plan, context, schedule)
        metadata = {
            "classification": CLASSIFICATION,
            "artifact_kind": ARTIFACT_KIND,
            "gate_claim": GATE_CLAIM,
            "adjustment_method": HK_GROSS_TOTAL_RETURN_V1,
            "formula_policy": FORMULA_POLICY,
            "rounding_policy": ROUNDING_POLICY,
            "source": SOURCE,
        }
        artifact_id = _hash_payload(
            {
                "algorithm": "development-hk-gross-total-return-artifact-v1",
                "metadata": metadata,
                "as_of": context.as_of,
                "inputs": inputs,
                "research_price_logical_content_sha256": logical_hash,
            },
            "HK_TOTAL_RETURN_PRICE_INVALID",
        )
        request_base = {
            "schema_version": "development-hk-gross-total-return-request-v1",
            "artifact_id": artifact_id,
            **metadata,
            "as_of": _utc_text(context.as_of),
            "inputs": inputs,
            "research_price_logical_content_sha256": logical_hash,
        }
        request_hash = _hash_payload(request_base, "HK_TOTAL_RETURN_PUBLICATION_INVALID")
        request = {**request_base, "request_sha256": request_hash}
        return {
            "artifact_id": artifact_id,
            "as_of": context.as_of,
            "prices": prices,
            "logical_rows": logical_rows,
            "logical_hash": logical_hash,
            "inputs": inputs,
            "metadata": metadata,
            "request": request,
            "request_hash": request_hash,
        }
    except HkTotalReturnResearchPriceError:
        raise
    except (DecimalException, ArithmeticError, OverflowError, ValueError, TypeError):
        raise _fail("HK_TOTAL_RETURN_PRICE_INVALID") from None
    except Exception:
        raise _fail("HK_TOTAL_RETURN_PRICE_INPUT_INVALID") from None


def _calculate_prices(
    schedule: pl.DataFrame, bars: pl.DataFrame
) -> tuple[pl.DataFrame, list[dict[str, object]]]:
    required_schedule = {
        "event_id",
        "symbol",
        "action_type",
        "ex_date",
        "window_disposition",
        "application_trade_date",
        "cash_per_share_gross_hkd",
        "share_multiplier",
    }
    if not required_schedule.issubset(schedule.columns) or set(bars.columns) != {
        "symbol",
        "trade_date",
        "close",
    }:
        raise _fail("HK_TOTAL_RETURN_PRICE_INPUT_INVALID")
    ordered_bars = bars.sort(["symbol", "trade_date"])
    if not ordered_bars.height or ordered_bars.select("symbol", "trade_date").is_duplicated().any():
        raise _fail("HK_TOTAL_RETURN_PRICE_INPUT_INVALID")
    if bars.columns != ["symbol", "trade_date", "close"]:
        raise _fail("HK_TOTAL_RETURN_PRICE_INPUT_INVALID")

    groups: dict[tuple[str, dt.date], tuple[Decimal, Decimal]] = {}
    applicable = schedule.filter(pl.col("window_disposition") == "APPLY_IN_WINDOW")
    grouped_rows: dict[tuple[str, dt.date], list[dict[str, Any]]] = {}
    for row in applicable.iter_rows(named=True):
        key = (row["symbol"], row["application_trade_date"])
        if type(key[0]) is not str or type(key[1]) is not dt.date:
            raise _fail("HK_TOTAL_RETURN_PRICE_INPUT_INVALID")
        grouped_rows.setdefault(key, []).append(row)
    for key, action_rows in grouped_rows.items():
        if len({row["ex_date"] for row in action_rows}) != 1:
            raise _fail("HK_TOTAL_RETURN_GROUP_UNSUPPORTED")
        share_rows = [row for row in action_rows if row["action_type"] in {"BONUS", "SPLIT"}]
        if len(share_rows) > 1:
            raise _fail("HK_TOTAL_RETURN_GROUP_UNSUPPORTED")
        if any(row["action_type"] not in {"DIVIDEND", "BONUS", "SPLIT"} for row in action_rows):
            raise _fail("HK_TOTAL_RETURN_GROUP_UNSUPPORTED")
        cash = sum(
            (
                _decimal(row["cash_per_share_gross_hkd"])
                for row in action_rows
                if row["action_type"] == "DIVIDEND"
            ),
            Decimal(0),
        )
        multiplier = _decimal(share_rows[0]["share_multiplier"]) if share_rows else Decimal(1)
        if cash < 0 or multiplier <= 0:
            raise _fail("HK_TOTAL_RETURN_PRICE_INVALID")
        groups[key] = (multiplier, cash)

    bar_keys = set(ordered_bars.select("symbol", "trade_date").iter_rows())
    if not set(groups).issubset(bar_keys):
        raise _fail("HK_TOTAL_RETURN_PRICE_INPUT_INVALID")

    output: list[dict[str, object]] = []
    logical: list[dict[str, object]] = []
    for partition in ordered_bars.partition_by("symbol", maintain_order=True):
        bar_rows = partition.iter_rows(named=True)
        previous_raw: Decimal | None = None
        adjusted: Decimal | None = None
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
            for row in bar_rows:
                raw = _decimal(row["close"])
                if raw <= 0:
                    raise _fail("HK_TOTAL_RETURN_PRICE_INVALID")
                if previous_raw is None:
                    adjusted = raw
                else:
                    multiplier, cash = groups.get(
                        (row["symbol"], row["trade_date"]),
                        (Decimal(1), Decimal(0)),
                    )
                    if adjusted is None:
                        raise _fail("HK_TOTAL_RETURN_PRICE_INVALID")
                    adjusted = adjusted * (multiplier * raw + cash) / previous_raw
                if not adjusted.is_finite() or adjusted <= 0:
                    raise _fail("HK_TOTAL_RETURN_PRICE_INVALID")
                quantized = adjusted.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
                numeric = float(quantized)
                if not math.isfinite(numeric) or numeric <= 0:
                    raise _fail("HK_TOTAL_RETURN_PRICE_INVALID")
                common = {
                    "symbol": row["symbol"],
                    "trade_date": row["trade_date"],
                    "adjustment_method": HK_GROSS_TOTAL_RETURN_V1,
                    "source": SOURCE,
                }
                output.append({**common, "adjusted_close": numeric})
                logical.append({**common, "adjusted_close_12dp": format(quantized, ".12f")})
                previous_raw = raw
    frame = pl.DataFrame(
        output,
        schema={
            "symbol": pl.String,
            "trade_date": pl.Date,
            "adjusted_close": pl.Float64,
            "adjustment_method": pl.String,
            "source": pl.String,
        },
        orient="row",
    )
    try:
        validated = ResearchPrice1dSchema.validate(frame)
    except (pandera.errors.SchemaError, pandera.errors.SchemaErrors, pl.exceptions.PolarsError):
        raise _fail("HK_TOTAL_RETURN_PRICE_INVALID") from None
    if (
        validated.columns != list(frame.schema)
        or validated.schema != frame.schema
        or not validated.equals(validated.sort(["symbol", "trade_date"]))
        or validated.height != ordered_bars.height
    ):
        raise _fail("HK_TOTAL_RETURN_PRICE_INVALID")
    return validated, logical


def _input_identities(
    plan: VerifiedHkTotalReturnApplicationPlan,
    context: HkTotalReturnFreshContext,
    schedule: pl.DataFrame,
) -> dict[str, str]:
    names = (
        "p0_query_sha256",
        "p0_actions_content_sha256",
        "p0_evidence_content_sha256",
        "implementation_evidence_content_sha256",
        "implementation_projection_sha256",
        "bar_plan_sha256",
        "bar_publication_sha256",
        "bars_content_sha256",
        "bar_availability_content_sha256",
    )
    identities: dict[str, str] = {
        "application_plan_identity_sha256": plan.plan_identity_sha256,
        "application_schedule_content_sha256": plan.schedule_content_sha256,
        "application_schedule_policy": plan.policy_version,
    }
    for name in names:
        values = schedule.get_column(name).unique().to_list()
        if len(values) != 1 or not _is_hex(values[0]):
            raise _fail("HK_TOTAL_RETURN_PRICE_INPUT_INVALID")
        identities[name] = values[0]
    direct = {
        "p0_query_sha256": context.implemented.p0_query_sha256,
        "p0_actions_content_sha256": context.implemented.p0_actions_content_sha256,
        "p0_evidence_content_sha256": context.implemented.p0_evidence_content_sha256,
        "implementation_evidence_content_sha256": context.implemented.implementation_evidence_content_sha256,
        "implementation_projection_sha256": context.implemented.projection_sha256,
        "bar_plan_sha256": context.bar_bundle.plan_sha256,
        "bar_publication_sha256": context.bar_bundle.publication_sha256,
    }
    if any(identities[name] != value for name, value in direct.items()):
        raise _fail("HK_TOTAL_RETURN_PRICE_INPUT_INVALID")
    if not all(_is_hex(value) for value in identities.values() if value != plan.policy_version):
        raise _fail("HK_TOTAL_RETURN_PRICE_INPUT_INVALID")
    return identities


def _decimal(value: object) -> Decimal:
    if value is None or type(value) is bool:
        raise _fail("HK_TOTAL_RETURN_PRICE_INVALID")
    result = Decimal(str(value))
    if not result.is_finite():
        raise _fail("HK_TOTAL_RETURN_PRICE_INVALID")
    return result


def _publish_or_replay(
    artifact_root: Path,
    material: dict[str, Any],
    *,
    development_root: Path,
    development_identity: tuple[int, int, int],
) -> VerifiedDevelopmentHkGrossTotalReturnPublication:
    parent = artifact_root.parent
    try:
        parent.mkdir(mode=0o700, exist_ok=True)
    except OSError:
        raise _fail("HK_TOTAL_RETURN_IO_FAILED") from None
    _validate_plain_directory(parent, expected_name=_NAMESPACE)
    if _directory_identity(development_root) != development_identity:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    created_root = False
    try:
        artifact_root.mkdir(mode=0o700, exist_ok=False)
        created_root = True
    except FileExistsError:
        result = _verify_artifact(artifact_root, material)
        if _directory_identity(development_root) != development_identity:
            raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
        return result
    except OSError:
        raise _fail("HK_TOTAL_RETURN_IO_FAILED") from None

    root_identity = _directory_identity(artifact_root)
    created: list[tuple[Path, tuple[int, int, int], str]] = []
    try:
        payloads = _publication_payloads(material)
        for name in ("request.json", "research_price_1d.parquet", "manifest.json", "receipt.json"):
            path = artifact_root / name
            identity = _write_exclusive(path, payloads[name])
            created.append((path, identity, _sha256(payloads[name])))
        result = _verify_artifact(artifact_root, material)
        if _directory_identity(development_root) != development_identity:
            raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
        return result
    except HkTotalReturnResearchPriceError:
        _rollback_created(created, artifact_root, root_identity if created_root else None)
        raise
    except Exception:
        _rollback_created(created, artifact_root, root_identity if created_root else None)
        raise _fail("HK_TOTAL_RETURN_IO_FAILED") from None


def _publication_payloads(material: dict[str, Any]) -> dict[str, bytes]:
    request_raw = _canonical_bytes(material["request"])
    buffer = io.BytesIO()
    try:
        material["prices"].write_parquet(buffer)
    except Exception:
        raise _fail("HK_TOTAL_RETURN_IO_FAILED") from None
    parquet_raw = buffer.getvalue()
    manifest = _manifest(material, request_raw, parquet_raw)
    manifest_raw = _canonical_bytes(manifest)
    receipt = _receipt(material, manifest, manifest_raw)
    return {
        "request.json": request_raw,
        "research_price_1d.parquet": parquet_raw,
        "manifest.json": manifest_raw,
        "receipt.json": _canonical_bytes(receipt),
    }


def _manifest(material: dict[str, Any], request_raw: bytes, parquet_raw: bytes) -> dict[str, Any]:
    prices: pl.DataFrame = material["prices"]
    dates = prices.get_column("trade_date")
    first_date = cast(dt.date, dates.min())
    last_date = cast(dt.date, dates.max())
    return {
        "schema_version": "development-hk-gross-total-return-manifest-v1",
        "artifact_id": material["artifact_id"],
        **material["metadata"],
        "request_sha256": material["request_hash"],
        "files": [
            {
                "selector": "request.json",
                "sha256": _sha256(request_raw),
                "size": len(request_raw),
            },
            {
                "selector": "research_price_1d.parquet",
                "sha256": _sha256(parquet_raw),
                "size": len(parquet_raw),
                "logical_content_sha256": material["logical_hash"],
            },
        ],
        "output_summary": {
            "rows": prices.height,
            "symbols": prices.get_column("symbol").n_unique(),
            "first_trade_date": first_date.isoformat(),
            "last_trade_date": last_date.isoformat(),
            "logical_content_sha256": material["logical_hash"],
        },
    }


def _receipt(
    material: dict[str, Any], manifest: dict[str, Any], manifest_raw: bytes
) -> dict[str, Any]:
    return {
        "schema_version": "development-hk-gross-total-return-receipt-v1",
        "status": "SUCCESS",
        "artifact_id": material["artifact_id"],
        **material["metadata"],
        "as_of": _utc_text(material["as_of"]),
        "request_sha256": material["request_hash"],
        "manifest_sha256": _sha256(manifest_raw),
        "input_summary": material["inputs"],
        "output_summary": manifest["output_summary"],
    }


def _verify_artifact(
    root: Path, material: dict[str, Any]
) -> VerifiedDevelopmentHkGrossTotalReturnPublication:
    root = _validate_publication_root(root, material["artifact_id"])
    root_identity = _directory_identity(root)
    try:
        entries = {entry.name for entry in os.scandir(root)}
    except OSError:
        raise _fail("HK_TOTAL_RETURN_IO_FAILED") from None
    if entries != _FILES:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    raw = {name: _read_stable_file(root / name) for name in _FILES}
    request = _decode_canonical_json(raw["request.json"])
    if request != material["request"]:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    try:
        disk_prices = pl.read_parquet(io.BytesIO(raw["research_price_1d.parquet"]))
        disk_prices = ResearchPrice1dSchema.validate(disk_prices)
    except Exception:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID") from None
    if (
        disk_prices.schema != material["prices"].schema
        or disk_prices.columns != material["prices"].columns
        or not disk_prices.equals(material["prices"])
        or not disk_prices.equals(disk_prices.sort(["symbol", "trade_date"]))
    ):
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    expected_manifest = _manifest(material, raw["request.json"], raw["research_price_1d.parquet"])
    manifest = _decode_canonical_json(raw["manifest.json"])
    if manifest != expected_manifest:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    expected_receipt = _receipt(material, expected_manifest, raw["manifest.json"])
    receipt = _decode_canonical_json(raw["receipt.json"])
    if receipt != expected_receipt:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    if _directory_identity(root) != root_identity:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    return _issue_publication(
        material["prices"],
        material["artifact_id"],
        root.resolve(strict=True),
        _sha256(raw["receipt.json"]),
        material["as_of"],
    )


def _issue_publication(
    prices: pl.DataFrame,
    artifact_id: str,
    root: Path,
    receipt_sha256: str,
    as_of: dt.datetime,
) -> VerifiedDevelopmentHkGrossTotalReturnPublication:
    result = object.__new__(VerifiedDevelopmentHkGrossTotalReturnPublication)
    object.__setattr__(result, "_research_prices", prices.clone())
    object.__setattr__(result, "artifact_id", artifact_id)
    object.__setattr__(result, "publication_root", root)
    object.__setattr__(result, "receipt_sha256", receipt_sha256)
    object.__setattr__(result, "as_of", as_of)
    object.__setattr__(result, "classification", CLASSIFICATION)
    object.__setattr__(result, "_attestation", b"")
    object.__setattr__(result, "_attestation", _capability_attestation(result))
    return result


def _capability_attestation(
    publication: VerifiedDevelopmentHkGrossTotalReturnPublication,
) -> bytes:
    payload = _hash_payload(
        {
            "algorithm": "development-hk-gross-total-return-capability-v1",
            "artifact_id": publication.artifact_id,
            "publication_root": str(publication.publication_root),
            "receipt_sha256": publication.receipt_sha256,
            "as_of": publication.as_of,
            "classification": publication.classification,
        },
        "HK_TOTAL_RETURN_PUBLICATION_INVALID",
    ).encode("ascii")
    return hmac.digest(_ATTESTATION_KEY, payload, "sha256")


def _validate_development_root(value: Path) -> Path:
    if not isinstance(value, Path):
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    return _validate_plain_directory(value, expected_name="development")


def _validate_publication_root(value: Path, artifact_id: str) -> Path:
    if not isinstance(value, Path) or value.name != artifact_id:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    root = _validate_plain_directory(value, expected_name=artifact_id)
    namespace = _validate_plain_directory(root.parent, expected_name=_NAMESPACE)
    _validate_plain_directory(namespace.parent, expected_name="development")
    return root


def _validate_plain_directory(path: Path, *, expected_name: str) -> Path:
    if path.name != expected_name:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID") from None
    if not stat.S_ISDIR(info.st_mode) or _is_reparse(info):
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    if os.path.normcase(os.path.abspath(path)) != os.path.normcase(str(resolved)):
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    return resolved


def _is_reparse(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _directory_identity(path: Path) -> tuple[int, int, int]:
    try:
        info = path.lstat()
    except OSError:
        raise _fail("HK_TOTAL_RETURN_IO_FAILED") from None
    if not stat.S_ISDIR(info.st_mode) or _is_reparse(info):
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    return (info.st_dev, info.st_ino, info.st_mode)


def _write_exclusive(path: Path, payload: bytes) -> tuple[int, int, int]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID") from None
    except OSError:
        raise _fail("HK_TOTAL_RETURN_IO_FAILED") from None
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError
            view = view[written:]
        os.fsync(fd)
        info = os.fstat(fd)
    except OSError:
        raise _fail("HK_TOTAL_RETURN_IO_FAILED") from None
    finally:
        os.close(fd)
    return (info.st_dev, info.st_ino, info.st_size)


def _read_stable_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or _is_reparse(before):
            raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            os.close(fd)
        after = path.lstat()
    except HkTotalReturnResearchPriceError:
        raise
    except FileNotFoundError:
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID") from None
    except OSError:
        raise _fail("HK_TOTAL_RETURN_IO_FAILED") from None
    identities = {(item.st_dev, item.st_ino, item.st_size) for item in (before, opened, after)}
    if len(identities) != 1 or not stat.S_ISREG(after.st_mode) or _is_reparse(after):
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID")
    return b"".join(chunks)


def _rollback_created(
    created: list[tuple[Path, tuple[int, int, int], str]],
    root: Path,
    root_identity: tuple[int, int, int] | None,
) -> None:
    for path, identity, digest in reversed(created):
        try:
            info = path.lstat()
            current = (info.st_dev, info.st_ino, info.st_size)
            if (
                current == identity
                and stat.S_ISREG(info.st_mode)
                and _sha256(path.read_bytes()) == digest
            ):
                path.unlink()
        except OSError:
            pass
    if root_identity is not None:
        try:
            if _directory_identity(root) == root_identity:
                root.rmdir()
        except (OSError, HkTotalReturnResearchPriceError):
            pass


def _decode_canonical_json(raw: bytes) -> object:
    try:
        value = json.loads(raw.decode("utf-8"))
        if _canonical_bytes(value) != raw:
            raise ValueError
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, OverflowError):
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID") from None
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            _json_value(value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise _fail("HK_TOTAL_RETURN_PUBLICATION_INVALID") from None


def _hash_payload(value: object, code: str) -> str:
    try:
        return hashlib.sha256(_canonical_bytes(value)).hexdigest()
    except HkTotalReturnResearchPriceError:
        raise _fail(code) from None


def _json_value(value: object) -> object:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError
        return {"float64": format(0.0 if value == 0.0 else value, ".17g")}
    if type(value) is dt.datetime:
        if not _is_utc(value):
            raise ValueError
        return {"datetime_utc": _utc_text(value)}
    if type(value) is dt.date:
        return {"date": value.isoformat()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_hex(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _HEX


def _is_utc(value: object) -> bool:
    return (
        type(value) is dt.datetime
        and value.tzinfo is not None
        and value.utcoffset() == dt.timedelta(0)
    )


def _utc_text(value: dt.datetime) -> str:
    return value.isoformat(timespec="microseconds")


__all__ = [
    "HK_GROSS_TOTAL_RETURN_V1",
    "HkTotalReturnResearchPriceError",
    "VerifiedDevelopmentHkGrossTotalReturnPublication",
    "publish_development_hk_gross_total_return",
    "verify_development_hk_gross_total_return",
]
