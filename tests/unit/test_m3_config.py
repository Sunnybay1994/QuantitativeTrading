"""C0 strict M3 configuration, normalization, and identity boundaries."""

from __future__ import annotations

import datetime as dt
import math
import traceback
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

import pytest

from quant.research.m3.config import (
    _FIELD_SPECS,
    _iter_assignment_leaves,
    ConfigIssue,
    LoadedM3Config,
    M3ConfigError,
    canonical_config_sha256,
    canonical_tracking_target_key,
    load_m3_config,
)

CONFIG_PATH = Path("configs/research/m3_qlib_example.toml")
SELECTOR_ATTRS = {
    "full": "full_config_sha256",
    "g1": "g1_config_sha256",
    "snapshot": "snapshot_config_sha256",
    "provider": "provider_config_sha256",
    "scientific": "scientific_config_sha256",
    "provider-validation": "provider_validation_config_sha256",
    "label-reconciliation": "label_reconciliation_config_sha256",
    "acceptance": "acceptance_config_sha256",
    "tracking-target": "tracking_target_key",
}


def _loaded() -> LoadedM3Config:
    return load_m3_config(CONFIG_PATH)


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    return value


def _document() -> dict[str, object]:
    return _thaw(_loaded().document)  # type: ignore[return-value]


def _nested(document: dict[str, object], *parts: str) -> dict[str, object]:
    current: object = document
    for part in parts:
        assert isinstance(current, dict)
        current = current[part]
    assert isinstance(current, dict)
    return current


def _issues(document: Mapping[str, object]) -> tuple[ConfigIssue, ...]:
    with pytest.raises(M3ConfigError) as caught:
        canonical_config_sha256(selector="full", document=document)
    return caught.value.issues


def _assert_issue(
    document: Mapping[str, object], code: str, dotted_path: str
) -> tuple[ConfigIssue, ...]:
    issues = _issues(document)
    assert any(issue.code == code and issue.dotted_path == dotted_path for issue in issues)
    return issues


def _identities(document: Mapping[str, object]) -> dict[str, str]:
    result = {
        selector: canonical_config_sha256(selector=selector, document=document)
        for selector in (
            "full",
            "g1",
            "snapshot",
            "provider",
            "scientific",
            "provider-validation",
            "label-reconciliation",
            "acceptance",
        )
    }
    tracking = document["tracking"]
    assert isinstance(tracking, Mapping)
    result["tracking-target"] = canonical_tracking_target_key(
        tracking_uri=tracking["tracking_uri"],  # type: ignore[arg-type]
        experiment_name=tracking["experiment_name"],  # type: ignore[arg-type]
    )
    return result


def test_valid_example_has_closed_shape_and_nine_bare_identities() -> None:
    loaded = _loaded()
    leaves = list(_iter_assignment_leaves(loaded.document, []))
    assert len(leaves) == 151
    shapes = {".".join(str(part) for part in ())}  # force a distinct local set
    shapes.clear()
    for tokens, _value in leaves:
        parts: list[str] = []
        for token in tokens:
            if isinstance(token, int):
                parts[-1] += "[]"
            else:
                parts.append(token)
        shapes.add(".".join(parts))
    assert len(_FIELD_SPECS) == 138
    assert shapes == set(_FIELD_SPECS)
    assert sum(not spec.required for spec in _FIELD_SPECS.values()) == 1
    assert all(spec.kind and spec.selectors <= set(SELECTOR_ATTRS) for spec in _FIELD_SPECS.values())
    for attr in SELECTOR_ATTRS.values():
        digest = getattr(loaded, attr)
        assert len(digest) == 64
        assert digest == digest.lower()
        assert all(char in "0123456789abcdef" for char in digest)
    assert loaded.config_version == "1.0.0"
    assert loaded.canonical_tracking_uri == "sqlite:///artifacts/research/m3/mlflow.db"
    assert loaded.document["data"]["start_date"] == dt.date(2016, 1, 4)
    assert loaded.document["data"]["end_date"] == dt.date(2026, 6, 26)
    assert (
        loaded.document["g1_backfill"]["membership_method_version"]
        == "tushare_monthly_observed_next_session_close_v1"
    )
    assert loaded.document["costs"]["a_share_periods"][0]["effective_from"] == dt.date(
        2016, 1, 1
    )
    assert set(_FIELD_SPECS["g1_backfill.membership_method_version"].selectors) == {"g1"}
    assert (
        _FIELD_SPECS["g1_backfill.membership_method_version"].literal
        == "tushare_monthly_observed_next_session_close_v1"
    )


