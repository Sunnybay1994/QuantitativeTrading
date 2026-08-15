# M4 P8 RUN-0D1 R3：Formal PAPER Operator Runner 主 Agent 最终验收报告

日期：2026-08-15  
结论：**Windows 工程验收 PASS；未启动 PAPER、订单、任务或 28 日 soak**

## 验收范围

本次验收只关闭 RUN-0D1 operator wrapper 的工程合同：在既有 formal daily dependency builder 与
`quant.execution.cli` 之间增加 PAPER-only 的人工操作入口，支持 `inspect`、`plan`、`approve`、
`paper-submit`、`cancel`、`reconcile`。wrapper 不复制 CLI 的 challenge、幂等、UNKNOWN 或订单状态语义，
不自动确认、重试、跨日补发或切换为 LIVE。

R1 独立初验发现 CLI import/main 异常未被统一脱敏及非 exact action 可进入依赖链；R2 关闭这两项后，独立
复验又发现 read-only 入口会先对不可 hash action 做集合成员判断并泄漏 `TypeError`。R3 在成员判断前加入
exact `str` 闸门，并补齐 dict、list、bytearray、不可 hash 对象及 `str` 子类的零下游回归。全新的外部复验
Agent 使用 `cursor-grok-4.6-high` 增加 hash/eq 抛异常、`StrEnum`、`UserString` 与 hostile exception graph
反例，结论 PASS。

## 主验结果

Windows 原生 `D:\Miniforge3\python.exe`，`PYTHONPATH=src`：

- `pytest tests/unit/test_paper_formal_daily.py tests/unit/test_execution_cli.py -q`：`53 passed`；
- Ruff：两生产文件与两定向测试文件全部通过；
- mypy：`paper_formal_daily.py` 与 execution lazy export 通过；
- cold import：`FORMAL_DAILY_MAIN_COLD_PASS`，读取 public operator 不提前加载 CLI；
- scoped diff-check：无 whitespace error。

主验确认：

1. 每次合法 operator 调用只构造一次 fresh formal daily dependencies；
2. read-only exact `inspect/plan` 仅委派 operator，其他动作及所有非 exact `str` 在 operator/dependencies/CLI
   前拒绝；
3. CLI import/main 的 hostile `Exception` 图统一转换为 `PAPER_FORMAL_DAILY_RUNNER_INVALID`，
   `__cause__`/`__context__` 为空；
4. approve/submit/cancel 仍使用既有 CLI challenge 与幂等语义，UNKNOWN 不自动重发；
5. 本包没有创建 source selector、候选、opening facts、订单、成交、系统任务或 soak 证据。

## 边界与下一步

本结论只证明 Windows operator 工程闭包可用，不代表 UA-M4-002、PAPER、28 日 soak、Linux/ext4 或 M4 整体
Gate 已完成。真实启动仍等待策略会话在冻结后生成可准入的 `PAPER_CANDIDATE`，并为其下一共同开市日生成
receipt-backed opening facts；按当前计划理论最早为 2026-09-01，届时仍保持人工 challenge、仅 PAPER、
`auto_trade=false` 与 UNKNOWN 不自动重发。

