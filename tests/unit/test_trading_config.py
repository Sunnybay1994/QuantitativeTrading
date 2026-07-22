"""M4-C0 strict trading configuration, safety defaults, and identity."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import cast

import pytest

from quant.execution.config import (
    ConfigIssue,
    TradingConfig,
    TradingConfigError,
    load_trading_config,
    trading_config_identity,
)

CONFIG_PATH = Path("configs/trading/example.toml")


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    return value


def _document() -> dict[str, object]:
    return _thaw(load_trading_config(CONFIG_PATH).document)  # type: ignore[return-value]


def _write_toml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "trading.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _valid_toml() -> str:
    return CONFIG_PATH.read_text(encoding="utf-8")


def _issues_from_text(tmp_path: Path, text: str) -> tuple[ConfigIssue, ...]:
    path = _write_toml(tmp_path, text)
    with pytest.raises(TradingConfigError) as caught:
        load_trading_config(path)
    return caught.value.issues


def _assert_issue(tmp_path: Path, text: str, code: str, dotted_path: str) -> None:
    issues = _issues_from_text(tmp_path, text)
    assert any(issue.code == code and issue.dotted_path == dotted_path for issue in issues)


def test_valid_example_loads_immutable_paper_defaults() -> None:
    loaded = load_trading_config(CONFIG_PATH)
    assert isinstance(loaded, TradingConfig)
    assert loaded.schema_version == "trading-config-v1"
    assert loaded.document["execution"]["mode"] == "PAPER"
    assert loaded.document["execution"]["auto_trade"] is False
    assert loaded.document["execution"]["manual_approval"] is True
    assert loaded.document["execution"]["sell_only"] is False
    assert loaded.document["execution"]["frozen_symbols"] == ()
    assert loaded.document["data"]["snapshot_max_age_seconds"] == 86400
    assert loaded.document["store"]["sqlite_uri"] == "sqlite:///artifacts/trading/execution.db"
    digest = trading_config_identity(loaded)
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(char in "0123456789abcdef" for char in digest)
    assert isinstance(loaded.document, MappingProxyType)
    with pytest.raises(TypeError):
        loaded.document["execution"] = {}  # type: ignore[index]


def test_comments_whitespace_and_key_order_do_not_change_identity(tmp_path: Path) -> None:
    original = _valid_toml()
    variant = (
        original.replace(
            'schema_version = "trading-config-v1"\n',
            '# reordered\nschema_version = "trading-config-v1"\n',
        )
        .replace(
            'mode = "PAPER"\nauto_trade = false',
            'auto_trade = false\nmode = "PAPER"',
        )
        .replace("\n\n[", "\n\n\n[")
    )
    path_a = _write_toml(tmp_path, original)
    path_b = tmp_path / "reordered.toml"
    path_b.write_text(variant, encoding="utf-8")
    assert trading_config_identity(load_trading_config(path_a)) == trading_config_identity(
        load_trading_config(path_b)
    )


def test_risk_threshold_change_changes_identity(tmp_path: Path) -> None:
    base = load_trading_config(CONFIG_PATH)
    mutated = _valid_toml().replace("max_symbol_weight = 0.10", "max_symbol_weight = 0.11")
    path = _write_toml(tmp_path, mutated)
    changed = load_trading_config(path)
    assert trading_config_identity(base) != trading_config_identity(changed)


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    text = _valid_toml().replace(
        'schema_version = "trading-config-v1"\n',
        'schema_version = "trading-config-v1"\nextra = 1\n',
    )
    _assert_issue(tmp_path, text, "UNKNOWN_KEY", "meta.extra")


def test_bool_cannot_masquerade_as_number(tmp_path: Path) -> None:
    text = _valid_toml().replace(
        "snapshot_max_age_seconds = 86400",
        "snapshot_max_age_seconds = true",
    )
    _assert_issue(tmp_path, text, "TYPE_ERROR", "data.snapshot_max_age_seconds")


def test_nan_and_inf_are_rejected(tmp_path: Path) -> None:
    text = _valid_toml().replace("max_order_notional = 1000000.0", "max_order_notional = nan")
    _assert_issue(tmp_path, text, "NON_FINITE", "risk.limits[0].max_order_notional")
    text_inf = _valid_toml().replace(
        "max_gross_exposure = 1.0",
        "max_gross_exposure = inf",
    )
    _assert_issue(tmp_path, text_inf, "NON_FINITE", "risk.limits[0].max_gross_exposure")
    assert not math.isfinite(float("nan"))


def test_live_mode_and_auto_trade_true_are_rejected(tmp_path: Path) -> None:
    live = _valid_toml().replace('mode = "PAPER"', 'mode = "LIVE"')
    _assert_issue(tmp_path, live, "VALUE_ERROR", "execution.mode")
    auto = _valid_toml().replace("auto_trade = false", "auto_trade = true")
    _assert_issue(tmp_path, auto, "VALUE_ERROR", "execution.auto_trade")


def test_absolute_personal_path_and_unsafe_sqlite_uri_are_rejected(tmp_path: Path) -> None:
    abs_path = _valid_toml().replace(
        'sqlite_uri = "sqlite:///artifacts/trading/execution.db"',
        'sqlite_uri = "sqlite:////home/someone/secrets/trading.db"',
    )
    _assert_issue(tmp_path, abs_path, "UNSAFE_URI", "store.sqlite_uri")
    windows = _valid_toml().replace(
        'sqlite_uri = "sqlite:///artifacts/trading/execution.db"',
        'sqlite_uri = "sqlite:///C:/Users/me/trading.db"',
    )
    _assert_issue(tmp_path, windows, "UNSAFE_URI", "store.sqlite_uri")


def test_risk_period_gap_and_overlap_are_rejected(tmp_path: Path) -> None:
    gap = """