def test_comments_whitespace_and_key_order_do_not_change_hashes(tmp_path: Path) -> None:
    original = CONFIG_PATH.read_text(encoding="utf-8")
    variant = original.replace(
        'config_version = "1.0.0"\npurpose = ',
        "# reordered meta keys\npurpose = ",
    ).replace(
        'enabled = false\n\n[data]',
        'enabled = false\nconfig_version = "1.0.0"\n\n\n[data]',
    )
    path = tmp_path / "variant.toml"
    path.write_text(variant, encoding="utf-8")
    left = _loaded()
    right = load_m3_config(path)
    assert {attr: getattr(left, attr) for attr in SELECTOR_ATTRS.values()} == {
        attr: getattr(right, attr) for attr in SELECTOR_ATTRS.values()
    }


def test_document_is_recursively_immutable_and_sections_have_no_defaults() -> None:
    loaded = _loaded()
    assert isinstance(loaded.document, MappingProxyType)
    with pytest.raises(TypeError):
        loaded.document["meta"] = {}  # type: ignore[index]
    data = loaded.section("data")
    with pytest.raises(TypeError):
        data["universe"] = "other"  # type: ignore[index]
    periods = loaded.section("costs")["a_share_periods"]
    assert isinstance(periods, tuple)
    with pytest.raises(TypeError):
        periods[0]["commission_rate"] = 1.0  # type: ignore[index]
    with pytest.raises(KeyError):
        loaded.section("missing")


def test_unknown_missing_and_strict_scalar_types_are_collected() -> None:
    document = _document()
    document["unknown"] = {"api-token": "plain"}
    del _nested(document, "data")["benchmark"]
    _nested(document, "data")["minimum_train_sessions"] = True
    _nested(document, "model", "lightgbm")["learning_rate"] = 1
    _nested(document, "features")["feature_version"] = ""
    issues = _issues(document)
    pairs = {(issue.code, issue.dotted_path) for issue in issues}
    assert ("UNKNOWN_KEY", "unknown.api-token") in pairs
    assert ("SECRET_VALUE", "unknown.api-token") in pairs
    assert ("MISSING_KEY", "data.benchmark") in pairs
    assert ("TYPE_ERROR", "data.minimum_train_sessions") in pairs
    assert ("TYPE_ERROR", "model.lightgbm.learning_rate") in pairs
    assert ("EMPTY_STRING", "features.feature_version") in pairs
    assert issues == tuple(sorted(issues, key=lambda item: (item.dotted_path, item.code, item.message)))


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_float_and_array_elements_are_rejected(bad: float) -> None:
    document = _document()
    _nested(document, "features")["minimum_scorable_coverage"] = bad
    _nested(document, "backtest", "a_share")["friction_multipliers"] = [0.5, bad, 2.0]
    issues = _issues(document)
    assert {issue.dotted_path for issue in issues if issue.code == "NON_FINITE"} >= {
        "features.minimum_scorable_coverage",
        "backtest.a_share.friction_multipliers",
    }


@pytest.mark.parametrize("bad", [dt.datetime(2026, 1, 1), dt.time(9, 30)])
def test_datetime_and_time_do_not_masquerade_as_date(bad: object) -> None:
    document = _document()
    _nested(document, "data")["start_date"] = bad
    _assert_issue(document, "TYPE_ERROR", "data.start_date")


