"""M4-D1 Repository Protocol + in-memory contract fake (fail-closed).

Based on pending-main-acceptance M4-D0 contracts. Does not open project data/.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import traceback
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from quant.data.repositories import (
    CleanAccountFactsBundle,
    CleanMarketFactsBundle,
    InMemoryAccountSnapshotRepository,
    InMemoryMarketDataRepository,
    RepositoryContractError,
    ValidatedCleanAccountSnapshotRepository,
    ValidatedCleanMarketDataRepository,
    reject_data_legacy_path,
)
from quant.domain.enums import ConnectRoute, Currency, Market
from quant.execution.contracts import (
    ContractError,
    VerifiedConnectMarketContext,
    build_account_snapshot,
    build_cash_balance,
    build_money_amount,
    build_position_balance,
    build_symbol_market_state,
    build_verified_connect_market_context,
    build_verified_connect_market_context_identity,
    build_verified_market_snapshot,
)
from quant.execution.ports import (
    AccountSnapshotRepository,
    ConnectMarketContextRepository,
    MarketDataRepository,
)

UTC = dt.timezone.utc
SESSION = dt.date(2026, 7, 15)


def _hex64(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _utc(hour: int = 8) -> dt.datetime:
    return dt.datetime(2026, 7, 15, hour, 0, 0, tzinfo=UTC)


def _state(
    symbol: str = "600000.SH",
    *,
    market: Market = Market.SH,
    session_date: dt.date = SESSION,
) -> object:
    currency = Currency.HKD if market is Market.HK else Currency.CNY
    return build_symbol_market_state(
        symbol=symbol,
        market=market,
        session_date=session_date,
        quote_currency=currency,
        reference_price=Decimal("10"),
        limit_up=Decimal("11") if market is not Market.HK else None,
        limit_down=Decimal("9") if market is not Market.HK else None,
        suspended=False,
        board_lot=100,
        tick_size=Decimal("0.01"),
        rule_version="rule-v1",
    )


def _market_snapshot(
    *,
    symbols: tuple[str, ...] = ("600000.SH",),
    as_of: dt.datetime | None = None,
    session_date: dt.date = SESSION,
    connect_contexts: tuple[object, ...] = (),
) -> object:
    states = tuple(
        _state(
            symbol=symbol,
            market=(
                Market.HK
                if symbol.endswith(".HK")
                else Market.SZ
                if symbol.endswith(".SZ")
                else Market.SH
            ),
            session_date=session_date,
        )
        for symbol in symbols
    )
    return build_verified_market_snapshot(
        as_of=as_of or _utc(8),
        session_date=session_date,
        states=states,
        connect_contexts=connect_contexts,
        calendar_identity=_hex64("cal"),
        source_identity=_hex64("src"),
    )


def _account_snapshot(*, as_of: dt.datetime | None = None) -> object:
    return build_account_snapshot(
        as_of=as_of or _utc(8),
        positions=(
            build_position_balance(
                symbol="600000.SH",
                market=Market.SH,
                quantity=100,
                sellable_quantity=100,
                avg_cost=build_money_amount(Currency.CNY, Decimal("10")),
            ),
        ),
        cash=(
            build_cash_balance(
                currency=Currency.CNY,
                settled=Decimal("10000"),
                available=Decimal("10000"),
                receivable=Decimal("0"),
                payable=Decimal("0"),
            ),
        ),
    )


def _connect_ctx(
    *,
    route: ConnectRoute = ConnectRoute.SH_CONNECT,
    session_date: dt.date = SESSION,
    as_of: dt.datetime | None = None,
    buy_quota_available: bool = True,
    quota_identity: str | None = None,
) -> VerifiedConnectMarketContext:
    return build_verified_connect_market_context(
        route=route,
        session_date=session_date,
        as_of=as_of or _utc(8),
        mainland_open=True,
        hong_kong_open=True,
        buy_quota_available=buy_quota_available,
        calendar_identity=_hex64("cal"),
        quota_identity=quota_identity or _hex64("quota"),
        source_identity=_hex64("src"),
    )


def test_protocol_signatures_have_no_path_parameters() -> None:
    for name, method in (
        (
            "load_verified_market_snapshot",
            MarketDataRepository.load_verified_market_snapshot,
        ),
        ("load_account_snapshot", AccountSnapshotRepository.load_account_snapshot),
    ):
        params = set(inspect.signature(method).parameters)
        forbidden = {"root", "path", "glob", "data_root", "legacy"}
        assert forbidden.isdisjoint(params), name
        assert "as_of" in params
    market_params = set(
        inspect.signature(MarketDataRepository.load_verified_market_snapshot).parameters
    )
    assert "connect_routes" in market_params


def test_inmemory_market_happy_path_and_protocol() -> None:
    snap = _market_snapshot(symbols=("600000.SH", "000001.SZ"))
    repo = InMemoryMarketDataRepository(
        {(SESSION, frozenset({"600000.SH", "000001.SZ"})): snap}
    )
    assert isinstance(repo, MarketDataRepository)
    loaded = repo.load_verified_market_snapshot(
        symbols=("600000.SH", "000001.SZ"),
        session_date=SESSION,
        as_of=_utc(10),
        connect_routes=(),
    )
    assert loaded.snapshot_id == snap.snapshot_id
    assert len(loaded.states) == 2


def test_inmemory_rejects_legacy_path_wiring() -> None:
    with pytest.raises(RepositoryContractError) as exc:
        reject_data_legacy_path(Path("data/legacy/bars"))
    assert exc.value.code == "LEGACY_PATH_REJECTED"

    with pytest.raises(RepositoryContractError) as exc2:
        InMemoryMarketDataRepository(
            {},
            configured_paths=(Path("data/legacy/raw"),),
        )
    assert exc2.value.code == "LEGACY_PATH_REJECTED"


def test_inmemory_pit_violation_when_snapshot_newer_than_as_of() -> None:
    snap = _market_snapshot(as_of=_utc(12))
    repo = InMemoryMarketDataRepository({(SESSION, frozenset({"600000.SH"})): snap})
    with pytest.raises(RepositoryContractError) as exc:
        repo.load_verified_market_snapshot(
            symbols=("600000.SH",),
            session_date=SESSION,
            as_of=_utc(8),
            connect_routes=(),
        )
    assert exc.value.code == "PIT_VIOLATION"


def test_inmemory_duplicate_key_rejected() -> None:
    state = _state("600000.SH")
    with pytest.raises(RepositoryContractError) as exc:
        InMemoryMarketDataRepository.from_states(
            session_date=SESSION,
            as_of=_utc(8),
            states=(state, state),
            connect_contexts=(),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
        )
    assert exc.value.code == "DUPLICATE_KEY"


def test_inmemory_missing_and_superset_symbols() -> None:
    snap = _market_snapshot(symbols=("600000.SH", "000001.SZ"))
    repo = InMemoryMarketDataRepository(
        {(SESSION, frozenset({"600000.SH", "000001.SZ"})): snap}
    )
    with pytest.raises(RepositoryContractError) as exc_miss:
        repo.load_verified_market_snapshot(
            symbols=("600000.SH", "000001.SZ", "600519.SH"),
            session_date=SESSION,
            as_of=_utc(10),
            connect_routes=(),
        )
    assert exc_miss.value.code == "MISSING_SYMBOL"

    with pytest.raises(RepositoryContractError) as exc_extra:
        repo.load_verified_market_snapshot(
            symbols=("600000.SH",),
            session_date=SESSION,
            as_of=_utc(10),
            connect_routes=(),
        )
    assert exc_extra.value.code == "SYMBOL_SUPERSET"


def test_validated_clean_market_composes_reader_and_quality_gate() -> None:
    state = _state("600000.SH")

    def reader(
        *, symbols: tuple[str, ...], session_date: dt.date, as_of: dt.datetime
    ) -> CleanMarketFactsBundle:
        del as_of
        assert symbols == ("600000.SH",)
        assert session_date == SESSION
        return CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=(state,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
            quality_passed=True,
        )

    repo = ValidatedCleanMarketDataRepository(read_market_facts=reader)
    assert isinstance(repo, MarketDataRepository)
    out = repo.load_verified_market_snapshot(
        symbols=("600000.SH",),
        session_date=SESSION,
        as_of=_utc(9),
        connect_routes=(),
    )
    assert out.states[0].symbol == "600000.SH"
    assert out.as_of == _utc(7)
    assert out.connect_contexts == ()


def test_validated_clean_market_quality_gate_fail_closed() -> None:
    state = _state("600000.SH")

    def reader(
        *, symbols: tuple[str, ...], session_date: dt.date, as_of: dt.datetime
    ) -> CleanMarketFactsBundle:
        del symbols, session_date, as_of
        return CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=(state,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
            quality_passed=False,
        )

    repo = ValidatedCleanMarketDataRepository(read_market_facts=reader)
    with pytest.raises(RepositoryContractError) as exc:
        repo.load_verified_market_snapshot(
            symbols=("600000.SH",),
            session_date=SESSION,
            as_of=_utc(9),
            connect_routes=(),
        )
    assert exc.value.code == "QUALITY_GATE_FAILED"


def test_validated_clean_rejects_legacy_configured_path() -> None:
    def reader(
        *, symbols: tuple[str, ...], session_date: dt.date, as_of: dt.datetime
    ) -> CleanMarketFactsBundle:
        del symbols, session_date, as_of
        raise AssertionError("reader must not run")

    with pytest.raises(RepositoryContractError) as exc:
        ValidatedCleanMarketDataRepository(
            read_market_facts=reader,
            configured_paths=(Path("proj") / "data" / "legacy" / "x",),
        )
    assert exc.value.code == "LEGACY_PATH_REJECTED"


def test_inmemory_account_and_validated_account() -> None:
    account = _account_snapshot(as_of=_utc(8))
    mem = InMemoryAccountSnapshotRepository({_utc(8): account})
    assert isinstance(mem, AccountSnapshotRepository)
    assert mem.load_account_snapshot(as_of=_utc(10)).snapshot_id == account.snapshot_id

    with pytest.raises(RepositoryContractError) as exc_pit:
        mem.load_account_snapshot(as_of=_utc(6))
    assert exc_pit.value.code == "PIT_VIOLATION"

    def acct_reader(*, as_of: dt.datetime) -> CleanAccountFactsBundle:
        del as_of
        return CleanAccountFactsBundle(
            known_as_of=_utc(8),
            positions=account.positions,
            cash=account.cash,
            quality_passed=True,
        )

    prod = ValidatedCleanAccountSnapshotRepository(read_account_facts=acct_reader)
    assert isinstance(prod, AccountSnapshotRepository)
    loaded = prod.load_account_snapshot(as_of=_utc(10))
    assert loaded.snapshot_id == account.snapshot_id


def test_validated_no_partial_on_missing_symbol() -> None:
    state = _state("600000.SH")

    def reader(
        *, symbols: tuple[str, ...], session_date: dt.date, as_of: dt.datetime
    ) -> CleanMarketFactsBundle:
        del symbols, session_date, as_of
        return CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=(state,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
            quality_passed=True,
        )

    repo = ValidatedCleanMarketDataRepository(read_market_facts=reader)
    with pytest.raises(RepositoryContractError) as exc:
        repo.load_verified_market_snapshot(
            symbols=("600000.SH", "000001.SZ"),
            session_date=SESSION,
            as_of=_utc(9),
            connect_routes=(),
        )
    assert exc.value.code == "MISSING_SYMBOL"


def _assert_sanitized_repo_error(
    exc: RepositoryContractError,
    *,
    code: str,
    forbidden: tuple[str, ...],
) -> None:
    assert exc.code == code
    assert exc.__cause__ is None
    assert exc.__context__ is None
    text = f"{exc!s}\n{exc!r}\n" + "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    for token in forbidden:
        assert token not in text


def _bypass_market_bundle(
    *,
    known_as_of: dt.datetime,
    states: object,
    calendar_identity: object,
    source_identity: object,
    quality_passed: object,
) -> CleanMarketFactsBundle:
    bundle = object.__new__(CleanMarketFactsBundle)
    object.__setattr__(bundle, "known_as_of", known_as_of)
    object.__setattr__(bundle, "states", states)
    object.__setattr__(bundle, "calendar_identity", calendar_identity)
    object.__setattr__(bundle, "source_identity", source_identity)
    object.__setattr__(bundle, "quality_passed", quality_passed)
    return bundle


def _bypass_account_bundle(
    *,
    known_as_of: dt.datetime,
    positions: object,
    cash: object,
    quality_passed: object,
) -> CleanAccountFactsBundle:
    bundle = object.__new__(CleanAccountFactsBundle)
    object.__setattr__(bundle, "known_as_of", known_as_of)
    object.__setattr__(bundle, "positions", positions)
    object.__setattr__(bundle, "cash", cash)
    object.__setattr__(bundle, "quality_passed", quality_passed)
    return bundle


def test_inmemory_market_rejects_key_content_and_forged_identity() -> None:
    snap_a = _market_snapshot(symbols=("600000.SH",))
    other_day = SESSION + dt.timedelta(days=1)
    with pytest.raises(RepositoryContractError) as exc_date:
        InMemoryMarketDataRepository({(other_day, frozenset({"600000.SH"})): snap_a})
    assert exc_date.value.code == "KEY_CONTENT_MISMATCH"

    with pytest.raises(RepositoryContractError) as exc_symbols:
        InMemoryMarketDataRepository({(SESSION, frozenset({"000001.SZ"})): snap_a})
    assert exc_symbols.value.code == "KEY_CONTENT_MISMATCH"

    forged = _market_snapshot(symbols=("600000.SH",))
    object.__setattr__(forged, "snapshot_id", "0" * 64)
    with pytest.raises(RepositoryContractError) as exc_id:
        InMemoryMarketDataRepository({(SESSION, frozenset({"600000.SH"})): forged})
    assert exc_id.value.code == "DOMAIN_CONTRACT"
    assert exc_id.value.__cause__ is None


def test_inmemory_account_rejects_key_mismatch_non_utc_and_forged_identity() -> None:
    account = _account_snapshot(as_of=_utc(8))
    with pytest.raises(RepositoryContractError) as exc_key:
        InMemoryAccountSnapshotRepository({_utc(10): account})
    assert exc_key.value.code == "KEY_CONTENT_MISMATCH"

    cst = dt.timezone(dt.timedelta(hours=8))
    non_utc = dt.datetime(2026, 7, 15, 16, 0, 0, tzinfo=cst)
    with pytest.raises(RepositoryContractError) as exc_tz:
        InMemoryAccountSnapshotRepository({non_utc: account})
    assert exc_tz.value.code == "INVALID_AS_OF"

    forged = _account_snapshot(as_of=_utc(8))
    object.__setattr__(forged, "snapshot_id", "a" * 64)
    with pytest.raises(RepositoryContractError) as exc_id:
        InMemoryAccountSnapshotRepository({_utc(8): forged})
    assert exc_id.value.code == "DOMAIN_CONTRACT"
    assert exc_id.value.__cause__ is None


def test_clean_bundles_reject_non_bool_wrong_element_list_and_bad_identity() -> None:
    state = _state("600000.SH")
    account = _account_snapshot(as_of=_utc(8))

    with pytest.raises(RepositoryContractError) as exc_m1:
        CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=(state,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
            quality_passed=1,  # type: ignore[arg-type]
        )
    assert exc_m1.value.code == "INVALID_READER_RESULT"

    with pytest.raises(RepositoryContractError) as exc_m0:
        CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=(state,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
            quality_passed=0,  # type: ignore[arg-type]
        )
    assert exc_m0.value.code == "INVALID_READER_RESULT"

    with pytest.raises(RepositoryContractError) as exc_m_list:
        CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=[state],  # type: ignore[arg-type]
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
            quality_passed=True,
        )
    assert exc_m_list.value.code == "INVALID_READER_RESULT"

    with pytest.raises(RepositoryContractError) as exc_m_el:
        CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=("bad",),  # type: ignore[arg-type]
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
            quality_passed=True,
        )
    assert exc_m_el.value.code == "INVALID_READER_RESULT"

    with pytest.raises(RepositoryContractError) as exc_m_id:
        CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=(state,),
            calendar_identity="not-hex",
            source_identity=_hex64("src"),
            quality_passed=True,
        )
    assert exc_m_id.value.code == "INVALID_READER_RESULT"

    with pytest.raises(RepositoryContractError) as exc_a1:
        CleanAccountFactsBundle(
            known_as_of=_utc(8),
            positions=account.positions,
            cash=account.cash,
            quality_passed=1,  # type: ignore[arg-type]
        )
    assert exc_a1.value.code == "INVALID_READER_RESULT"

    with pytest.raises(RepositoryContractError) as exc_a0:
        CleanAccountFactsBundle(
            known_as_of=_utc(8),
            positions=account.positions,
            cash=account.cash,
            quality_passed=0,  # type: ignore[arg-type]
        )
    assert exc_a0.value.code == "INVALID_READER_RESULT"

    with pytest.raises(RepositoryContractError) as exc_a_list:
        CleanAccountFactsBundle(
            known_as_of=_utc(8),
            positions=list(account.positions),  # type: ignore[arg-type]
            cash=account.cash,
            quality_passed=True,
        )
    assert exc_a_list.value.code == "INVALID_READER_RESULT"

    with pytest.raises(RepositoryContractError) as exc_a_el:
        CleanAccountFactsBundle(
            known_as_of=_utc(8),
            positions=("bad",),  # type: ignore[arg-type]
            cash=account.cash,
            quality_passed=True,
        )
    assert exc_a_el.value.code == "INVALID_READER_RESULT"

    # Repository must not treat truthy non-bool as quality pass / AttributeError.
    bad_quality = _bypass_market_bundle(
        known_as_of=_utc(7),
        states=(state,),
        calendar_identity=_hex64("cal"),
        source_identity=_hex64("src"),
        quality_passed=1,
    )

    def reader_quality(
        *, symbols: tuple[str, ...], session_date: dt.date, as_of: dt.datetime
    ) -> CleanMarketFactsBundle:
        del symbols, session_date, as_of
        return bad_quality

    repo_q = ValidatedCleanMarketDataRepository(read_market_facts=reader_quality)
    with pytest.raises(RepositoryContractError) as exc_rq:
        repo_q.load_verified_market_snapshot(
            symbols=("600000.SH",),
            session_date=SESSION,
            as_of=_utc(9),
            connect_routes=(),
        )
    assert exc_rq.value.code == "INVALID_READER_RESULT"

    bad_states = _bypass_market_bundle(
        known_as_of=_utc(7),
        states=("bad",),
        calendar_identity=_hex64("cal"),
        source_identity=_hex64("src"),
        quality_passed=True,
    )

    def reader_states(
        *, symbols: tuple[str, ...], session_date: dt.date, as_of: dt.datetime
    ) -> CleanMarketFactsBundle:
        del symbols, session_date, as_of
        return bad_states

    repo_s = ValidatedCleanMarketDataRepository(read_market_facts=reader_states)
    with pytest.raises(RepositoryContractError) as exc_rs:
        repo_s.load_verified_market_snapshot(
            symbols=("600000.SH",),
            session_date=SESSION,
            as_of=_utc(9),
            connect_routes=(),
        )
    assert exc_rs.value.code == "INVALID_READER_RESULT"
    assert not isinstance(exc_rs.value, AttributeError)


def test_market_and_account_reader_oserror_sanitized() -> None:
    wsl_path = "/home/user/private/market.parquet"
    win_path = r"C:\Users\secret\account.parquet"

    def market_reader(
        *, symbols: tuple[str, ...], session_date: dt.date, as_of: dt.datetime
    ) -> CleanMarketFactsBundle:
        del symbols, session_date, as_of
        raise OSError(wsl_path)

    market_repo = ValidatedCleanMarketDataRepository(read_market_facts=market_reader)
    with pytest.raises(RepositoryContractError) as exc_m:
        market_repo.load_verified_market_snapshot(
            symbols=("600000.SH",),
            session_date=SESSION,
            as_of=_utc(9),
            connect_routes=(),
        )
    _assert_sanitized_repo_error(exc_m.value, code="READER_FAILURE", forbidden=(wsl_path,))

    def account_reader(*, as_of: dt.datetime) -> CleanAccountFactsBundle:
        del as_of
        raise OSError(win_path)

    account_repo = ValidatedCleanAccountSnapshotRepository(read_account_facts=account_reader)
    with pytest.raises(RepositoryContractError) as exc_a:
        account_repo.load_account_snapshot(as_of=_utc(10))
    _assert_sanitized_repo_error(
        exc_a.value,
        code="READER_FAILURE",
        forbidden=(win_path, r"C:\Users\secret", "Users\\secret"),
    )


def test_domain_and_from_states_errors_sanitized() -> None:
    leak = "/home/user/private/domain-secret.parquet"
    state = _state("600000.SH")
    with pytest.raises(RepositoryContractError) as exc_fs:
        InMemoryMarketDataRepository.from_states(
            session_date=SESSION + dt.timedelta(days=1),
            as_of=_utc(8),
            states=(state,),
            connect_contexts=(),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
        )
    _assert_sanitized_repo_error(
        exc_fs.value,
        code="DOMAIN_CONTRACT",
        forbidden=(leak,),
    )

    def reader(
        *, symbols: tuple[str, ...], session_date: dt.date, as_of: dt.datetime
    ) -> CleanMarketFactsBundle:
        del symbols, session_date, as_of
        return CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=(state,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
            quality_passed=True,
        )

    repo = ValidatedCleanMarketDataRepository(read_market_facts=reader)
    with patch(
        "quant.data.repositories.build_verified_market_snapshot",
        side_effect=ContractError(leak),
    ):
        with pytest.raises(RepositoryContractError) as exc_dom:
            repo.load_verified_market_snapshot(
                symbols=("600000.SH",),
                session_date=SESSION,
                as_of=_utc(9),
                connect_routes=(),
            )
    _assert_sanitized_repo_error(
        exc_dom.value,
        code="DOMAIN_CONTRACT",
        forbidden=(leak,),
    )


def test_connect_market_context_protocol_runtime_checkable() -> None:
    class GoodFake:
        def load_verified_connect_market_context(
            self,
            *,
            route: ConnectRoute,
            session_date: dt.date,
            as_of: dt.datetime,
        ) -> object:
            return _connect_ctx(route=route, session_date=session_date, as_of=as_of)

    class MissingMethodFake:
        pass

    good = GoodFake()
    assert isinstance(good, ConnectMarketContextRepository)
    assert not isinstance(MissingMethodFake(), ConnectMarketContextRepository)

    loaded = good.load_verified_connect_market_context(
        route=ConnectRoute.SH_CONNECT,
        session_date=SESSION,
        as_of=_utc(10),
    )
    assert isinstance(loaded, VerifiedConnectMarketContext)
    assert loaded.route is ConnectRoute.SH_CONNECT
    assert loaded.session_date == SESSION
    assert loaded.as_of <= _utc(10)
    assert loaded.context_id == build_verified_connect_market_context_identity(loaded)


def test_connect_market_context_runtime_checkable_not_return_closure() -> None:
    """isinstance only sees the method name; return closure is adapter/caller duty."""

    class WrongSignatureFake:
        def load_verified_connect_market_context(
            self,
            *,
            market: ConnectRoute,
            day: dt.date,
            when: dt.datetime,
        ) -> object:
            del market, day, when
            return _connect_ctx()

    class WrongRouteFake:
        def load_verified_connect_market_context(
            self,
            *,
            route: ConnectRoute,
            session_date: dt.date,
            as_of: dt.datetime,
        ) -> object:
            del route
            return _connect_ctx(
                route=ConnectRoute.SZ_CONNECT,
                session_date=session_date,
                as_of=as_of,
            )

    class FutureAsOfFake:
        def load_verified_connect_market_context(
            self,
            *,
            route: ConnectRoute,
            session_date: dt.date,
            as_of: dt.datetime,
        ) -> object:
            return _connect_ctx(
                route=route,
                session_date=session_date,
                as_of=as_of + dt.timedelta(hours=1),
            )

    class WrongReturnTypeFake:
        def load_verified_connect_market_context(
            self,
            *,
            route: ConnectRoute,
            session_date: dt.date,
            as_of: dt.datetime,
        ) -> object:
            del route, session_date, as_of
            return SimpleNamespace(context_id="0" * 64)

    for fake in (
        WrongSignatureFake(),
        WrongRouteFake(),
        FutureAsOfFake(),
        WrongReturnTypeFake(),
    ):
        assert isinstance(fake, ConnectMarketContextRepository)

    query_route = ConnectRoute.SH_CONNECT
    query_as_of = _utc(8)
    wrong_route = WrongRouteFake().load_verified_connect_market_context(
        route=query_route,
        session_date=SESSION,
        as_of=query_as_of,
    )
    assert isinstance(wrong_route, VerifiedConnectMarketContext)
    assert wrong_route.route is not query_route

    future = FutureAsOfFake().load_verified_connect_market_context(
        route=query_route,
        session_date=SESSION,
        as_of=query_as_of,
    )
    assert isinstance(future, VerifiedConnectMarketContext)
    assert future.as_of > query_as_of

    wrong_type = WrongReturnTypeFake().load_verified_connect_market_context(
        route=query_route,
        session_date=SESSION,
        as_of=query_as_of,
    )
    assert not isinstance(wrong_type, VerifiedConnectMarketContext)


def test_connect_market_context_port_import_isolation() -> None:
    ports_path = Path(__file__).resolve().parents[2] / "src" / "quant" / "execution" / "ports.py"
    source = ports_path.read_text(encoding="utf-8")
    assert "quant.data" not in source
    assert "quant.backtest" not in source
    assert "data/" not in source
    params = set(
        inspect.signature(
            ConnectMarketContextRepository.load_verified_connect_market_context
        ).parameters
    )
    assert {"route", "session_date", "as_of"} <= params
    assert {"root", "path", "glob", "data_root", "legacy", "AUTO", "ANY"}.isdisjoint(
        params
    )


def test_connect_routes_reject_string_list_unsorted_duplicate_fake_bool_int() -> None:
    state = _state("600000.SH")

    def reader(
        *, symbols: tuple[str, ...], session_date: dt.date, as_of: dt.datetime
    ) -> CleanMarketFactsBundle:
        del symbols, session_date, as_of
        return CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=(state,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
            quality_passed=True,
        )

    repo = ValidatedCleanMarketDataRepository(read_market_facts=reader)
    snap = _market_snapshot()
    mem = InMemoryMarketDataRepository({(SESSION, frozenset({"600000.SH"})): snap})

    class FakeRoute(str, Enum):
        SH_CONNECT = "SH_CONNECT"

    bad_cases: tuple[object, ...] = (
        "SH_CONNECT",
        [ConnectRoute.SH_CONNECT],
        (ConnectRoute.SZ_CONNECT, ConnectRoute.SH_CONNECT),
        (ConnectRoute.SH_CONNECT, ConnectRoute.SH_CONNECT),
        (FakeRoute.SH_CONNECT,),
        (True,),
        (1,),
    )
    for bad in bad_cases:
        with pytest.raises(RepositoryContractError) as exc_v:
            repo.load_verified_market_snapshot(
                symbols=("600000.SH",),
                session_date=SESSION,
                as_of=_utc(9),
                connect_routes=bad,  # type: ignore[arg-type]
            )
        assert exc_v.value.code == "INVALID_CONNECT_ROUTES"
        with pytest.raises(RepositoryContractError) as exc_m:
            mem.load_verified_market_snapshot(
                symbols=("600000.SH",),
                session_date=SESSION,
                as_of=_utc(9),
                connect_routes=bad,  # type: ignore[arg-type]
            )
        assert exc_m.value.code == "INVALID_CONNECT_ROUTES"


def test_hk_states_require_routes_and_context_repository_fail_closed() -> None:
    hk_state = _state("00700.HK", market=Market.HK)

    def reader(
        *, symbols: tuple[str, ...], session_date: dt.date, as_of: dt.datetime
    ) -> CleanMarketFactsBundle:
        del symbols, session_date, as_of
        return CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=(hk_state,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
            quality_passed=True,
        )

    repo_no_ctx = ValidatedCleanMarketDataRepository(read_market_facts=reader)
    with pytest.raises(RepositoryContractError) as exc_empty:
        repo_no_ctx.load_verified_market_snapshot(
            symbols=("00700.HK",),
            session_date=SESSION,
            as_of=_utc(9),
            connect_routes=(),
        )
    assert exc_empty.value.code == "CONNECT_CONTEXT_REQUIRED"

    with pytest.raises(RepositoryContractError) as exc_repo:
        repo_no_ctx.load_verified_market_snapshot(
            symbols=("00700.HK",),
            session_date=SESSION,
            as_of=_utc(9),
            connect_routes=(ConnectRoute.SH_CONNECT,),
        )
    assert exc_repo.value.code == "CONNECT_CONTEXT_REPOSITORY_REQUIRED"

    class BadTypeFake:
        def load_verified_connect_market_context(
            self,
            *,
            route: ConnectRoute,
            session_date: dt.date,
            as_of: dt.datetime,
        ) -> object:
            del route, session_date, as_of
            return SimpleNamespace(context_id="0" * 64)

    class WrongRouteFake:
        def load_verified_connect_market_context(
            self,
            *,
            route: ConnectRoute,
            session_date: dt.date,
            as_of: dt.datetime,
        ) -> object:
            del route
            return _connect_ctx(
                route=ConnectRoute.SZ_CONNECT,
                session_date=session_date,
                as_of=as_of,
            )

    class WrongSessionFake:
        def load_verified_connect_market_context(
            self,
            *,
            route: ConnectRoute,
            session_date: dt.date,
            as_of: dt.datetime,
        ) -> object:
            return _connect_ctx(
                route=route,
                session_date=session_date + dt.timedelta(days=1),
                as_of=as_of,
            )

    class FutureAsOfFake:
        def load_verified_connect_market_context(
            self,
            *,
            route: ConnectRoute,
            session_date: dt.date,
            as_of: dt.datetime,
        ) -> object:
            return _connect_ctx(
                route=route,
                session_date=session_date,
                as_of=as_of + dt.timedelta(hours=1),
            )

    class ForgedIdFake:
        def load_verified_connect_market_context(
            self,
            *,
            route: ConnectRoute,
            session_date: dt.date,
            as_of: dt.datetime,
        ) -> object:
            ctx = _connect_ctx(route=route, session_date=session_date, as_of=as_of)
            object.__setattr__(ctx, "context_id", "f" * 64)
            return ctx

    for fake, _label in (
        (BadTypeFake(), "type"),
        (WrongRouteFake(), "route"),
        (WrongSessionFake(), "session"),
        (FutureAsOfFake(), "future"),
        (ForgedIdFake(), "forged"),
    ):
        repo = ValidatedCleanMarketDataRepository(
            read_market_facts=reader,
            connect_context_repository=fake,  # type: ignore[arg-type]
        )
        with pytest.raises(RepositoryContractError) as exc:
            repo.load_verified_market_snapshot(
                symbols=("00700.HK",),
                session_date=SESSION,
                as_of=_utc(9),
                connect_routes=(ConnectRoute.SH_CONNECT,),
            )
        assert exc.value.code == "CONNECT_CONTEXT_CONTRACT_INVALID"


def test_a_share_nonempty_routes_fail_without_calling_context_repository() -> None:
    state = _state("600000.SH")
    ctx_repo = MagicMock()

    def reader(
        *, symbols: tuple[str, ...], session_date: dt.date, as_of: dt.datetime
    ) -> CleanMarketFactsBundle:
        del symbols, session_date, as_of
        return CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=(state,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
            quality_passed=True,
        )

    repo = ValidatedCleanMarketDataRepository(
        read_market_facts=reader,
        connect_context_repository=ctx_repo,
    )
    with pytest.raises(RepositoryContractError) as exc:
        repo.load_verified_market_snapshot(
            symbols=("600000.SH",),
            session_date=SESSION,
            as_of=_utc(9),
            connect_routes=(ConnectRoute.SH_CONNECT,),
        )
    assert exc.value.code == "CONNECT_CONTEXT_UNEXPECTED"
    ctx_repo.load_verified_connect_market_context.assert_not_called()


def test_two_routes_order_independent_quota_changes_identity() -> None:
    hk_state = _state("00700.HK", market=Market.HK)
    sh_ctx = _connect_ctx(route=ConnectRoute.SH_CONNECT, as_of=_utc(7))
    sz_ctx = _connect_ctx(route=ConnectRoute.SZ_CONNECT, as_of=_utc(7))
    call_order: list[ConnectRoute] = []

    class OrderIndependentFake:
        def __init__(self) -> None:
            self.by_route = {
                ConnectRoute.SH_CONNECT: sh_ctx,
                ConnectRoute.SZ_CONNECT: sz_ctx,
            }

        def load_verified_connect_market_context(
            self,
            *,
            route: ConnectRoute,
            session_date: dt.date,
            as_of: dt.datetime,
        ) -> object:
            del session_date, as_of
            call_order.append(route)
            return self.by_route[route]

    def reader(
        *, symbols: tuple[str, ...], session_date: dt.date, as_of: dt.datetime
    ) -> CleanMarketFactsBundle:
        del symbols, session_date, as_of
        return CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=(hk_state,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
            quality_passed=True,
        )

    routes_fwd = (ConnectRoute.SH_CONNECT, ConnectRoute.SZ_CONNECT)
    repo = ValidatedCleanMarketDataRepository(
        read_market_facts=reader,
        connect_context_repository=OrderIndependentFake(),  # type: ignore[arg-type]
    )
    call_order.clear()
    snap_a = repo.load_verified_market_snapshot(
        symbols=("00700.HK",),
        session_date=SESSION,
        as_of=_utc(9),
        connect_routes=routes_fwd,
    )
    assert call_order == [ConnectRoute.SH_CONNECT, ConnectRoute.SZ_CONNECT]

    # Manually build with reversed context input order → same identity.
    snap_b = build_verified_market_snapshot(
        as_of=_utc(7),
        session_date=SESSION,
        states=(hk_state,),
        connect_contexts=(sz_ctx, sh_ctx),
        calendar_identity=_hex64("cal"),
        source_identity=_hex64("src"),
    )
    assert snap_a.snapshot_id == snap_b.snapshot_id

    alt_sz = _connect_ctx(
        route=ConnectRoute.SZ_CONNECT,
        as_of=_utc(7),
        quota_identity=_hex64("quota-alt"),
        buy_quota_available=False,
    )

    class AltQuotaFake:
        def load_verified_connect_market_context(
            self,
            *,
            route: ConnectRoute,
            session_date: dt.date,
            as_of: dt.datetime,
        ) -> object:
            del session_date, as_of
            if route is ConnectRoute.SH_CONNECT:
                return sh_ctx
            return alt_sz

    repo_alt = ValidatedCleanMarketDataRepository(
        read_market_facts=reader,
        connect_context_repository=AltQuotaFake(),  # type: ignore[arg-type]
    )
    snap_alt = repo_alt.load_verified_market_snapshot(
        symbols=("00700.HK",),
        session_date=SESSION,
        as_of=_utc(9),
        connect_routes=routes_fwd,
    )
    assert snap_alt.snapshot_id != snap_a.snapshot_id


def test_inmemory_connect_routes_exact_set_mismatch() -> None:
    sh_ctx = _connect_ctx(route=ConnectRoute.SH_CONNECT)
    sz_ctx = _connect_ctx(route=ConnectRoute.SZ_CONNECT)
    snap = _market_snapshot(
        symbols=("00700.HK",),
        connect_contexts=(sh_ctx, sz_ctx),
    )
    repo = InMemoryMarketDataRepository(
        {(SESSION, frozenset({"00700.HK"})): snap}
    )
    # exact match ok
    loaded = repo.load_verified_market_snapshot(
        symbols=("00700.HK",),
        session_date=SESSION,
        as_of=_utc(10),
        connect_routes=(ConnectRoute.SH_CONNECT, ConnectRoute.SZ_CONNECT),
    )
    assert loaded.snapshot_id == snap.snapshot_id

    # subset
    with pytest.raises(RepositoryContractError) as exc_sub:
        repo.load_verified_market_snapshot(
            symbols=("00700.HK",),
            session_date=SESSION,
            as_of=_utc(10),
            connect_routes=(ConnectRoute.SH_CONNECT,),
        )
    assert exc_sub.value.code == "SNAPSHOT_CONNECT_ROUTES_MISMATCH"

    # empty (proper subset)
    with pytest.raises(RepositoryContractError) as exc_empty:
        repo.load_verified_market_snapshot(
            symbols=("00700.HK",),
            session_date=SESSION,
            as_of=_utc(10),
            connect_routes=(),
        )
    assert exc_empty.value.code == "SNAPSHOT_CONNECT_ROUTES_MISMATCH"

    # single other route
    snap_sh_only = _market_snapshot(
        symbols=("00700.HK",),
        connect_contexts=(sh_ctx,),
    )
    repo_sh = InMemoryMarketDataRepository(
        {(SESSION, frozenset({"00700.HK"})): snap_sh_only}
    )
    with pytest.raises(RepositoryContractError) as exc_other:
        repo_sh.load_verified_market_snapshot(
            symbols=("00700.HK",),
            session_date=SESSION,
            as_of=_utc(10),
            connect_routes=(ConnectRoute.SZ_CONNECT,),
        )
    assert exc_other.value.code == "SNAPSHOT_CONNECT_ROUTES_MISMATCH"

    # superset of single-route snapshot
    with pytest.raises(RepositoryContractError) as exc_super:
        repo_sh.load_verified_market_snapshot(
            symbols=("00700.HK",),
            session_date=SESSION,
            as_of=_utc(10),
            connect_routes=(ConnectRoute.SH_CONNECT, ConnectRoute.SZ_CONNECT),
        )
    assert exc_super.value.code == "SNAPSHOT_CONNECT_ROUTES_MISMATCH"


def test_connect_context_reader_path_sanitized() -> None:
    hk_state = _state("00700.HK", market=Market.HK)
    leak = "/home/user/private/connect-secret.parquet"

    def reader(
        *, symbols: tuple[str, ...], session_date: dt.date, as_of: dt.datetime
    ) -> CleanMarketFactsBundle:
        del symbols, session_date, as_of
        return CleanMarketFactsBundle(
            known_as_of=_utc(7),
            states=(hk_state,),
            calendar_identity=_hex64("cal"),
            source_identity=_hex64("src"),
            quality_passed=True,
        )

    class LeakyFake:
        def load_verified_connect_market_context(
            self,
            *,
            route: ConnectRoute,
            session_date: dt.date,
            as_of: dt.datetime,
        ) -> object:
            del route, session_date, as_of
            raise OSError(leak)

    repo = ValidatedCleanMarketDataRepository(
        read_market_facts=reader,
        connect_context_repository=LeakyFake(),  # type: ignore[arg-type]
    )
    with pytest.raises(RepositoryContractError) as exc:
        repo.load_verified_market_snapshot(
            symbols=("00700.HK",),
            session_date=SESSION,
            as_of=_utc(9),
            connect_routes=(ConnectRoute.SH_CONNECT,),
        )
    _assert_sanitized_repo_error(
        exc.value,
        code="CONNECT_CONTEXT_READER_FAILURE",
        forbidden=(leak, "/home/user/private"),
    )


def test_market_data_repository_runtime_checkable_not_economic_closure() -> None:
    """isinstance only proves method name; wrong signature is not economic closure."""

    class WrongSignatureMarketFake:
        def load_verified_market_snapshot(
            self,
            *,
            tickers: tuple[str, ...],
            day: dt.date,
            when: dt.datetime,
        ) -> object:
            del tickers, day, when
            return _market_snapshot()

    fake = WrongSignatureMarketFake()
    assert isinstance(fake, MarketDataRepository)
    params = set(
        inspect.signature(MarketDataRepository.load_verified_market_snapshot).parameters
    )
    assert "connect_routes" in params
    # Must not treat Protocol membership as route/economic closure.
    assert "connect_routes" not in set(
        inspect.signature(fake.load_verified_market_snapshot).parameters
    )
