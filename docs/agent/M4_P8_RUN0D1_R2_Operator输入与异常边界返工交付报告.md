# M4 P8 RUN-0D1 R2：Operator 输入与异常边界返工 — 交付报告

日期：2026-08-15  
实现模型：`cursor-grok-4.6-high`  
状态：已交付；待未参与本轮实现的外部独立初验复验，再由主 Agent 终验

关闭初验项：`RUN0D1-R1-01`、`RUN0D1-R1-02`  
依据：`docs/agent/M4_P8_RUN0D1_R1_FormalPAPEROperatorRunner独立初验报告.md`

## 结果

- 状态：已交付（仅闭合两项初验缺口；**不是** Gate 通过，也不是 UA-M4-002 启动）
- 修改文件及目的：
  - `src/quant/execution/paper_formal_daily.py`：CLI import 与 `main(...)` 纳入同一脱敏 `try`；`action` 在 argv 闸门要求 `type is str`
  - `tests/unit/test_paper_formal_daily.py`：CLI 递归异常图脱敏、诚实 ImportError 注入、action str 子类/非 str、int 0/20/30 原样返回
- 明确未修改：R1 任务书/交付/初验报告；`src/quant/execution/__init__.py`；`tests/unit/test_execution_cli.py`；CLI/store/gateway/service/policy/runtime/config；M1/M2/M3/策略文件；未读 `data/`、`artifacts/`、ignored 配置或秘密；未联网；未创建订单/soak；未 add/commit/push

## 设计与合同证据

- **R1-01**：`from quant.execution.cli import main` 与 `return main(...)` 移入 argv/deps 同一 `try`。`except FormalPaperDailyRunnerError: raise`；`except Exception: raise FormalPaperDailyRunnerError() from None`。`main` 正常返回的 int 不改写成异常。
- **R1-02**：`_formal_paper_operator_argv` 在成员判断前要求 `type(action) is str`；str 子类/bytes/其他类型在 deps/CLI 前 `FormalPaperDailyRunnerError`。
- 六动作、challenge/幂等、UNKNOWN 不重发、read-only 只允许 inspect/plan：既有测试保留且仍绿。
- ImportError 诚实注入：不改生产 import 形态；测试用无 `main` 的 `sys.modules["quant.execution.cli"]` 假模块，`__file__` 带绝对路径 marker，触发真实 `from quant.execution.cli import main`。

## 反例结果

| 反例 | 结果 |
| --- | --- |
| CLI `main` 抛环形 `__cause__`/`__context__` + TOKEN/路径/账号 marker | `FormalPaperDailyRunnerError`；code 稳定；cause/context 空；str/repr/traceback 无 marker |
| `from quant.execution.cli import main` 失败（ImportError 带路径 marker） | 同上脱敏；零真实 CLI 动作 |
| `action=Str("inspect")` / bytes / int / None / list | deps/CLI 前拒绝 |
| patch `main` 返回 0/20/30 | 原样 int，不包装为异常 |
| 既有 challenge/幂等/错误 confirm/UNKNOWN/read-only | 行为不变 |

## 验证

Windows `D:\Miniforge3\python.exe`，`PYTHONPATH=src`；工程反馈，不替代 WSL Gate。

| 命令或检查 | 结果 | 证据 |
| --- | --- | --- |
| `D:\Miniforge3\python.exe -m pytest tests/unit/test_paper_formal_daily.py tests/unit/test_execution_cli.py -q` | 通过 | `45 passed`（R1 为 34；本轮新增 11） |
| `D:\Miniforge3\python.exe -m ruff check src/quant/execution/paper_formal_daily.py tests/unit/test_paper_formal_daily.py` | 通过 | All checks passed |
| `D:\Miniforge3\python.exe -m mypy src/quant/execution/paper_formal_daily.py src/quant/execution/__init__.py` | 通过 | Success: no issues found in 2 source files |
| cold import `run_formal_paper_daily_operator` | 通过 | `FORMAL_DAILY_LAZY_IMPORT_PASS` |

## 清理与范围审查

- 无临时代码、无平行验真、无第二套 challenge/exit 逻辑
- 未改 CLI；未改 `__init__.py` / `test_execution_cli.py`
- 范围外改动：无

## 风险与交接

- 通过仅表示两项初验缺口已按合同闭合；UA-M4-002 仍要等首个正式输入
- 需要未参与本轮实现的外部独立初验复验 R1-01/R1-02 反例，再由主 Agent 终验
- 回滚：丢弃本轮对 `paper_formal_daily.py`、`test_paper_formal_daily.py` 的改动及本报告；无外部状态
