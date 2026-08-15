# M4 P8 RUN-0D1 R1：Formal PAPER Operator Runner — 交付报告

日期：2026-08-15  
实现模型：`cursor-grok-4.6-high`  
状态：已交付；待独立外部初验与主 Agent 验收

## 结果

- 状态：已交付（operator wrapper 可用；**不是** Gate 通过，也不是 UA-M4-002 启动）
- 修改文件及目的：
  - `src/quant/execution/paper_formal_daily.py`：新增 `run_formal_paper_daily_operator`；只读 runner 仍只允许 `inspect/plan`，并委派同一 operator
  - `src/quant/execution/__init__.py`：lazy 安全导出 `run_formal_paper_daily_operator`
  - `tests/unit/test_paper_formal_daily.py`：参数矩阵前置拒绝、challenge/幂等、错误 confirm、UNKNOWN 不重发、hostile 脱敏
- 明确未修改：CLI/store/gateway/service/policy/runtime/config Schema；未注册 Task Scheduler；未创建真实 source selector、候选、opening facts、订单、成交或 soak 证据；未 add/commit/push；未触碰工作树中 M1/M2/M3 或策略会话已有改动

## 设计与合同证据

- 每次调用只构造一次 `build_formal_paper_daily_dependencies`，再拼接 canonical argv 调用既有 `quant.execution.cli.main`
- `inspect/plan/reconcile` 携 `confirm_sha256` 或 `command_id`：dependencies/CLI 前 `FormalPaperDailyRunnerError`
- `approve/paper-submit` 携 `command_id`：前置拒绝；无 confirm 返回 CLI `20` 且零 staged/sent
- `cancel` 缺非空 `command_id`：前置拒绝
- 正确 digest：approve 只 stage；paper-submit 只发送已 stage 的 PAPER command；重复调用保持 CLI 幂等，不产生第二份命令
- 错误 confirm：不 stage/不发送；UNKNOWN 后再次调用返回既有 query-required，gateway 调用次数不变
- hostile fresh/dependency 异常脱敏为 `PAPER_FORMAL_DAILY_RUNNER_INVALID`，cause/context 为空，零 CLI 调用
- 既有 read-only runner 仍拒绝 `approve`/`paper-submit`/`cancel`/`reconcile`

未复制 CLI confirmation、exit code 或幂等语义；未改 `auto_trade`；wrapper 不循环、不等待、不跨日补发。

## 验证

| 命令或检查 | 结果 | 证据 |
| --- | --- | --- |
| `D:\Miniforge3\python.exe -m pytest tests/unit/test_paper_formal_daily.py tests/unit/test_execution_cli.py -q` | 通过 | `34 passed`（Windows 反馈，不替代 WSL Gate） |
| `D:\Miniforge3\python.exe -m ruff check src/quant/execution/paper_formal_daily.py src/quant/execution/__init__.py tests/unit/test_paper_formal_daily.py` | 通过 | All checks passed |
| `D:\Miniforge3\python.exe -m mypy src/quant/execution/paper_formal_daily.py src/quant/execution/__init__.py` | 通过 | Success: no issues found in 2 source files |
| cold import `run_formal_paper_daily_operator` | 通过 | `FORMAL_DAILY_LAZY_IMPORT_PASS` |

## 清理与范围审查

- 无临时代码、无平行验真、无第二套 challenge 逻辑
- 未改 CLI/文档 SSOT 以外的交付报告
- 范围外改动：无

## 风险与交接

- 本包不依赖真实候选或真实开盘数据，也未启动 PAPER
- 通过仅表示 operator wrapper 可用；UA-M4-002 的真实 28 日计时仍要等首个正式输入
- 需要未参与本实现的外部独立初验，再由主 Agent 终验
- 回滚：丢弃白名单三文件 + 本报告即可；无外部状态
