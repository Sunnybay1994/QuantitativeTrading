"""Canonical importable event schema, also used by delegated CLI execution."""

from __future__ import annotations

import pandera.polars as pa
import polars as pl


class EventV0Schema(pa.DataFrameModel):
    announcement_id: str
    symbol: str
    title: str
    published: pl.Date
    known_at: pl.Date
    family: str = pa.Field(isin=["repurchase", "insider_trading"])
    amount_cny: float = pa.Field(nullable=True)
    ratio_pct: float = pa.Field(nullable=True)
    term_days: int = pa.Field(nullable=True)
    direction: str = pa.Field(isin=["buy", "sell", "repurchase"], nullable=True)
    parse_status: str = pa.Field(isin=["parsed", "unresolved"])
    human_label: str = pa.Field(nullable=True)
    evidence: str = pa.Field(nullable=True)
    excerpt: str
    adjunct_url: str = pa.Field(nullable=True)

    class Config:
        strict = True
        coerce = True