[meta]
schema_version = "trading-config-v1"

[execution]
mode = "PAPER"
auto_trade = false
manual_approval = true
sell_only = false
frozen_symbols = []

[rules]
a_share_rule_selector = "a_share_execution_rules_v1"
hk_connect_rule_selector = "hk_connect_execution_rules_v1"
fee_schedule_selector = "a_share_research_cost_schedule_v1"
fx_schedule_selector = "cny_hkd_fx_schedule_v1"

[data]
snapshot_max_age_seconds = 86400

[store]
sqlite_uri = "sqlite:///artifacts/trading/execution.db"

[[risk.limits]]
effective_from = 2020-01-01
effective_to = 2023-12-31
max_order_notional = 1000000.0
max_symbol_weight = 0.10
max_gross_exposure = 1.0
max_daily_notional = 5000000.0
max_orders_per_day = 50
max_cancels_per_day = 20

[[risk.limits]]
effective_from = 2024-01-02
max_order_notional = 1000000.0
max_symbol_weight = 0.10
max_gross_exposure = 1.0
max_daily_notional = 5000000.0
max_orders_per_day = 50
max_cancels_per_day = 20
"""
    _assert_issue(tmp_path, gap, "CROSS_FIELD_ERROR", "risk.limits[1].effective_from")

    overlap = gap.replace(
        "effective_from = 2024-01-02",
        "effective_from = 2023-12-01",
    )
    _assert_issue(tmp_path, overlap, "CROSS_FIELD_ERROR", "risk.limits[1].effective_from")


def test_token_and_account_keys_are_rejected(tmp_path: Path) -> None:
    text = _valid_toml().replace(
        'schema_version = "trading-config-v1"\n',
        'schema_version = "trading-config-v1"\ntoken = "sk-abc"\n',
    )
    issues = _issues_from_text(tmp_path, text)
    assert any(issue.code == "SECRET_VALUE" for issue in issues)
    account = _valid_toml().replace(
        "[store]\n",
        '[store]\naccount_id = "ACC-001"\n',
    )
    issues = _issues_from_text(tmp_path, account)
    assert any(
        issue.code in {"SECRET_VALUE", "UNKNOWN_KEY"} and "account" in issue.dotted_path
        for issue in issues
    )


def test_shadow_mode_is_accepted(tmp_path: Path) -> None:
    text = _valid_toml().replace('mode = "PAPER"', 'mode = "SHADOW"')
    loaded = load_trading_config(_write_toml(tmp_path, text))
    assert loaded.document["execution"]["mode"] == "SHADOW"
    assert trading_config_identity(loaded) != trading_config_identity(
        load_trading_config(CONFIG_PATH)
    )


def test_frozen_symbols_are_canonical_sorted_unique(tmp_path: Path) -> None:
    text = _valid_toml().replace(
        "frozen_symbols = []",
        'frozen_symbols = ["000001.SZ", "600000.SH", "000001.SZ"]',
    )
    with pytest.raises(TradingConfigError) as caught:
        load_trading_config(_write_toml(tmp_path, text))
    assert any(
        issue.code == "VALUE_ERROR" and issue.dotted_path == "execution.frozen_symbols"
        for issue in caught.value.issues
    )
    ordered = _valid_toml().replace(
        "frozen_symbols = []",
        'frozen_symbols = ["600000.SH", "000001.SZ"]',
    )
    loaded = load_trading_config(_write_toml(tmp_path, ordered))
    assert loaded.document["execution"]["frozen_symbols"] == ("000001.SZ", "600000.SH")


def test_io_and_parse_errors_are_sanitized(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"
    with pytest.raises(TradingConfigError) as caught:
        load_trading_config(missing)
    assert caught.value.issues[0].code == "CONFIG_IO_ERROR"
    bad = _write_toml(tmp_path, "not = [valid")
    with pytest.raises(TradingConfigError) as caught_parse:
        load_trading_config(bad)
    assert caught_parse.value.issues[0].code == "TOML_PARSE_ERROR"


def test_risk_period_end_preceding_start_is_rejected(tmp_path: Path) -> None:
    doc = _document()
    # Build a single-period config with inverted dates via TOML
    text = _valid_toml().replace(
        "effective_from = 2016-01-01",
        "effective_from = 2025-01-01\neffective_to = 2020-01-01",
    )
    # Final open-ended period cannot have effective_to; use two-period fixture
    text = """
