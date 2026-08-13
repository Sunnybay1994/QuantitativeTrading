"""研究编排入口；稳定计算逻辑仍位于 factors/strategies/backtest。"""

from quant.research.lightweight_run import (
    LightweightResearchRunV1,
    ResearchFoldV1,
    ResearchInputDigestV1,
    ResearchOutputDigestV1,
    compute_code_sha256,
    dataframe_input_digest,
    publish_lightweight_research_run,
)

__all__ = [
    "LightweightResearchRunV1",
    "ResearchFoldV1",
    "ResearchInputDigestV1",
    "ResearchOutputDigestV1",
    "compute_code_sha256",
    "dataframe_input_digest",
    "publish_lightweight_research_run",
]
