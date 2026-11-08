"""A2 frozen-input fallback: existing captures only, without provider collection."""

import copy
import datetime as dt
import json
import shutil
import tomllib
from dataclasses import fields
from pathlib import Path

import polars as pl

from quant.data.account_30w_top15_inputs import SYMBOLS, instruments, read_capture
from quant.data.etf_corporate_actions import load as load_actions
from quant.data.stock_paper_inputs import (
    StockPaperInputs,
    read_stock_data,
    read_stock_paper_calendar,
)
from quant.execution import account_30w_top15_paper as paper
from quant.execution.paper_order_fallback import digest, guard, sources


def offline_stocks(root, config, symbols, day, calendar):
    """Same stock reader contract, with no call to the auto-capture function."""
    folder = root / f"clean/stock_paper_inputs/date={day}"
    frames = {
        name: pl.read_parquet(folder / f"{name}.parquet").filter(pl.col("symbol").is_in(symbols))
        for name in ("instruments", "names", "limits", "suspensions", "dividends")
    }
    data = {
        table: read_stock_data(
            data_root=root,
            config=Path(config["data"]["refresh_config"]),
            table=table,
            start=config["data"]["warmup_start"],
            end=day,
            symbols=symbols,
        )
        for table in ("bar_1d", "daily_basic")
    }
    minimum = config["universe"]["minimum_daily_symbols"]
    if any(frame.filter(pl.col("trade_date") == day).height < minimum for frame in data.values()):
        raise ValueError("Missing frozen same-session stock bars/basic; collection prohibited")
    if frames["instruments"].height != len(symbols):
        raise ValueError("Frozen stock instrument coverage missing")
    return StockPaperInputs(data["bar_1d"], data["daily_basic"], calendar, **frames)


def cached_etfs(config, day, now):
    root = Path(config["data"]["etf_daily_root"]) / f"date={day}"
    folder = next(
        (p for p in sorted(root.glob("capture_*")) if (p / "summary.json").is_file()), None
    )
    if folder is None:
        raise ValueError("No frozen same-session ETF capture; collection prohibited")
    bars, refs, receipt = read_capture(folder, date=day, now=now)
    version = Path(config["data"]["etf_actions_root"]) / ("account_30w_" + folder.name)
    actions = load_actions(version, symbols=SYMBOLS)
    for value in actions["observed_at"]:
        stamp = dt.datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp > now:
            raise ValueError("ETF actions were not yet observable")
    paths = [folder / name for name in ["summary.json", *receipt["products"]]]
    paths += [Path(x["raw_path"]) for x in receipt["requests"].values()]
    paths += [
        version / name for name in ["summary.json", "actions.parquet", "sources.json", "terms.toml"]
    ]
    terms = tomllib.loads((folder / "corporate_actions.toml").read_text(encoding="utf-8"))["splits"]
    return dict(
        bars=bars,
        references=refs,
        actions=actions.filter(pl.col("ann_date") <= day),
        instruments=instruments(),
        splits=terms,
        capture=str(folder),
        actions_version=str(version),
    ), paths


