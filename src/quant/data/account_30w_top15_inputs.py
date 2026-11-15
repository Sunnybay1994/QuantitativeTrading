"""Two-ETF dated inputs and shared action publication for the A2 paper account."""

import datetime as dt
import hashlib
import json
from pathlib import Path

import polars as pl

from quant.data.mappers import TushareBarMapper
from quant.data.refresh import SHANGHAI
from quant.data.storage import RawStore
from quant.domain import Bar1dSchema, InstrumentSchema

SYMBOLS = ["512890.SH", "511010.SH"]
LISTINGS = {"512890.SH": dt.date(2019, 1, 18), "511010.SH": dt.date(2013, 3, 25)}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_capture(folder, *, date, now):
    receipt = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    if (
        receipt["status"] != "complete"
        or receipt["as_of"] != str(date)
        or receipt["auto_trade"] is not False
        or dt.datetime.fromisoformat(receipt["available_at"]) > now
    ):
        raise ValueError("ETF capture is incomplete, from another date or unavailable at run time")
    for name, digest in receipt["products"].items():
        if sha(folder / name) != digest:
            raise ValueError(f"ETF capture changed: {name}")
    for item in receipt["requests"].values():
        if sha(item["raw_path"]) != item["sha256"]:
            raise ValueError("ETF raw source changed")
    bars = pl.read_parquet(folder / "bars.parquet")
    references = pl.read_parquet(folder / "reference_prices.parquet")
    return bars, references, receipt


def capture(*, date, settings, data_root=Path("data"), now=None, connector=None):
    """One publisher per exact account/date; never duplicate an active capture."""
    clock = now or dt.datetime.now(SHANGHAI)
    if clock.tzinfo is None or date > clock.date():
        raise ValueError("Require an actual completed date and aware observation clock")
    if date == clock.date() and clock.hour < 21:
        raise ValueError("ETF execution data is consumed after the daily completion window")
    from quant.data.realtime import single_writer

    root = Path(settings["etf_daily_root"]) / f"date={date}"
    with single_writer(root / "writer.lock"):
        return _capture(date=date, settings=settings, data_root=data_root, now=clock, connector=connector)