def test_io_and_toml_parse_errors_are_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "token=DO_NOT_ECHO.toml"
    with pytest.raises(M3ConfigError) as missing_error:
        load_m3_config(missing)
    assert missing_error.value.issues[0].code == "CONFIG_IO_ERROR"
    assert str(tmp_path) not in str(missing_error.value)
    assert "DO_NOT_ECHO" not in repr(missing_error.value)

    with pytest.raises(M3ConfigError) as directory_error:
        load_m3_config(tmp_path)
    assert directory_error.value.issues[0].code == "CONFIG_IO_ERROR"

    valid = tmp_path / "valid.toml"
    valid.write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    original_read_bytes = Path.read_bytes

    def denied(path: Path) -> bytes:
        if path == valid:
            raise PermissionError("sensitive physical path")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(M3ConfigError) as unreadable_error:
        load_m3_config(valid)
    assert unreadable_error.value.issues[0].code == "CONFIG_IO_ERROR"
    assert "sensitive" not in str(unreadable_error.value)


def test_io_and_parse_errors_do_not_retain_or_format_sensitive_exception_chain(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "C0_PHYSICAL_PATH_SENTINEL.toml"
    with pytest.raises(M3ConfigError) as io_error:
        load_m3_config(missing)
    formatted_io = "".join(traceback.format_exception(io_error.value))
    assert "C0_PHYSICAL_PATH_SENTINEL" not in formatted_io
    assert io_error.value.__cause__ is None
    assert io_error.value.__context__ is None

    parse_path = tmp_path / "parse.toml"
    parse_sentinel = "C0_PARSE_INPUT_SENTINEL"
    parse_path.write_text(f'secret = "{parse_sentinel}\n', encoding="utf-8")
    with pytest.raises(M3ConfigError) as parse_error:
        load_m3_config(parse_path)
    formatted_parse = "".join(traceback.format_exception(parse_error.value))
    assert parse_sentinel not in formatted_parse
    assert str(parse_path) not in formatted_parse
    assert parse_error.value.__cause__ is None
    assert parse_error.value.__context__ is None


@pytest.mark.parametrize(
    "suffix",
    [
        '\n[meta]\nconfig_version = "1.0.0"\n',
        "\ninvalid_date = 2026-99-99\n",
        "\ninvalid = \"unterminated\n",
    ],
)
def test_duplicate_key_bad_date_and_parse_messages_are_sanitized(
    tmp_path: Path, suffix: str
) -> None:
    path = tmp_path / "parse.toml"
    path.write_text(CONFIG_PATH.read_text(encoding="utf-8") + suffix, encoding="utf-8")
    with pytest.raises(M3ConfigError) as caught:
        load_m3_config(path)
    assert caught.value.issues == (
        ConfigIssue("TOML_PARSE_ERROR", "config", "configuration must be valid UTF-8 TOML"),
    )
    assert str(path) not in repr(caught.value)


@pytest.mark.parametrize(
    ("mutator", "code", "path"),
    [
        (lambda d: _nested(d, "walk_forward").update(embargo_sessions=9), "CROSS_FIELD_ERROR", "walk_forward.embargo_sessions"),
        (lambda d: _nested(d, "labels").update(horizons_sessions=[10, 5]), "VALUE_ERROR", "labels.horizons_sessions"),
        (lambda d: _nested(d, "walk_forward").update(step_sessions=125), "CROSS_FIELD_ERROR", "walk_forward.step_sessions"),
        (lambda d: _nested(d, "data").update(required_fields=["open"]), "VALUE_ERROR", "data.required_fields"),
        (lambda d: _nested(d, "data").update(provider_fields=["open"]), "VALUE_ERROR", "data.provider_fields"),
        (lambda d: _nested(d, "portfolio").update(top_k=101), "CROSS_FIELD_ERROR", "portfolio.top_k"),
        (lambda d: _nested(d, "data").update(minimum_cross_section_symbols=301), "CROSS_FIELD_ERROR", "data.minimum_cross_section_symbols"),
        (lambda d: _nested(d, "evaluation").update(minimum_ic_symbols=1), "VALUE_ERROR", "evaluation.minimum_ic_symbols"),
        (lambda d: _nested(d, "g1_backfill").update(label_tail_sessions=9), "CROSS_FIELD_ERROR", "g1_backfill.label_tail_sessions"),
        (lambda d: _nested(d, "walk_forward").update(train_sessions=755), "CROSS_FIELD_ERROR", "walk_forward.train_sessions"),
        (lambda d: _nested(d, "validation", "provider").update(gap_dates_per_symbol=-1), "VALUE_ERROR", "validation.provider.gap_dates_per_symbol"),
        (lambda d: _nested(d, "validation", "labels").update(qlib_expression_atol=1e-5), "CROSS_FIELD_ERROR", "validation.labels.qlib_expression_atol"),
        (lambda d: _nested(d, "model", "lightgbm").update(early_stopping_rounds=500), "CROSS_FIELD_ERROR", "model.lightgbm.early_stopping_rounds"),
        (lambda d: _nested(d, "model", "lightgbm").update(max_depth=0), "VALUE_ERROR", "model.lightgbm.max_depth"),
    ],
)
def test_cross_field_and_numeric_invariants(
    mutator: object, code: str, path: str
) -> None:
    document = _document()
    mutator(document)  # type: ignore[operator]
    _assert_issue(document, code, path)


def test_extra_cash_below_capacity_is_valid() -> None:
    document = _document()
    _nested(document, "portfolio").update(top_k=10, max_weight=0.05, cash_buffer=0.05)
    digest = canonical_config_sha256(selector="scientific", document=document)
    assert len(digest) == 64


def test_cost_period_gaps_overlap_reverse_and_closed_tail_fail() -> None:
    for change, expected_path in (
        ((1, "effective_from", dt.date(2022, 4, 30)), "costs.a_share_periods[1].effective_from"),
        ((0, "effective_to", dt.date(2021, 12, 31)), "costs.a_share_periods[1].effective_from"),
        ((0, "effective_to", dt.date(2015, 12, 31)), "costs.a_share_periods[0].effective_to"),
        ((2, "effective_to", dt.date(2099, 1, 1)), "costs.a_share_periods[2].effective_to"),
    ):
        document = _document()
        periods = _nested(document, "costs")["a_share_periods"]
        assert isinstance(periods, list)
        periods[change[0]][change[1]] = change[2]
        issues = _issues(document)
        assert any(issue.dotted_path == expected_path for issue in issues)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("backtest.a_share.friction_multipliers", [0.5, 1.0]),
        ("backtest.a_share.friction_multipliers", [0.5, 1.0, 1.0]),
        ("validation.provider.sample_symbols", 2),
        ("g1_backfill.expected_constituent_count", 299),
        ("g1_backfill.feature_warmup_sessions", 59),
        ("g1_backfill.endpoint_row_limits.daily", 5999),
        ("g1_backfill.endpoint_row_limits.dividend", 5001),
    ],
)
def test_version_frozen_literals_reject_nearby_values(path: str, value: object) -> None:
    document = _document()
    parts = path.split(".")
    _nested(document, *parts[:-1])[parts[-1]] = value
    _assert_issue(document, "VALUE_ERROR", path)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("costs.a_share_periods.0.commission_rate", 0),
        ("costs.a_share_periods.0.commission_min", 5),
        ("costs.a_share_periods.0.stamp_tax_sell", 0),
        ("costs.a_share_periods.0.transfer_fee", 0),
        ("costs.a_share_periods.0.slippage", 0),
    ],
)
def test_cost_numeric_fields_require_exact_float(path: str, value: int) -> None:
    document = _document()
    periods = _nested(document, "costs")["a_share_periods"]
    assert isinstance(periods, list)
    name = path.rsplit(".", 1)[1]
    periods[0][name] = value
    _assert_issue(document, "TYPE_ERROR", f"costs.a_share_periods[0].{name}")