def run(
    spec,
    *,
    end,
    data_root,
    output,
    deadline,
    account_writer=False,
    as_month_end=False,
    forecast=None,
):
    config_path = Path(spec["config"])
    account = Path(spec["output"])
    data_root = Path(data_root)
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if end < config["paper"]["inception_date"]:
        return paper.run(config_path=config_path, output=account, end=end, data_root=data_root)
    if account_writer:
        raise ValueError("Account writer active; frozen A2 cannot race it")
    guard(deadline)
    calendar = read_stock_paper_calendar(data_root)
    sessions = sorted(calendar.filter(pl.col("is_open"))["date"].unique().to_list())
    following = next(d for d in sessions if d > end)
    snapshots = sorted(account.glob("????-??-??/state.json"))
    prior = snapshots[-1] if snapshots else None
    state = (
        json.loads(prior.read_text(encoding="utf-8"))
        if prior
        else dict(holdings={}, receivables=[], limit_book={})
    )
    last = (
        dt.date.fromisoformat(state["date"])
        if prior
        else max(d for d in sessions if d < config["paper"]["inception_date"])
    )
    dates = [d for d in sessions if last < d <= end]
    if end not in sessions or end < last or len(dates) > 1:
        raise ValueError(
            "Frozen A2 needs the current open session; multiple missed sessions require catch-up"
        )
    candidates = ([Path(forecast)] if forecast else []) + sorted(
        Path(config["model"]["forecast_root"]).glob("**/model/forecast")
    )
    forecast = next(
        (
            p
            for p in candidates
            if (p / "summary.json").is_file()
            and json.loads((p / "summary.json").read_text(encoding="utf-8")).get("as_of")
            == str(end)
        ),
        None,
    )
    if forecast is None:
        raise ValueError("Missing same-date frozen A2 forecast")
    now = dt.datetime.now(paper.SHANGHAI)
    stamp = dt.datetime.fromisoformat(
        json.loads((forecast / "summary.json").read_text(encoding="utf-8"))["recorded_at"]
    )
    if stamp.tzinfo is None or stamp > now:
        raise ValueError("Frozen A2 forecast not yet observable")
    original = copy.deepcopy(config)
    original["research"]["assessment"] = config["research"]["preregistration"]
    anchor = prior or account / str(end) / "state.json"
    before = sources(data_root, config_path, anchor, forecast, end, original, deadline)
    prior_sha = digest(prior, deadline) if prior else None
    controls_path = account / "controls.json"
    controls = (
        json.loads(controls_path.read_text())
        if controls_path.exists()
        else {name: config["paper"][name] for name in ("halt", "sell_only")}
    )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    copied = output / "model/forecast"
    copied.mkdir(parents=True)
    for name in ("summary.json", "predictions.parquet"):
        shutil.copy2(forecast / name, copied / name)
    shutil.copy2(forecast.parent / "summary.json", copied.parent / "summary.json")
    shutil.copy2(config_path, output / "config.toml")
    scores = paper.forecast_for(config, end, following, copied)
    symbols = (
        set(scores["symbol"])
        | set(state["holdings"])
        | {r["symbol"] for r in state["receivables"]}
        | {r["symbol"] for r in state.get("limit_book", {}).get("orders", [])}
    ) - set(SYMBOLS)
    stocks, etfs = {}, {}
    extra_paths = []
    for day in dates:
        guard(deadline)
        etfs[day], paths = cached_etfs(config, day, now)
        extra_paths += paths
        stocks[day] = offline_stocks(data_root, config, sorted(symbols), day, calendar)
        folder = output / str(day)
        folder.mkdir()
        for field in fields(StockPaperInputs):
            guard(deadline)
            getattr(stocks[day], field.name).write_parquet(folder / f"stock_{field.name}.parquet")
        for name, value in etfs[day].items():
            if isinstance(value, pl.DataFrame):
                value.write_parquet(folder / f"etf_{name}.parquet")
    if before != sources(data_root, config_path, anchor, forecast, end, original, deadline):
        raise ValueError("A2 sources changed while freezing")
    originals = {**before, **{str(p): digest(p, deadline) for p in extra_paths}}
    (output / "sources.json").write_text(json.dumps(originals, indent=2), encoding="utf-8")
    calendar.write_parquet(output / "calendar.parquet")
    frozen = {p: digest(p, deadline) for p in output.rglob("*") if p.is_file()}

    def preflight():
        guard(deadline)
        current = sorted(account.glob("????-??-??/state.json"))
        if (
            (current[-1] if current else None) != prior
            or prior
            and digest(prior, deadline) != prior_sha
        ):
            raise ValueError("A2 account advanced during freeze")

    def before_publish():
        guard(deadline)
        if json.loads(controls_path.read_text()) != controls:
            raise ValueError("A2 controls changed after freeze")
        if any(digest(p, deadline) != value for p, value in frozen.items()):
            raise ValueError("Frozen A2 inputs changed")

    return paper.run(
        config_path=output / "config.toml",
        output=account,
        data_root=data_root,
        end=end,
        forecast=copied,
        as_month_end=as_month_end,
        calendar=pl.read_parquet(output / "calendar.parquet"),
        stock_reader=lambda _root, _config, _symbols, day: stocks[day],
        etf_reader=lambda _c, day, _n: etfs[day],
        preflight=preflight,
        before_publish=before_publish,
    )
