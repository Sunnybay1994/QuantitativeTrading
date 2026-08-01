"""prediction_score -> 等权 Top-k 目标权重（无状态第一版）。

n_drop 状态化策略暂不实现；接口评审记录见模块文档字符串末尾。
"""

from __future__ import annotations

import datetime as dt

import polars as pl

from quant.domain import TargetWeightSchema
from quant.research.m3.predictions import normalize_prediction_scores
from quant.strategies.base import Strategy

_IDENTITY_COLS = (
    "model",
    "model_version",
    "dataset_snapshot_id",
    "fold",
    "horizon_sessions",
)


class MlTopkStrategy(Strategy):
    """无状态等权 Top-k；不读取账户，不隐藏上期持仓状态。"""

    def __init__(
        self,
        *,
        name: str = "m3_topk",
        version: str = "m3_topk_v1",
        top_k: int = 30,
        cash_buffer: float = 0.05,
        max_weight: float | None = None,
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k 必须为正")
        if not 0.0 <= cash_buffer < 1.0:
            raise ValueError("cash_buffer 必须在 [0, 1)")
        if max_weight is not None and max_weight <= 0:
            raise ValueError("max_weight 必须为正")
        self.name = name
        self.version = version
        self.top_k = top_k
        self.cash_buffer = cash_buffer
        self.max_weight = max_weight

    def target_weights(self, as_of: dt.date, data: pl.DataFrame) -> pl.DataFrame:
        """``data`` 必须同时包含预测列与 ``eligible`` 资格列。"""
        if "eligible" not in data.columns:
            raise ValueError("data 必须包含 eligible 列")

        day = data.filter(pl.col("as_of") == as_of)
        if day.is_empty():
            return _empty_targets()

        eligibility = _resolve_eligibility(day)
        pred_cols = [col for col in day.columns if col != "eligible"]
        predictions = normalize_prediction_scores(day.select(pred_cols))
        _assert_single_slice(predictions)

        cross = predictions.join(eligibility, on="symbol", how="left").with_columns(
            pl.col("eligible").fill_null(False)
        )
        eligible = cross.filter(pl.col("eligible")).sort(
            ["score", "symbol"], descending=[True, False]
        )
        selected = eligible.head(self.top_k)
        investable = 1.0 - self.cash_buffer
        weights = {row["symbol"]: 0.0 for row in cross.iter_rows(named=True)}
        if not selected.is_empty():
            raw = investable / selected.height
            if self.max_weight is not None:
                raw = min(raw, self.max_weight)
            for row in selected.iter_rows(named=True):
                weights[row["symbol"]] = raw

        total = sum(weights.values())
        if total > investable + 1e-12:
            raise ValueError("总权重超过 1-cash_buffer")

        rows = [
            {
                "as_of": as_of,
                "strategy": self.name,
                "strategy_version": self.version,
                "symbol": symbol,
                "weight": weight,
            }
            for symbol, weight in sorted(weights.items())
        ]
        frame = pl.DataFrame(rows)
        if frame.get_column("symbol").n_unique() != frame.height:
            raise ValueError("目标权重每个 symbol 只能一行")
        return TargetWeightSchema.validate(frame)


def _assert_single_slice(predictions: pl.DataFrame) -> None:
    keys = predictions.select(list(_IDENTITY_COLS)).unique()
    if keys.height != 1:
        raise ValueError(
            "同日预测必须只包含一个 "
            "(model,model_version,dataset_snapshot_id,fold,horizon_sessions) 切片"
        )


def _resolve_eligibility(day: pl.DataFrame) -> pl.DataFrame:
    rows = day.select("symbol", "eligible")
    conflict = (
        rows.group_by("symbol")
        .agg(pl.col("eligible").n_unique().alias("n"))
        .filter(pl.col("n") > 1)
    )
    if not conflict.is_empty():
        raise ValueError("同一 symbol 存在冲突的 eligible 布尔值")
    return rows.unique(subset=["symbol"])


def _empty_targets() -> pl.DataFrame:
    return TargetWeightSchema.validate(
        pl.DataFrame(
            schema={
                "as_of": pl.Date,
                "strategy": pl.Utf8,
                "strategy_version": pl.Utf8,
                "symbol": pl.Utf8,
                "weight": pl.Float64,
            }
        )
    )


# 接口评审记录（D6）：
# MlTopkDropStrategy 需要上期选择集合才能实现 n_drop；当前 Strategy.target_weights
# 只有 (as_of, data) 签名，不能藏全局/可变对象状态。下一版建议扩展为 keyword-only
# previous_selection: set[str] | None = None，由 portfolio 层显式传入。