def _capture(*, date, settings, data_root=Path("data"), now=None, connector=None):
    """Append raw and publish one immutable daily capture, reusing exact receipts."""
    now = now or dt.datetime.now(SHANGHAI)
    if now.tzinfo is None or date > now.date():
        raise ValueError("Require an actual completed date and aware observation clock")
    if date == now.date() and now.hour < 21:
        raise ValueError("ETF execution data is consumed after the daily completion window")
    root = Path(settings["etf_daily_root"]) / f"date={date}"
    for folder in sorted(root.glob("capture_*")):
        if (folder / "summary.json").exists():
            read_capture(folder, date=date, now=now)
            return folder
    from quant.data.connectors.tushare import TushareConnector

    client = connector or TushareConnector(config_path=Path("configs/tushare.local.toml"))
    folder = root / ("capture_" + now.strftime("%Y%m%dT%H%M%S%f"))
    folder.mkdir(parents=True, exist_ok=False)
    store = RawStore(Path(data_root) / "raw")
    requests, daily = {}, []
    for symbol in SYMBOLS:
        for table, params in [
            (
                "fund_daily",
                dict(
                    ts_code=symbol,
                    start_date=(date - dt.timedelta(days=10)).strftime("%Y%m%d"),
                    end_date=date.strftime("%Y%m%d"),
                ),
            ),
            ("fund_div", dict(ts_code=symbol)),
        ]:
            frame = client.query_raw(table, **params)
            observed = dt.datetime.now(SHANGHAI)
            snapshot = store.write(
                source="tushare", table=table, frame=frame, parameters=params, fetched_at=observed
            )
            requests[f"{symbol}/{table}/0"] = dict(
                raw_path=str(snapshot.data_path),
                sha256=snapshot.checksum_sha256,
                rows=frame.height,
                observed_at=observed.isoformat(),
                full_history_response=(table == "fund_div"),
            )
            if frame.height >= 5000:
                raise ValueError("Possibly truncated ETF response; do not publish it")
            if table == "fund_daily":
                if frame.is_empty() or set(frame["ts_code"]) != {symbol}:
                    raise ValueError(f"Missing or foreign ETF daily prices: {symbol}")
                daily.append(frame)
    raw = pl.concat(daily, how="diagonal_relaxed")
    if raw.select("ts_code", "trade_date").is_duplicated().any():
        raise ValueError("Duplicate ETF session prices")
    # Both listed ETFs must have this exact session; no stale close substitution.
    if set(raw.filter(pl.col("trade_date") == date.strftime("%Y%m%d"))["ts_code"]) != set(SYMBOLS):
        raise ValueError("Exact-session ETF quotes missing; inspect suspension/action evidence")
    bars = Bar1dSchema.validate(
        TushareBarMapper().map(
            raw.with_columns(
                pl.col("ts_code").alias("_request_symbol"), pl.lit("SH").alias("_market")
            )
        )
    )
    references = raw.select(
        pl.col("ts_code").alias("symbol"),
        pl.col("trade_date").str.to_date("%Y%m%d"),
        pl.col("pre_close").cast(pl.Float64),
    )
    bars.write_parquet(folder / "bars.parquet")
    references.write_parquet(folder / "reference_prices.parquet")
    terms = Path(settings["action_terms"]).read_bytes()
    (folder / "corporate_actions.toml").write_bytes(terms)
    (folder / "config.toml").write_text("auto_trade=false\n", encoding="utf-8")
    receipt = dict(
        status="complete",
        as_of=str(date),
        available_at=dt.datetime.now(SHANGHAI).isoformat(),
        auto_trade=False,
        requests=requests,
        events_sha256=hashlib.sha256(terms).hexdigest(),
        source_inventory_note="fund_div is a full-history response including explicit zero-row captures",
        products={
            name: sha(folder / name)
            for name in [
                "bars.parquet",
                "reference_prices.parquet",
                "corporate_actions.toml",
                "config.toml",
            ]
        },
    )
    (folder / "summary.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return folder


def shared_actions(*, folder, settings, now=None):
    from quant.data.realtime import single_writer

    lock = Path(settings["etf_actions_root"]) / ("account_30w_" + Path(folder).name + ".writer.lock")
    with single_writer(lock):
        return _shared_actions(folder=folder, settings=settings, now=now)


def _shared_actions(*, folder, settings, now=None):
    from quant.data.etf_corporate_actions import load, publish

    live_clock = now is None
    now = now or dt.datetime.now(SHANGHAI)
    receipt = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    version = Path(settings["etf_actions_root"]) / ("account_30w_" + folder.name)
    if not version.exists():
        known = set()
        for summary_path in Path(settings["etf_actions_root"]).glob("*/summary.json"):
            prior = json.loads(summary_path.read_text(encoding="utf-8"))
            if (
                prior.get("status") != "complete"
                or not set(SYMBOLS) <= set(prior.get("symbols", []))
                or dt.datetime.fromisoformat(prior["observed_at"]) > now
            ):
                continue
            old = load(summary_path.parent, symbols=SYMBOLS)
            known.update(
                (r["symbol"], r["ex_date"])
                for r in old.filter(pl.col("action_type") == "CASH_DIVIDEND").iter_rows(named=True)
            )
        incoming = set()
        for key, item in receipt["requests"].items():
            if "/fund_div/" not in key:
                continue
            raw = pl.read_parquet(item["raw_path"])
            if raw.height:
                incoming.update(
                    (r["ts_code"], dt.datetime.strptime(str(r["ex_date"]), "%Y%m%d").date())
                    for r in raw.filter(
                        (pl.col("div_proc") == "实施") & pl.col("ex_date").is_not_null()
                    ).iter_rows(named=True)
                )
        if known - incoming:
            raise ValueError(
                "Full-history ETF dividend response lost known implementations; retain prior master"
            )
        publish(
            capture=folder,
            sources=Path(settings["action_sources"]),
            output=version,
            include_announced_future=True,
        )
    # A live producer can observe its just-published version. A caller supplying
    # an explicit historical cutoff must still reject later observations.
    if live_clock:
        now = dt.datetime.now(SHANGHAI)
    events = load(version, symbols=SYMBOLS)
    if (
        events.height
        and events.filter(pl.col("observed_at").str.to_datetime(time_zone="UTC") > now).height
    ):
        raise ValueError("Corporate-action version was not yet available at this run time")
    if receipt["as_of"] > str(now.date()):
        raise ValueError("Future ETF capture")
    # Keep announced future ex-dates for record-date entitlement capture.
    return events.filter(pl.col("ann_date") <= now.date()), version


def instruments():
    return InstrumentSchema.validate(
        pl.from_dicts(
            [
                dict(
                    symbol=s,
                    market="SH",
                    name=s,
                    instrument_type="ETF",
                    currency="CNY",
                    list_date=LISTINGS[s],
                    delist_date=None,
                    board_lot=100,
                    status="LISTED",
                )
                for s in SYMBOLS
            ],
            schema_overrides={"delist_date": pl.Date},
        )
    )