[meta]
schema_version = "trading-config-v1"

[execution]
mode = "PAPER"
auto_trade = false
manual_approval = true
sell_only = false
frozen_symbols = []

[rules]
a_share_rule_selector = "a_share_execution_rules_v1"
hk_connect_rule_selector = "hk_connect_execution_rules_v1"
fee_schedule_selector = "a_share_research_cost_schedule_v1"
fx_schedule_selector = "cny_hkd_fx_schedule_v1"

[data]
snapshot_max_age_seconds = 86400

[store]
sqlite_uri = "sqlite:///artifacts/trading/execution.db"

[[risk.limits]]
effective_from = 2025-01-01
effective_to = 2020-01-01
max_order_notional = 1000000.0
max_symbol_weight = 0.10
max_gross_exposure = 1.0
max_daily_notional = 5000000.0
max_orders_per_day = 50
max_cancels_per_day = 20

[[risk.limits]]
effective_from = 2020-01-02
max_order_notional = 1000000.0
max_symbol_weight = 0.10
max_gross_exposure = 1.0
max_daily_notional = 5000000.0
max_orders_per_day = 50
max_cancels_per_day = 20
"""
    issues = _issues_from_text(tmp_path, text)
    assert any(
        issue.code == "CROSS_FIELD_ERROR"
        and issue.dotted_path == "risk.limits[0].effective_to"
        for issue in issues
    )
    assert isinstance(doc["risk"]["limits"][0]["effective_from"], dt.date)


def test_direct_construct_live_mode_is_rejected() -> None:
    forged = cast(dict[str, object], _document())
    cast(dict[str, object], forged["execution"])["mode"] = "LIVE"
    with pytest.raises(TradingConfigError) as caught:
        TradingConfig(document=forged)
    assert any(
        issue.code == "VALUE_ERROR" and issue.dotted_path == "execution.mode"
        for issue in caught.value.issues
    )


def test_direct_construct_rejects_missing_unknown_and_non_finite() -> None:
    missing = cast(dict[str, object], _document())
    cast(dict[str, object], missing["execution"]).pop("mode")
    with pytest.raises(TradingConfigError) as missing_caught:
        TradingConfig(document=missing)
    assert any(
        issue.code == "MISSING_KEY" and issue.dotted_path == "execution.mode"
        for issue in missing_caught.value.issues
    )

    unknown = cast(dict[str, object], _document())
    cast(dict[str, object], unknown["meta"])["extra"] = 1
    with pytest.raises(TradingConfigError) as unknown_caught:
        TradingConfig(document=unknown)
    assert any(
        issue.code == "UNKNOWN_KEY" and issue.dotted_path == "meta.extra"
        for issue in unknown_caught.value.issues
    )

    non_finite = cast(dict[str, object], _document())
    limits = cast(list[dict[str, object]], cast(dict[str, object], non_finite["risk"])["limits"])
    limits[0]["max_order_notional"] = float("nan")
    with pytest.raises(TradingConfigError) as nan_caught:
        TradingConfig(document=non_finite)
    assert any(issue.code == "NON_FINITE" for issue in nan_caught.value.issues)

    inf_doc = cast(dict[str, object], _document())
    inf_limits = cast(list[dict[str, object]], cast(dict[str, object], inf_doc["risk"])["limits"])
    inf_limits[0]["max_gross_exposure"] = float("inf")
    with pytest.raises(TradingConfigError) as inf_caught:
        TradingConfig(document=inf_doc)
    assert any(issue.code == "NON_FINITE" for issue in inf_caught.value.issues)


def test_direct_construct_deep_freezes_caller_owned_mutables() -> None:
    mutable = cast(dict[str, object], _document())
    symbols = ["600000.SH", "000001.SZ"]
    cast(dict[str, object], mutable["execution"])["frozen_symbols"] = symbols
    loaded = TradingConfig(document=mutable)
    before = trading_config_identity(loaded)
    symbols.append("300001.SZ")
    cast(dict[str, object], mutable["execution"])["mode"] = "SHADOW"
    cast(list[object], cast(dict[str, object], mutable["risk"])["limits"]).clear()
    assert loaded.document["execution"]["mode"] == "PAPER"
    assert loaded.document["execution"]["frozen_symbols"] == ("000001.SZ", "600000.SH")
    assert trading_config_identity(loaded) == before


def test_divergent_schema_version_argument_is_rejected() -> None:
    loaded = load_trading_config(CONFIG_PATH)
    original = trading_config_identity(loaded)
    with pytest.raises(TypeError):
        TradingConfig(  # type: ignore[call-arg]
            document=loaded.document,
            schema_version="caller-forged-version",
        )
    assert trading_config_identity(loaded) == original
    assert loaded.schema_version == "trading-config-v1"


def test_version_selectors_reject_uri_and_omit_input_from_errors(tmp_path: Path) -> None:
    selector_keys = (
        "a_share_rule_selector",
        "hk_connect_rule_selector",
        "fee_schedule_selector",
        "fx_schedule_selector",
    )
    payloads = (
        "file:///home/user/private",
        "https://example.invalid/rules",
    )
    for key in selector_keys:
        for payload in payloads:
            original_line = next(
                line for line in _valid_toml().splitlines() if line.startswith(f"{key} = ")
            )
            mutated = _valid_toml().replace(original_line, f'{key} = "{payload}"', 1)
            issues = _issues_from_text(tmp_path, mutated)
            assert any(
                issue.code == "VALUE_ERROR" and issue.dotted_path == f"rules.{key}"
                for issue in issues
            )
            rendered = repr(issues)
            assert payload not in rendered
            for issue in issues:
                assert payload not in issue.message
                assert payload not in issue.dotted_path
