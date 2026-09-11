"""P7 corpus I/O, resumable API-cost cache, and PIT factor publication."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3

import polars as pl

from quant.factors.forecast_text_score import DIMENSIONS


def read_corpus(path: Path) -> pl.DataFrame:
    frame = pl.read_parquet(path)
    if "symbol" not in frame.columns and "ts_code" in frame.columns:
        frame = frame.rename({"ts_code": "symbol"})
    required = {"symbol", "publication_date", "report_period", "reason_text"}
    if not required.issubset(frame.columns):
        raise ValueError("Corpus requires symbol, publication_date, report_period, reason_text")
    if "same_day_conflict" not in frame.columns:
        frame = frame.with_columns(pl.lit(False).alias("same_day_conflict"))
    frame = frame.with_columns(
        pl.col("publication_date").cast(pl.Date, strict=True),
        pl.col("report_period").cast(pl.Date, strict=True),
        pl.col("reason_text").cast(pl.String).str.strip_chars().replace("", None),
    )
    if frame.filter(
        pl.col("symbol").is_null() | ~pl.col("symbol").str.contains(r"^[0-9]{6}\.(SH|SZ)$")
        | pl.col("publication_date").is_null() | pl.col("report_period").is_null()
        | pl.col("same_day_conflict").is_null()
    ).height or frame.schema["same_day_conflict"] != pl.Boolean:
        raise ValueError("Invalid corpus symbol, date or conflict flag")
    # Detect conflicts before selecting fields: even differing numeric forecasts conflict.
    frame = frame.unique(maintain_order=True)
    keys = ["symbol", "publication_date", "report_period"]
    frame = frame.with_columns(
        (pl.col("same_day_conflict") | (pl.len().over(keys) > 1)).alias("same_day_conflict")
    )
    frame = frame.select(*keys, "reason_text", "same_day_conflict").unique().sort(keys)
    hashes = [hashlib.sha256(json.dumps(row, sort_keys=True, default=str,
                                        ensure_ascii=False).encode()).hexdigest()
              for row in frame.iter_rows(named=True)]
    return frame.with_columns(pl.Series("input_id", hashes))


class ScoreCache:
    """SQLite commits before network I/O so interruption cannot silently re-charge.

    This is a request/results cache, shared by sequential resumed/incremental runs.
    A request with no committed response stays unknown and is never auto-resubmitted.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY, cache_key TEXT NOT NULL, state TEXT NOT NULL,
            reserved_usd REAL NOT NULL, charged_usd REAL NOT NULL,
            actual_model TEXT, usage_json TEXT, scores_json TEXT, error TEXT,
            created_at TEXT NOT NULL)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS by_key ON attempts(cache_key)")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def latest(self, key: str) -> dict | None:
        row = self.db.execute("SELECT * FROM attempts WHERE cache_key=? ORDER BY id DESC LIMIT 1",
                              (key,)).fetchone()
        return dict(row) if row else None

    def totals(self) -> dict:
        row = self.db.execute("SELECT COUNT(*), COALESCE(SUM(charged_usd),0) FROM attempts").fetchone()
        return {"requests": row[0], "charged_or_reserved_usd": row[1]}

    def requests(self, keys: set[str]) -> list[dict]:
        return [dict(row) for row in self.db.execute("SELECT * FROM attempts ORDER BY id")
                if row["cache_key"] in keys]

    def reserve(self, key: str, cost: float, *, max_requests: int, max_usd: float,
                max_attempts: int) -> int | None:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.latest(key)
            count = self.db.execute("SELECT COUNT(*) FROM attempts WHERE cache_key=?", (key,)).fetchone()[0]
            if prior and prior["state"] != "retryable":
                self.db.rollback()
                return None
            total = self.totals()
            if count >= max_attempts or total["requests"] >= max_requests or (
                total["charged_or_reserved_usd"] + cost > max_usd
            ):
                self.db.rollback()
                return None
            cursor = self.db.execute(
                "INSERT INTO attempts(cache_key,state,reserved_usd,charged_usd,created_at) "
                "VALUES (?,'unknown',?,?,?)",
                (key, cost, cost, dt.datetime.now(dt.timezone.utc).isoformat()),
            )
            self.db.commit()
            return cursor.lastrowid
        except BaseException:
            self.db.rollback()
            raise

    def finish(self, attempt: int, *, state: str, model: str | None = None,
               usage: dict | None = None, scores: dict | None = None,
               cost: float | None = None, error: str | None = None) -> None:
        self.db.execute(
            "UPDATE attempts SET state=?,actual_model=?,usage_json=?,scores_json=?,error=?,"
            "charged_usd=COALESCE(?,charged_usd) WHERE id=? AND state='unknown'",
            (state, model, json.dumps(usage) if usage is not None else None,
             json.dumps(scores, ensure_ascii=False) if scores is not None else None,
             error, cost, attempt),
        )
        self.db.commit()