def test_secret_and_path_checks_precede_unknown_key_discard() -> None:
    document = _document()
    document["extra"] = {
        "api-token": "plain",
        "authorization": "Bearer TOPSECRET",
        "path": "C:\\private\\file",
        "unc": "\\\\server\\share",
        "encoded": "%2fetc%2fpasswd",
    }
    issues = _issues(document)
    pairs = {(issue.code, issue.dotted_path) for issue in issues}
    assert ("SECRET_VALUE", "extra.api-token") in pairs
    assert ("SECRET_VALUE", "extra.authorization") in pairs
    assert ("UNSAFE_PATH", "extra.path") in pairs
    assert ("UNSAFE_PATH", "extra.unc") in pairs
    assert ("UNSAFE_PATH", "extra.encoded") in pairs
    assert ("UNKNOWN_KEY", "extra.api-token") in pairs
    assert not any(
        forbidden in issue.message
        for issue in issues
        for forbidden in ("TOPSECRET", "C:\\private", "server")
    )


@pytest.mark.parametrize(
    "encoded_key",
    ["%74oken", "%2574oken", "api%2dkey", "private%252dkey"],
)
def test_percent_encoded_sensitive_quoted_keys_are_classified_before_unknown(
    encoded_key: str,
) -> None:
    document = _document()
    document["extra"] = {encoded_key: "plain"}
    issues = _issues(document)
    path = f"extra.{encoded_key}"
    assert ("SECRET_VALUE", path) in {(issue.code, issue.dotted_path) for issue in issues}
    assert ("UNKNOWN_KEY", path) in {(issue.code, issue.dotted_path) for issue in issues}
    assert all("plain" not in issue.message for issue in issues)
    # Fixed supply-chain SHA remains a legal value; no broad long-hex heuristic is used.
    assert _loaded().section("runtime")["qlib"]


