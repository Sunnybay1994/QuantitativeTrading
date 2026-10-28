"""Post-close whole-market 1m backfill via Futu realtime K_1M subscribe (not History KL).

Distinct from live ``quant data realtime`` (quote-first small watchlist) and from
``quant data minutes`` (TDX/AkShare). Uses subscribe → get_cur_kline → rotate.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import time
import tomllib
from pathlib import Path

import polars as pl

from quant.data.connectors.futu_realtime import FutuRealtime
from quant.data.intraday import merge_bars
from quant.data.intraday_sources import minute_bars_path
from quant.data.intraday_bars import SCHEMA, TZ, validate_bars
from quant.data.realtime import single_writer
from quant.data.realtime_inputs import phase
from quant.data.realtime_store import atomic_json, raw_packet

SOURCE = "futu_realtime"
# Per-market session end-minute labels (Futu get_cur_kline time_key minute-of-day).
# CN/HK use Asia/Shanghai wall clock; US keeps ET wall clock tagged Asia/Shanghai for SCHEMA.
MARKET_SPECS = {
    "cn": {
        "suffixes": (".SH", ".SZ"),
        "expected_bars": 240,
        "auction_minutes": {570},
        "session_end_minutes": set(range(571, 691)) | set(range(781, 901)),
        "ready_after": (15, 5),
        "calendar_symbol": "000001.SZ",
    },
    "hk": {
        "suffixes": (".HK",),
        "expected_bars": 330,
        "half_day_bars": 150,
        "auction_minutes": {570},
        # 09:31-12:00 and 13:01-16:00
        "session_end_minutes": set(range(571, 721)) | set(range(781, 961)),
        "ready_after": (16, 5),
        "calendar_symbol": "00700.HK",
    },
    "us": {
        "suffixes": (".US",),
        "expected_bars": 390,
        "auction_minutes": {570},
        # 09:31-16:00 ET wall clock
        "session_end_minutes": set(range(571, 961)),
        "ready_after": (5, 0),
        "calendar_symbol": None,
    },
}
DEFAULT_MARKETS = ("cn", "hk", "us")


UNKNOWN_STOCK_RE = re.compile(
    r"(?:未知股票|unknown\s*stock)\s*[:：]?\s*(?:(?P<mkt>SH|SZ|HK|US)\.)?(?P<code>[A-Za-z0-9]+)",
    re.IGNORECASE,
)


def is_unknown_stock_error(exc: BaseException) -> bool:
    msg = str(exc)
    if UNKNOWN_STOCK_RE.search(msg):
        return True
    lowered = msg.lower()
    return "未知股票" in msg or "unknown stock" in lowered


def unknown_codes_from_error(exc: BaseException) -> set[str]:
    return {m.group("code") for m in UNKNOWN_STOCK_RE.finditer(str(exc))}


def match_symbols_by_codes(symbols: list[str], codes: set[str]) -> list[str]:
    if not codes:
        return []
    hit = []
    for symbol in symbols:
        num = symbol.split(".", 1)[0]
        if num in codes:
            hit.append(symbol)
    return hit


def subscribe_k1m_resilient(client, symbols: list[str], *, reserve: int) -> tuple[list[str], list[dict]]:
    """Subscribe K_1M; isolate OpenD-unknown symbols instead of aborting the sweep."""
    if not symbols:
        return [], []
    try:
        client.subscribe_k1m(symbols, reserve=reserve)
        return list(symbols), []
    except Exception as exc:
        if not is_unknown_stock_error(exc):
            raise
        rejected: list[dict] = []
        remaining = list(symbols)
        codes = unknown_codes_from_error(exc)
        bad = match_symbols_by_codes(remaining, codes)
        if bad:
            for symbol in bad:
                rejected.append(dict(symbol=symbol, error=f"{type(exc).__name__}: {exc}", unsupported=True))
            remaining = [s for s in remaining if s not in set(bad)]
            accepted, more = subscribe_k1m_resilient(client, remaining, reserve=reserve)
            return accepted, rejected + more
        if len(remaining) == 1:
            symbol = remaining[0]
            rejected.append(dict(symbol=symbol, error=f"{type(exc).__name__}: {exc}", unsupported=True))
            return [], rejected
        mid = len(remaining) // 2
        left_acc, left_rej = subscribe_k1m_resilient(client, remaining[:mid], reserve=reserve)
        right_acc, right_rej = subscribe_k1m_resilient(client, remaining[mid:], reserve=reserve)
        if left_acc and right_acc:
            # Both halves ok alone; re-subscribe combined if needed (left already subscribed).
            # Unsubscribe left first? OpenD may still hold left. Prefer keep left, subscribe right already done.
            # right_acc already subscribed in recursive call; left_acc likewise.
            # But they are separate subscriptions — both should be active. Merge lists.
            return left_acc + right_acc, left_rej + right_rej
        return left_acc + right_acc, left_rej + right_rej



def market_of(symbol: str) -> str:
    if symbol.endswith(".HK"):
        return "hk"
    if symbol.endswith(".US"):
        return "us"
    if symbol.endswith((".SH", ".SZ")):
        return "cn"
    raise ValueError(f"Unsupported symbol market: {symbol}")


def parse_markets(value) -> list[str]:
    if value is None:
        return list(DEFAULT_MARKETS)
    if isinstance(value, str):
        items = [p.strip().lower() for p in value.split(",") if p.strip()]
    else:
        items = [str(p).strip().lower() for p in value]
    unknown = [m for m in items if m not in MARKET_SPECS]
    if unknown:
        raise ValueError(f"Unknown markets: {unknown}; choose from {sorted(MARKET_SPECS)}")
    # Preserve order, drop dupes.
    out: list[str] = []
    for m in items:
        if m not in out:
            out.append(m)
    return out or list(DEFAULT_MARKETS)


def normalize(rows: list[dict], symbol: str, end: dt.date) -> tuple[pl.DataFrame, int]:
    """Map get_cur_kline rows into clean SCHEMA bars (Futu minute END labels)."""
    spec = MARKET_SPECS[market_of(symbol)]
    session_minutes = spec["session_end_minutes"]
    auction = spec["auction_minutes"]
    values, rejected = [], 0
    for row in rows:
        try:
            code, market = symbol.split(".", 1)
            if row["code"] != f"{market}.{code}":
                raise ValueError("Wrong symbol")
            stamp = dt.datetime.fromisoformat(row["time_key"]).replace(tzinfo=TZ)
            minute = stamp.hour * 60 + stamp.minute
            if stamp.date() > end:
                continue
            # Opening-auction rows stay in raw only.
            if minute in auction:
                continue
            if stamp.second or minute not in session_minutes:
                raise ValueError("Unexpected minute label")
            value = dict(
                symbol=symbol,
                trade_date=stamp.date(),
                bar_start=stamp - dt.timedelta(minutes=1),
                bar_end=stamp,
                source=SOURCE,
                amount=row["turnover"],
                **{k: row[k] for k in ("open", "high", "low", "close", "volume")},
            )
            prices = [value[k] for k in ("open", "high", "low", "close")]
            if (
                any(not math.isfinite(p) or p <= 0 for p in prices)
                or value["high"] < max(prices)
                or value["low"] > min(prices)
                or not math.isfinite(value["volume"])
                or value["volume"] < 0
            ):
                raise ValueError("Invalid OHLCV")
            if value["amount"] is not None and (
                not float("-inf") < value["amount"] < float("inf") or value["amount"] < 0
            ):
                raise ValueError("Invalid amount")
            values.append(value)
        except (KeyError, ValueError, TypeError):
            rejected += 1
    frame = pl.DataFrame(values, schema=SCHEMA)
    if frame.height:
        spec = MARKET_SPECS[market_of(symbol)]
        count = pl.len().over("trade_date")
        complete = count == spec["expected_bars"]
        half = spec.get("half_day_bars")
        if half:
            complete = complete | (count == half)
        frame = frame.with_columns(complete.alias("session_complete"))
    return validate_bars(frame), rejected



def latest_connect_snapshot(root: Path) -> Path | None:
    base = root / "clean/connect_snapshot"
    if not base.exists():
        return None
    best: tuple[dt.date, Path] | None = None
    for route_dir in base.glob("route=*"):
        for day_dir in route_dir.glob("date=*"):
            parquet = day_dir / "data.parquet"
            if not parquet.exists():
                continue
            day = dt.date.fromisoformat(day_dir.name.split("=", 1)[1])
            if best is None or day > best[0]:
                best = (day, parquet)
    # Prefer union of same-date SH+SZ routes when both exist.
    if best is None:
        return None
    return best[1]


def consumer_paused(data: dict, today: dt.date) -> bool:
    """A pool with no consumer pauses 60 days after its as-of date."""
    if str(data.get("consumer") or "").strip():
        return False
    raw = data.get("as_of") or data.get("frozen_as_of") or data.get("registered_on")
    if isinstance(raw, dt.datetime):
        opened = raw.date()
    elif isinstance(raw, dt.date):
        opened = raw
    elif isinstance(raw, str) and len(raw) >= 10:
        opened = dt.date.fromisoformat(raw[:10])
    else:
        return False
    return (today - opened).days >= 60


def paused_pool_names(root: Path, today: dt.date | None = None) -> list[str]:
    config = root / "configs/data/post_close_k1m.toml"
    if not config.is_file():
        return []
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    clock = today or dt.datetime.now(TZ).date()
    paused = []
    for key in ("us_universe_path", "hk_connect_watch", "ah_dual_list"):
        relative = settings.get(key)
        if not relative:
            continue
        path = root / str(relative)
        if not path.is_file():
            continue
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        if consumer_paused(data, clock):
            paused.append(path.name)
    return paused


def load_hk_connect_symbols(settings: dict) -> list[str]:
    """Frozen observation pool intersected with current Connect eligibility."""
    watch = Path(settings.get("hk_connect_watch", "configs/universe/hk_connect_watch_v1.toml"))
    data = tomllib.loads(watch.read_text(encoding="utf-8"))
    if consumer_paused(data, dt.datetime.now(TZ).date()):
        return []
    watched = {m['symbol'] for m in data.get('members', [])
               if str(m.get('symbol', '')).endswith('.HK')}
    if len(watched) > int(data.get('maximum_members', 60)):
        raise ValueError('HK observation pool exceeds its declared member limit')
    root = Path(settings["data_root"])
    explicit = settings.get("hk_connect_snapshot")
    paths: list[Path] = []
    if explicit:
        paths = [Path(explicit)]
    else:
        base = root / "clean/connect_snapshot"
        latest = None
        for route_dir in sorted(base.glob("route=*")) if base.exists() else []:
            for day_dir in route_dir.glob("date=*"):
                parquet = day_dir / "data.parquet"
                if parquet.exists():
                    day = dt.date.fromisoformat(day_dir.name.split("=", 1)[1])
                    if latest is None or day > latest:
                        latest = day
        if latest is None:
            return sorted(watched)
        for route_dir in base.glob("route=*"):
            parquet = route_dir / f"date={latest}" / "data.parquet"
            if parquet.exists():
                paths.append(parquet)
    symbols: set[str] = set()
    for path in paths:
        frame = pl.read_parquet(path)
        if "buy_eligible" in frame.columns:
            frame = frame.filter(pl.col("buy_eligible"))
        symbols.update(frame["symbol"].to_list())
    return sorted(symbols & watched)


def load_ah_priority_h_symbols(settings: dict) -> list[str]:
    path = Path(settings.get("ah_dual_list", "configs/universe/ah_dual_list_v1.toml"))
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if consumer_paused(data, dt.datetime.now(TZ).date()):
        return []
    out: list[str] = []
    for pair in data.get("pairs", []):
        h = pair.get("h_symbol")
        if h and h.endswith(".HK") and h not in out:
            out.append(h)
    return out


def load_us_symbols(settings: dict) -> list[str]:
    path = Path(settings.get("us_universe_path", "configs/universe/us_post_close_watch_v1.toml"))
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if consumer_paused(data, dt.datetime.now(TZ).date()):
        return []
    return sorted({m["symbol"] for m in data.get("members", []) if str(m.get("symbol", "")).endswith(".US")})


def load_cn_symbols(settings: dict) -> list[str]:
    """Prefer MinutesRecent snapshot; fall back to refreshing via PublicMarket."""
    path = Path(settings.get("universe_path", "artifacts/minute_refresh/universe.json"))
    members: list[dict] = []
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        captured = dt.datetime.fromisoformat(saved["captured_at"])
        if (dt.datetime.now(TZ) - captured).days <= 7:
            members = saved["members"]
    if not members:
        from quant.data.connectors.public_market import PublicMarket
        from quant.data.recent_minutes import universe as recent_universe

        root = Path(settings["data_root"])
        output = Path(settings.get("universe_output", "artifacts/minute_refresh"))
        output.mkdir(parents=True, exist_ok=True)
        client = PublicMarket(timeout=25)
        try:
            members = recent_universe(client, output, root)
        finally:
            client.close()
    suffixes = MARKET_SPECS["cn"]["suffixes"]
    return sorted({m["symbol"] for m in members if m["symbol"].endswith(suffixes)})


def load_universe(settings: dict, markets: list[str] | None = None) -> list[str]:
    """Build ordered universe: AH H-shares first within HK, then remaining Connect, then US, then CN."""
    selected = parse_markets(markets if markets is not None else settings.get("markets"))
    symbols: list[str] = []
    seen: set[str] = set()

    def add_many(items: list[str]):
        for symbol in items:
            if symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)

    if "hk" in selected:
        connect = load_hk_connect_symbols(settings)
        connect_set = set(connect)
        ah = [s for s in load_ah_priority_h_symbols(settings) if s in connect_set]
        # AH dual H legs not in connect still pulled when listed (rare).
        ah_extra = [s for s in load_ah_priority_h_symbols(settings) if s not in connect_set]
        add_many(ah)
        add_many([s for s in connect if s not in set(ah)])
        add_many(ah_extra)
        # Hang Seng index via Futu special code when HK market requested.
        if settings.get("include_hsi", True):
            add_many(["800000.HK"])
    if "us" in selected:
        add_many(load_us_symbols(settings))
    if "cn" in selected:
        add_many(load_cn_symbols(settings))
    return symbols


def expected_bars_for(symbol: str, session: dt.date, root: Path) -> int:
    market = market_of(symbol)
    spec = MARKET_SPECS[market]
    if market == "hk":
        cal = root / "clean/trade_calendar/market=HK/data.parquet"
        if cal.exists():
            frame = pl.read_parquet(cal).filter(pl.col("date") == session)
            if frame.height and bool(frame["is_half_day"][0]):
                return int(spec.get("half_day_bars", 150))
    return int(spec["expected_bars"])


def latest_market_session(
    market: str,
    *,
    data_root: Path,
    through: dt.date,
    now: dt.datetime | None = None,
) -> dt.date:
    if market == "cn":
        from quant.data.refresh import latest_session

        return latest_session(data_root=data_root, through=through, refresh_calendar=False)
    if market == "hk":
        from quant.data.calendar import expected_open_dates

        dates = expected_open_dates(data_root, ["00700.HK"], through - dt.timedelta(days=40), through)
        if not dates:
            raise ValueError("No HK open session in calendar window")
        return max(dates)
    # US: derive last regular close from America/New_York wall clock (no local calendar yet).
    from zoneinfo import ZoneInfo

    et_now = (now or dt.datetime.now(TZ)).astimezone(ZoneInfo("America/New_York"))
    day = et_now.date() if et_now.time() >= dt.time(16, 5) else et_now.date() - dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return min(day, through)


def market_ready(market: str, now: dt.datetime, *, force: bool = False) -> tuple[bool, str]:
    if force:
        return True, "force"
    local = now.astimezone(TZ)
    hour, minute = MARKET_SPECS[market]["ready_after"]
    threshold = dt.time(hour, minute)
    if market == "cn":
        current = phase(local)
        if current in ("closed", "settling"):
            return True, current
        return False, f"cn_phase={current}"
    if local.time() >= threshold:
        return True, f"after_{hour:02d}:{minute:02d}"
    return False, f"before_{hour:02d}:{minute:02d}"



def today_bar_count(root: Path, symbol: str, session: dt.date) -> int:
    path = minute_bars_path(root, symbol)
    if not path.exists():
        return 0
    frame = pl.read_parquet(path).filter(pl.col("trade_date") == session)
    return int(frame["bar_start"].n_unique()) if frame.height else 0


def run(
    config: Path,
    *,
    limit: int | None = None,
    max_seconds: float | None = None,
    max_batches: int | None = None,
    force: bool = False,
    skip_complete: bool = True,
    markets: list[str] | None = None,
) -> dict:
    if (limit is not None and limit < 1) or (max_seconds is not None and max_seconds <= 0):
        raise ValueError("Positive limit and time budget required")
    if max_batches is not None and max_batches < 1:
        raise ValueError("Positive max_batches required")
    settings = tomllib.loads(config.read_text(encoding="utf-8"))
    if settings.get("auto_trade") is not False:
        raise ValueError("auto_trade=false required")
    root = Path(settings["data_root"])
    output = Path(settings["output"])
    output.mkdir(parents=True, exist_ok=True)
    rotate_seconds = int(settings.get("k1m_rotate_seconds", 65))
    if rotate_seconds < 60:
        raise ValueError("k1m_rotate_seconds must be >=60 (OpenD unsubscribe hold)")
    reserve = int(settings.get("quota_reserve", 5))
    request_spacing = float(settings.get("request_spacing_seconds", 0.05))

    with single_writer(output / "writer.lock"):
        now = dt.datetime.now(TZ)
        current_phase = phase(now)
        selected = parse_markets(markets if markets is not None else settings.get("markets"))
        readiness = {m: market_ready(m, now, force=force) for m in selected}
        ready_markets = [m for m, (ok, _) in readiness.items() if ok]
        if not ready_markets:
            state = dict(
                status="idle",
                reason="No selected market is in its post-close window",
                phase=current_phase,
                markets=selected,
                market_readiness={m: {"ready": ok, "detail": detail} for m, (ok, detail) in readiness.items()},
                auto_trade=False,
                as_of=str(now.date()),
            )
            atomic_json(output / "status.json", state)
            write_coverage(output)
            return state

        # Session "through" per market: after that market's close use today, else yesterday.
        sessions: dict[str, dt.date] = {}
        for market in ready_markets:
            hour, minute = MARKET_SPECS[market]["ready_after"]
            through = now.date() if force or now.time() >= dt.time(hour, minute) else now.date() - dt.timedelta(days=1)
            sessions[market] = latest_market_session(market, data_root=root, through=through, now=now)

        began = time.monotonic()
        state: dict = dict(
            status="running",
            mechanism="post_close_k1m",
            as_of={m: str(d) for m, d in sessions.items()},
            started_at=now.isoformat(),
            auto_trade=False,
            phase=current_phase,
            markets=ready_markets,
            markets_requested=selected,
            market_readiness={m: {"ready": ok, "detail": detail} for m, (ok, detail) in readiness.items()},
            source=SOURCE,
            completed=0,
            ok=0,
            failed=0,
            skipped_complete=0,
            skipped_not_ready=0,
            changed_rows=0,
            bar_rows=0,
            batches=0,
            total=0,
            results=[],
            errors=[],
        )

        def publish(**changes):
            state.update(changes)
            state["heartbeat"] = dt.datetime.now(TZ).isoformat()
            state["elapsed_seconds"] = round(time.monotonic() - began, 1)
            atomic_json(output / "status.json", state)

        publish()
        client: FutuRealtime | None = None
        active: list[str] = []
        try:
            symbols = load_universe(settings, markets=ready_markets)
            if limit:
                symbols = symbols[:limit]
            state["universe_total"] = len(symbols)
            state["total"] = len(symbols)
            state["universe_by_market"] = {
                m: sum(1 for s in symbols if market_of(s) == m) for m in ready_markets
            }
            publish()

            client = FutuRealtime(settings.get("host", "127.0.0.1"), int(settings.get("port", 11111)))
            state["provider_state"] = client.state()
            quota = client.quota()
            state["quota_start"] = dict(quota)
            remain = int(quota["remain"])
            batch_size = max(1, remain - reserve)
            if batch_size < 1:
                raise RuntimeError(f"No K_1M quota: remain={remain}, reserve={reserve}")
            state["batch_size"] = batch_size
            state["quota_reserve"] = reserve
            publish()

            cursor = 0
            symbol_session = {symbol: sessions[market_of(symbol)] for symbol in symbols}
            symbol_expected = {
                symbol: expected_bars_for(symbol, symbol_session[symbol], root) for symbol in symbols
            }
            while cursor < len(symbols):
                if max_seconds and time.monotonic() - began >= max_seconds:
                    state["status"] = "time_budget_reached"
                    break
                if max_batches is not None and state["batches"] >= max_batches:
                    state["status"] = "batch_budget_reached"
                    break

                # Skip already-complete symbols without consuming quota.
                batch: list[str] = []
                while cursor < len(symbols) and len(batch) < batch_size:
                    symbol = symbols[cursor]
                    cursor += 1
                    session = symbol_session[symbol]
                    expected = symbol_expected[symbol]
                    checkpoints = output / f"date={session}"
                    checkpoints.mkdir(exist_ok=True)
                    checkpoint = checkpoints / f"{symbol}.json"
                    if skip_complete and checkpoint.exists():
                        prior = json.loads(checkpoint.read_text(encoding="utf-8"))
                        if prior.get("as_of") == str(session) and (
                            prior.get("session_bars", 0) >= expected or prior.get("unsupported")
                        ):
                            state["skipped_complete"] += 1
                            state["completed"] += 1
                            continue
                    if skip_complete and today_bar_count(root, symbol, session) >= expected:
                        atomic_json(
                            checkpoint,
                            dict(
                                symbol=symbol,
                                as_of=str(session),
                                session_bars=expected,
                                expected_bars=expected,
                                skipped=True,
                            ),
                        )
                        state["skipped_complete"] += 1
                        state["completed"] += 1
                        continue
                    batch.append(symbol)

                if not batch:
                    continue

                subscribe_at = time.monotonic()
                accepted, rejected = subscribe_k1m_resilient(client, batch, reserve=reserve)
                state["batches"] += 1
                for item in rejected:
                    symbol = item["symbol"]
                    session = symbol_session[symbol]
                    result = dict(
                        symbol=symbol,
                        as_of=str(session),
                        market=market_of(symbol),
                        ok=False,
                        unsupported=True,
                        error=item.get("error"),
                    )
                    (output / f"date={session}").mkdir(exist_ok=True)
                    atomic_json(output / f"date={session}" / f"{symbol}.json", result)
                    state["failed"] += 1
                    state["completed"] += 1
                    state["errors"].append(dict(symbol=symbol, error=result["error"], unsupported=True))
                    state["results"].append(result)
                if not accepted:
                    publish()
                    continue
                state["quota"] = client.quota()
                active = list(accepted)
                state["k1m_active"] = list(active)
                publish()

                for symbol in accepted:
                    session = symbol_session[symbol]
                    expected = symbol_expected[symbol]
                    result = dict(
                        symbol=symbol,
                        as_of=str(session),
                        market=market_of(symbol),
                        expected_bars=expected,
                        ok=False,
                    )
                    try:
                        rows = client.bars(symbol)
                        if not rows:
                            raise ValueError("Empty current K-line response")
                        received = dt.datetime.now(TZ)
                        raw = raw_packet(root, "post_close_k1m", rows, received, source="futu")
                        frame, rejected_rows = normalize(rows, symbol, session)
                        session_frame = frame.filter(pl.col("trade_date") == session)
                        directory = minute_bars_path(root, symbol).parent
                        changed = 0 if frame.is_empty() else merge_bars(directory, frame)
                        session_bars = int(session_frame["bar_start"].n_unique()) if session_frame.height else 0
                        result.update(
                            ok=True,
                            returned_rows=len(rows),
                            valid_rows=frame.height,
                            rejected_rows=rejected_rows,
                            session_bars=session_bars,
                            changed_rows=changed,
                            raw=raw,
                        )
                        state["ok"] += 1
                        state["changed_rows"] += changed
                        state["bar_rows"] += session_bars
                    except Exception as exc:
                        result["error"] = f"{type(exc).__name__}: {exc}"
                        state["failed"] += 1
                        state["errors"].append(dict(symbol=symbol, error=result["error"]))
                    (output / f"date={session}").mkdir(exist_ok=True)
                    atomic_json(output / f"date={session}" / f"{symbol}.json", result)
                    state["completed"] += 1
                    state["results"].append(
                        {k: result[k] for k in result if k != "raw"}
                    )
                    if request_spacing > 0:
                        time.sleep(request_spacing)
                    if state["completed"] % 20 == 0:
                        print(
                            f"post_close_k1m {state['completed']}/{state['total']} "
                            f"ok={state['ok']} fail={state['failed']} "
                            f"changed={state['changed_rows']}",
                            flush=True,
                        )
                        publish()

                # Hold subscription until OpenD release window, then free slots.
                wait = rotate_seconds - (time.monotonic() - subscribe_at)
                if wait > 0:
                    time.sleep(wait)
                state["quota"] = client.unsubscribe_k1m(active)
                active = []
                state["k1m_active"] = []
                publish()

            if state["status"] == "running":
                state["status"] = "complete" if state["completed"] >= state["total"] else "partial"
        except Exception as exc:
            state.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if client is not None:
                try:
                    if active:
                        client.unsubscribe_k1m(active)
                except Exception:
                    pass
                client.close()
            publish()
            write_coverage(output)
        return state


THRESHOLDS = {"cn": 0.95, "hk": 0.90, "us": 0.90}


def write_coverage(output: Path) -> dict:
    """Summarise post-close receipts. Complete means session_bars reached the expected count."""
    days: dict[str, dict[str, dict[str, int]]] = {}
    for folder in sorted(output.glob("date=*")):
        if not folder.is_dir():
            continue
        day = folder.name.split("=", 1)[1]
        for path in folder.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            market = str(payload.get("market") or "")
            if market not in THRESHOLDS:
                continue
            bucket = days.setdefault(day, {}).setdefault(
                market, {"expected": 0, "complete": 0, "partial": 0, "missing": 0})
            bars = int(payload.get("session_bars") or 0)
            target = int(payload.get("expected_bars") or MARKET_SPECS[market]["expected_bars"])
            bucket["expected"] += 1
            if payload.get("ok") and bars >= target:
                bucket["complete"] += 1
            elif bars > 0:
                bucket["partial"] += 1
            else:
                bucket["missing"] += 1
    lines = ["# post-close K_1M coverage", "",
             "| date | market | expected | complete | partial | missing | complete_rate |",
             "|---|---|---:|---:|---:|---:|---:|"]
    flat = []
    for day in sorted(days):
        for market in ("cn", "hk", "us"):
            bucket = days[day].get(market)
            if not bucket:
                continue
            rate = bucket["complete"] / bucket["expected"] if bucket["expected"] else 0.0
            lines.append(
                f"| {day} | {market} | {bucket['expected']} | {bucket['complete']} | "
                f"{bucket['partial']} | {bucket['missing']} | {rate:.1%} |")
            flat.append({"date": day, "market": market, **bucket, "complete_rate": rate})
    if not flat:
        lines.append("| | | 0 | 0 | 0 | 0 | |")
    lines.append("")
    lines.append("Complete bars: cn 240, hk 330 (half day 150), us 390.")
    text = "\n".join(lines) + "\n"
    output.mkdir(parents=True, exist_ok=True)
    (output / "coverage.md").write_text(text, encoding="utf-8")
    summary = {"rows": flat, "thresholds": THRESHOLDS}
    (output / "coverage.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/data/post_close_k1m.toml"))
    parser.add_argument("--limit", type=int, help="Cap universe size (probe / sample)")
    parser.add_argument("--max-seconds", type=float, help="Wall-clock budget")
    parser.add_argument("--max-batches", type=int, help="Stop after N subscribe rotations")
    parser.add_argument(
        "--markets",
        default=None,
        help="Comma list: cn,hk,us (default from config / all three)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even when a market is outside its post-close window",
    )
    parser.add_argument(
        "--no-skip-complete",
        action="store_true",
        help="Re-fetch symbols that already have a full session of bars",
    )
    args = parser.parse_args()
    result = run(
        args.config,
        limit=args.limit,
        max_seconds=args.max_seconds,
        max_batches=args.max_batches,
        force=args.force,
        skip_complete=not args.no_skip_complete,
        markets=parse_markets(args.markets) if args.markets else None,
    )
    printable = {k: v for k, v in result.items() if k not in ("results", "errors")}
    printable["error_count"] = len(result.get("errors") or [])
    printable["result_sample"] = (result.get("results") or [])[:5]
    print(json.dumps(printable, ensure_ascii=False, indent=2, default=str))
    if result.get("status") == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
