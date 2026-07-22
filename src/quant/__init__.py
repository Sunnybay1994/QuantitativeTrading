"""A股/港股通个人量化投研交易系统。

架构原则(详见《A股港股通个人量化投研交易系统调研.md》):
- 研究与交易解耦,共享同一数据契约与 target_weight 接口。
- 券商 API 只允许出现在 execution 的 Gateway 适配层。
- 数据源 SDK 只允许出现在 data/connectors 内部。
"""

__version__ = "0.1.0"