@pytest.mark.parametrize(
    "uri",
    [
        "sqlite:////absolute.db",
        "sqlite:///../escape.db",
        "sqlite:///C:/private.db",
        "sqlite:///%2e%2e/private.db",
        "http://user%40example.com@host.invalid/",
        "https://host.invalid/%2fsecret",
        "https://host.invalid/%5csecret",
        "https://host.invalid/path/",
        "https://host.invalid/a//b",
        "https://host.invalid/a?ToKeN=secret",
        "https://host.invalid/a#fragment",
    ],
)
def test_unsafe_tracking_uri_variants_fail_without_echo(uri: str) -> None:
    with pytest.raises(M3ConfigError) as caught:
        canonical_tracking_target_key(tracking_uri=uri, experiment_name="experiment")
    assert any(issue.code in {"UNSAFE_URI", "SECRET_VALUE"} for issue in caught.value.issues)
    assert uri not in str(caught.value)
    assert uri not in repr(caught.value)


def test_http_target_normalization_removes_default_port_and_host_case() -> None:
    variants = (
        "HTTPS://Example.COM:443/api",
        "https://example.com/api",
    )
    keys = {
        canonical_tracking_target_key(tracking_uri=uri, experiment_name="m3")
        for uri in variants
    }
    assert len(keys) == 1


@pytest.mark.parametrize(
    ("experiment_name", "expected_code"),
    [
        ("/tmp/m3-experiment", "UNSAFE_PATH"),
        ("C:\\private\\m3", "UNSAFE_PATH"),
        ("\\\\server\\share", "UNSAFE_PATH"),
        ("folder\\experiment", "UNSAFE_PATH"),
        ("%2ftmp%2fm3", "UNSAFE_PATH"),
        ("bad\nname", "SECRET_VALUE"),
    ],
)
def test_tracking_target_direct_and_loader_share_experiment_name_safety(
    experiment_name: str,
    expected_code: str,
) -> None:
    with pytest.raises(M3ConfigError) as direct_error:
        canonical_tracking_target_key(
            tracking_uri="sqlite:///artifacts/research/m3/mlflow.db",
            experiment_name=experiment_name,
        )
    direct_pairs = {
        (issue.code, issue.dotted_path) for issue in direct_error.value.issues
    }
    assert (expected_code, "tracking.experiment_name") in direct_pairs

    document = _document()
    _nested(document, "tracking")["experiment_name"] = experiment_name
    loader_pairs = {
        (issue.code, issue.dotted_path) for issue in _issues(document)
    }
    assert (expected_code, "tracking.experiment_name") in loader_pairs


