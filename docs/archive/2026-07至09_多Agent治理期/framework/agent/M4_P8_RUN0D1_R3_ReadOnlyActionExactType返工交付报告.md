# M4 P8 RUN-0D1 R3：Read-only action exact type 返工 — 交付报告

日期：2026-08-15  
实现模型：`cursor-grok-4.6-high`  
状态：已交付；待未参与本轮实现的外部独立初验复验，再由主 Agent 终验

关闭复验项：`RUN0D1-R2-01`  
依据：`docs/framework/agent/M4_P8_RUN0D1_R2_Operator输入与异常边界返工独立复验报告.md`

## 结果

- 状态：已交付（仅闭合 R2-01；**不是** Gate 通过，也不是 UA-M4-002 启动）
- 修改文件及目的：
  - `src/quant/execution/paper_formal_daily.py`：`run_formal_paper_daily_read_only` 在任何 `in _READ_ONLY_ACTIONS` 之前要求 `type(action) is str`
  - `tests/unit/test_paper_formal_daily.py`：read-only 对 dict / list / bytearray / `__hash__=None` 对象 / str 子类前置拒绝；合法 `"inspect"`/`"plan"` 仍委派 operator
- 明确未修改：R1 任务书/交付/初验、R2 交付/复验；`src/quant/execution/__init__.py`；`tests/unit/test_execution_cli.py`；operator CLI/import 脱敏、六动作、challenge/UNKNOWN；CLI/store/gateway/service/policy/runtime/config；M1/M2/M3/策略文件；未读 `data/`、`artifacts/`、ignored 配置或秘密；未联网；未创建订单/soak；未 add/commit/push

## 设计与合同证据

- **R2-01**：`run_formal_paper_daily_read_only` 闸门改为 `type(action) is not str or action not in _READ_ONLY_ACTIONS`，与 operator `_formal_paper_operator_argv` 对称；`type is str` 短路径在 frozenset 成员判断之前，不可 hash action 不再泄漏 `TypeError`。
- 非法 dict / list / bytearray / `__hash__=None` 的 `__eq__` 对象 / `str` 子类 `inspect`/`plan`：稳定 `FormalPaperDailyRunnerError`，code=`PAPER_FORMAL_DAILY_RUNNER_INVALID`，cause/context 空，零 operator/deps/CLI。
- 合法 exact `"inspect"`/`"plan"` 字符串仍委派 `run_formal_paper_daily_operator`（同参、返回 int）。
- 四类 dispatch/reconcile 字符串 `approve`/`paper-submit`/`cancel`/`reconcile` 仍前置拒绝。
- operator 六动作、R1-01 CLI/import 脱敏、challenge/UNKNOWN 行为未改。

## 反例结果

| 反例 | 结果 |
| --- | --- |
| read-only `action={"inspect": 1}` / `["inspect"]` / `bytearray(b"inspect")` / `__hash__=None` 对象 | `FormalPaperDailyRunnerError`；code 稳定；cause/context 空；零 operator/deps/CLI |
| read-only `str` 子类 `"inspect"`/`"plan"` | 同上前置拒绝，不委派 operator |
| 合法 `"inspect"`/`"plan"` | 委派 operator 一次并返回其 int |
| 既有四类 dispatch/reconcile 字符串拒绝 | 行为不变 |
| 既有 operator 非 exact str / CLI 脱敏 / 0/20/30 / challenge/UNKNOWN | 既有测试仍绿 |

## 验证

Windows `D:\Miniforge3\python.exe`，`PYTHONPATH=src`；工程反馈，不替代 WSL Gate。

| 命令或检查 | 结果 | 证据 |
| --- | --- | --- |
| `D:\Miniforge3\python.exe -m pytest tests/unit/test_paper_formal_daily.py tests/unit/test_execution_cli.py -q` | 通过 | `53 passed`（R2 为 45；本轮新增 8） |
| `D:\Miniforge3\python.exe -m ruff check src/quant/execution/paper_formal_daily.py tests/unit/test_paper_formal_daily.py` | 通过 | All checks passed |
| `D:\Miniforge3\python.exe -m mypy src/quant/execution/paper_formal_daily.py src/quant/execution/__init__.py` | 通过 | Success: no issues found in 2 source files |
| cold import `run_formal_paper_daily_operator` | 通过 | `FORMAL_DAILY_LAZY_IMPORT_PASS` |

## 清理与范围审查

- 无临时代码、无平行验真、无第二套 action 闸门语义
- 未改 operator CLI/import 脱敏、六动作、challenge/UNKNOWN
- 未改 `__init__.py` / `test_execution_cli.py` / 既有报告与任务书
- 范围外改动：无

## 风险与交接

- 通过仅表示 R2-01 已按合同闭合；UA-M4-002 仍要等首个正式输入
- 需要未参与本轮实现的外部独立初验复验 R2-01 反例，再由主 Agent 终验
- 回滚：丢弃本轮对 `paper_formal_daily.py`、`test_paper_formal_daily.py` 的改动及本报告；无外部状态