def write_scores(rows: list[dict], path: Path) -> pl.DataFrame:
    schema = {"symbol": pl.String, "publication_date": pl.Date, "report_period": pl.Date,
              "reason_text": pl.String, "same_day_conflict": pl.Boolean, "input_id": pl.String,
              "cache_key": pl.String, "result": pl.String, "actual_model": pl.String,
              "prompt_version": pl.String, "evidence_scope": pl.String}
    for name in DIMENSIONS:
        schema.update({f"text_{name}": pl.Float64, f"{name}_status": pl.String,
                       f"{name}_evidence": pl.String})
    frame = pl.from_dicts(rows, schema=schema)
    frame.write_parquet(path)
    return frame


def asof_panel(scores: pl.DataFrame, sessions: list[dt.date], *, max_age_days: int) -> pl.DataFrame:
    """Most recent publication at close; missing newer releases invalidate old scores."""
    if max_age_days < 1 or sessions != sorted(set(sessions)):
        raise ValueError("Invalid panel dates or lifetime")
    score_columns = [f"text_{name}" for name in DIMENSIONS]
    if scores.is_empty() or not sessions:
        return pl.DataFrame(schema={"trade_date": pl.Date, "ts_code": pl.String,
                                   **{name: pl.Float64 for name in score_columns}})
    keys = ["symbol", "publication_date", "report_period"]
    # All records of a conflict produce NULL. No order among conflicting texts is invented.
    scores = scores.with_columns(*[
        pl.when(pl.col("same_day_conflict") | (pl.len().over(keys) > 1))
        .then(None).otherwise(pl.col(name)).alias(name) for name in score_columns
    ]).sort(keys).unique(subset=["symbol", "publication_date"], keep="last", maintain_order=True)
    grid = pl.DataFrame({"trade_date": sessions}).join(scores.select("symbol").unique(), how="cross")
    joined = grid.sort("trade_date").join_asof(
        scores.sort("publication_date"), left_on="trade_date", right_on="publication_date",
        by="symbol", strategy="backward", check_sortedness=False,
    )
    return joined.select("trade_date", pl.col("symbol").alias("ts_code"), *[
        pl.when((pl.col("trade_date") - pl.col("publication_date")).dt.total_days() < max_age_days)
        .then(pl.col(name)).otherwise(None).alias(name) for name in score_columns
    ]).sort("trade_date", "ts_code")


def publish_panels(run: Path, *, data_root: Path, design: dict) -> dict:
    from quant.data.factor_panels import available_sessions, check_definition, write_panel

    report = json.loads((run / "run.json").read_text(encoding="utf-8"))
    if report["dry_run"] or report["summary"].get("success", 0) == 0:
        raise ValueError("Publication requires real validated model scores")
    if report["design"] != json.loads(json.dumps(design, default=str)):
        raise ValueError("Panel design differs from scoring design")
    scores = pl.read_parquet(run / "scores.parquet")
    rows = 0
    for year in range(design["start"].year, design["end"].year + 1):
        start, end = max(design["start"], dt.date(year, 1, 1)), min(design["end"], dt.date(year, 12, 31))
        sessions = [d for d in available_sessions(data_root, end) if start <= d <= end]
        panel = asof_panel(scores, sessions, max_age_days=design["maximum_age_calendar_days"])
        for signal in design["signals"]:
            name = signal["id"]
            check_definition(data_root, name, {"design": report["design"],
                                              "scoring": report["scoring"]})
            rows += write_panel(data_root, name, year,
                                panel.select("trade_date", "ts_code", pl.col(name).alias("value")),
                                start, end, known_through=design["end"])
    return {"factor_rows": rows, "factors": len(design["signals"])}