@pytest.mark.parametrize(
    ("mutator", "expected_path"),
    [
        (lambda document: document.__setitem__(1, "root"), "config"),
        (lambda document: _nested(document, "data").__setitem__(1, "nested"), "data"),
        (
            lambda document: _nested(document, "costs")["a_share_periods"][0].__setitem__(
                1, "period"
            ),
            "costs.a_share_periods[0]",
        ),
    ],
)
def test_direct_mapping_rejects_non_string_keys_before_coercion(
    mutator: object,
    expected_path: str,
) -> None:
    document = _document()
    mutator(document)  # type: ignore[operator]
    issues = _issues(document)
    assert ("TYPE_ERROR", expected_path) in {
        (issue.code, issue.dotted_path) for issue in issues
    }


def test_non_string_and_similar_string_keys_are_not_merged() -> None:
    document = _document()
    document[1] = "non-string"
    document["1"] = "string"
    pairs = {(issue.code, issue.dotted_path) for issue in _issues(document)}
    assert ("TYPE_ERROR", "config") in pairs
    assert ("UNKNOWN_KEY", "1") in pairs


def test_selector_propagation_for_valid_mutations() -> None:
    base_document = _document()
    base = _identities(base_document)
    cases = [
        (("tracking", "tracking_uri"), "sqlite:///artifacts/research/m3/other.db", {"full", "tracking-target"}),
        (("acceptance", "minimum_feature_coverage"), 0.97, {"full", "acceptance"}),
        (("validation", "labels", "label_return_atol"), 6e-6, {"full", "label-reconciliation"}),
        (("g1_backfill", "reconciliation", "price_atol"), 0.02, {"full", "g1"}),
        (("g1_backfill", "label_tail_sessions"), 11, {"full", "g1", "snapshot"}),
        (("g1_backfill", "retry_base_seconds"), 3.0, {"full"}),
        (("data", "start_date"), dt.date(2017, 1, 1), {"full", "snapshot", "scientific"}),
    ]
    for path, new_value, expected_changed in cases:
        document = _document()
        _nested(document, *path[:-1])[path[-1]] = new_value
        changed = _identities(document)
        actual_changed = {name for name in base if base[name] != changed[name]}
        assert actual_changed == expected_changed, path
        if path == ("data", "start_date"):
            unchanged = set(base) - expected_changed
            assert unchanged == {
                "g1",
                "provider",
                "provider-validation",
                "label-reconciliation",
                "acceptance",
                "tracking-target",
            }

    document = _document()
    periods = _nested(document, "costs")["a_share_periods"]
    assert isinstance(periods, list)
    periods[0]["commission_rate"] = 0.0003
    changed = _identities(document)
    assert {name for name in base if base[name] != changed[name]} == {"full", "scientific"}


def test_start_date_mutation_does_not_hardcode_example_session() -> None:
    """Loader accepts any typed date pair; example 2016-01-04 is not baked into validation."""
    base = _identities(_document())
    document = _document()
    _nested(document, "data")["start_date"] = dt.date(2018, 6, 1)
    loaded_digest = canonical_config_sha256(selector="full", document=document)
    assert len(loaded_digest) == 64
    changed = _identities(document)
    assert {name for name in base if base[name] != changed[name]} == {
        "full",
        "snapshot",
        "scientific",
    }
    assert changed["g1"] == base["g1"]


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        ("tushare_monthly_observed_next_open_v1", "VALUE_ERROR"),
        ("tushare_monthly_observed_next_session_close_v2", "VALUE_ERROR"),
        ("tushare_monthly_observed_next_session_close", "VALUE_ERROR"),
        (True, "TYPE_ERROR"),
        (None, "TYPE_ERROR"),
    ],
)
def test_membership_method_version_rejects_old_and_invalid_literals(
    bad: object, code: str
) -> None:
    document = _document()
    _nested(document, "g1_backfill")["membership_method_version"] = bad
    issues = _assert_issue(document, code, "g1_backfill.membership_method_version")
    text = " | ".join(f"{issue.code}:{issue.dotted_path}:{issue.message}" for issue in issues)
    # Public issues must stay path-scoped; never dump the whole config document.
    assert "Alpha158" not in text
    assert "sqlite:///artifacts" not in text
    assert str(CONFIG_PATH) not in text
    assert repr(document) not in text

def test_old_membership_literal_is_not_a_valid_hash_mutation() -> None:
    """Old method name is VALUE_ERROR, not a legal g1-only identity mutation."""
    document = _document()
    _nested(document, "g1_backfill")["membership_method_version"] = (
        "tushare_monthly_observed_next_open_v1"
    )
    with pytest.raises(M3ConfigError) as caught:
        _identities(document)
    assert any(
        issue.code == "VALUE_ERROR"
        and issue.dotted_path == "g1_backfill.membership_method_version"
        for issue in caught.value.issues
    )


def test_frozen_literal_selector_membership_and_public_rejection() -> None:
    expected = {
        "meta.config_version": {
            "g1",
            "snapshot",
            "provider",
            "scientific",
            "provider-validation",
            "label-reconciliation",
            "acceptance",
        },
        "validation.provider.sample_symbols": {"provider-validation"},
        "data.provider_fields": {"provider", "scientific"},
        "runtime.qlib.version": {"scientific"},
        "runtime.qlib.dump_script_sha256": set(),
        "runtime.qlib.supported_python": set(),
        "data.universe": {"snapshot", "scientific"},
        "g1_backfill.feature_warmup_sessions": {"g1", "snapshot"},
        "g1_backfill.endpoint_row_limits.daily": {"g1"},
        "g1_backfill.membership_method_version": {"g1"},
    }
    for path, selectors in expected.items():
        assert set(_FIELD_SPECS[path].selectors) == selectors
    method_selectors = set(_FIELD_SPECS["g1_backfill.membership_method_version"].selectors)
    assert "snapshot" not in method_selectors
    assert "scientific" not in method_selectors

    document = _document()
    _nested(document, "validation", "provider")["sample_symbols"] = 4
    _assert_issue(document, "VALUE_ERROR", "validation.provider.sample_symbols")


def test_direct_canonicalizer_rejects_partial_extra_and_version_mismatch() -> None:
    with pytest.raises(M3ConfigError):
        canonical_config_sha256(selector="scientific", document={"meta": {"config_version": "1.0.0"}})
    document = _document()
    document["extra"] = "value"
    _assert_issue(document, "UNKNOWN_KEY", "extra")
    document = _document()
    _nested(document, "meta")["config_version"] = "2.0.0"
    _assert_issue(document, "VALUE_ERROR", "meta.config_version")


def test_negative_zero_normalizes_to_zero() -> None:
    left = _document()
    right = _document()
    _nested(left, "model", "lightgbm")["early_stopping_min_delta"] = -0.0
    _nested(right, "model", "lightgbm")["early_stopping_min_delta"] = 0.0
    assert canonical_config_sha256(selector="scientific", document=left) == canonical_config_sha256(
        selector="scientific", document=right
    )


def test_corporate_action_factor_ratio_rtol_maximum() -> None:
    document = _document()
    path = "g1_backfill.corporate_action_reconciliation.factor_ratio_rtol"
    _nested(document, "g1_backfill", "corporate_action_reconciliation")[
        "factor_ratio_rtol"
    ] = 0.01
    canonical_config_sha256(selector="g1", document=document)
    document = _document()
    _nested(document, "g1_backfill", "corporate_action_reconciliation")[
        "factor_ratio_rtol"
    ] = 0.011
    _assert_issue(document, "VALUE_ERROR", path)
