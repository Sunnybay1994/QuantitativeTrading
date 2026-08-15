# M4 P8 RUN-0D1 R3：Read-only action exact type 返工 — 独立复验报告

日期：2026-08-15  
角色：外部独立复验 Agent（未参与 R1/R2/R3 实现或既有初验；独立上下文）  
模型：`cursor-grok-4.6-high`  
结论：**PASS（仅解锁主 Agent 终验）**

关闭核对：`RUN0D1-R2-01`  
回归核对：`RUN0D1-R1-01`、`RUN0D1-R1-02`  
依据：`docs/agent/M4_P8_RUN0D1_R1_FormalPAPEROperatorRunner任务单.md`、
`docs/agent/M4_P8_RUN0D1_R2_Operator输入与异常边界返工独立复验报告.md`、
`docs/agent/M4_P8_RUN0D1_R3_ReadOnlyActionExactType返工交付报告.md`

## 独立性与范围

只读核对：根 `AGENTS.md`、`.ai/README.md`、`.ai/coding_rules.md`、R1 任务单、R2 复验、R3 交付、
白名单 diff、`src/quant/execution/paper_formal_daily.py`、`src/quant/execution/__init__.py`、
`tests/unit/test_paper_formal_daily.py`、邻接 `tests/unit/test_execution_cli.py`。

未改生产代码、实现者测试、任务书、既有交付/初验报告；未读取 `data/`、`artifacts/`、ignored 配置或秘密；
未联网、未创建真实订单/soak；未 add/commit/push。唯一仓库写入即本报告。

实现者自测与 R3 交付仅作待核证据。下列对抗探针为本轮独立执行，未写入实现者测试。

## 标准—证据—结论

| 合同 | 独立证据 | 判定 |
|---|---|---|
| **R2-01**：read-only 在任何 `in _READ_ONLY_ACTIONS` 之前 `type(action) is str`；非法类型稳定 `FormalPaperDailyRunnerError`，code 精确，cause/context 空，零 operator/deps/CLI | 源码 459–460 行 `type(action) is not str or action not in _READ_ONLY_ACTIONS`；`or` 短路。实现者 dict/list/bytearray/`__hash__=None`/str 子类测试绿。本轮复现上述类型，并加 `__hash__` 抛异常、`__eq__` 抛异常（hash 与 `"inspect"` 碰撞）、另一套 str 子类/`StrEnum`/`UserString`/set/memoryview：一律 `type is FormalPaperDailyRunnerError`，code=`PAPER_FORMAL_DAILY_RUNNER_INVALID`，cause/context 空；hash/eq 调用计数均为 0 | **PASS（R2-01 关闭）** |
| 合法 exact str `inspect`/`plan` 只委派 operator | 独立 spy：各调用一次，kwargs 原样，返回 operator int；不另建 deps/CLI | **PASS** |
| `approve`/`paper-submit`/`cancel`/`reconcile` 仍由 read-only 前置拒绝 | 四动作均为 `FormalPaperDailyRunnerError`，operator/deps/CLI 均为 0 | **PASS** |
| **R1-01**：CLI import/`main(...)` 仍在同一脱敏 `try`；hostile Exception 图不泄漏 | 源码 485–504 行。本轮三节点 `__cause__`/`__context__` 环 + 自定义 `__str__`/`__repr__` + `add_note(MARKER)`；模块 `__getattr__` 抛带环 `ImportError`。均为 `FormalPaperDailyRunnerError`，code 稳定，cause/context 空，str/repr/traceback 无 marker | **PASS（仍关闭）** |
| **R1-02**：operator 非 exact str 仍在依赖前拒绝 | `_formal_paper_operator_argv` 513 行。本轮 dict/set/bytearray/`InspectToken`/`True`/`INSPECT`/`inspect `/`paper-Submit`/memoryview/`HashBomb`/`EqBomb`：deps=0、cli=0，hash/eq=0 | **PASS（仍关闭）** |
| BaseException vs Exception | `KeyboardInterrupt` 仍穿透（既有 `except Exception` 合同，不升格） | **既有合同** |

## 独立对抗核对（实现者未用）

实现者 read-only 反例止于 dict / list / bytearray / `__hash__=None` 且 `__eq__` 恒 False / 单一 `_ActionStr`。
本轮另用：

| 反例 | 结果 |
|---|---|
| read-only `__hash__` 抛 `RuntimeError(MARKER)` | 不调用 `__hash__`/`__eq__`；稳定 runner error；零下游 |
| read-only `__eq__` 抛异常且 `__hash__` 与 `"inspect"` 碰撞 | 不调用 `__hash__`/`__eq__`；稳定 runner error；零下游 |
| read-only 另一套 str 子类 `InspectToken`/`PlanLabel`、`enum.StrEnum`、`UserString` | 前置拒绝，不委派 operator |
| read-only set / memoryview / `True` / `INSPECT` / `inspect ` / `paper-Submit` | 前置拒绝，零下游 |
| `__hash__=None` 且 `__eq__` 对 `"inspect"` 返回 True | `__eq__` 调用 0；稳定 runner error |
| operator 侧 HashBomb/EqBomb/dict/str 子类/大小写空白 | 仍 deps/CLI 前拒绝 |
| CLI 三节点环 + `__str__`/`__repr__`/`add_note` | 脱敏，PASS |
| `from quant.execution.cli import main` 经 `__getattr__` 抛带环 ImportError | 脱敏，PASS |
| `KeyboardInterrupt` | 按既有合同穿透 |

## 白名单 diff

相对已提交 HEAD 的本包相关脏文件：

- `src/quant/execution/paper_formal_daily.py`：含 R1 operator + R2 脱敏/exact str + **R3 read-only `type is str` 短路径**
- `tests/unit/test_paper_formal_daily.py`：含 R1/R2 测试 + **R3 新增 8 项 read-only 非 exact str 用例**
- `src/quant/execution/__init__.py`：仍仅为 R1 `run_formal_paper_daily_operator` lazy 导出三处 +1 行；R3 未再改
- `tests/unit/test_execution_cli.py`：**无 diff**
- `docs/agent/M4_P8_RUN0D1_R3_ReadOnlyActionExactType返工交付报告.md`：实现者交付（既有，本轮只读）

R3 闭合 R2-01 的生产改动落在任务白名单内。工作区另有无关 M2 未提交文件，不在本包范围，本轮未读写。

## 验证

Windows `D:\Miniforge3\python.exe`，`PYTHONPATH=src`；独立 `--basetemp`；工程反馈，**不替代 WSL Gate**。

| 命令 | 结果 |
|---|---|
| `pytest tests/unit/test_paper_formal_daily.py tests/unit/test_execution_cli.py -q` | `53 passed`（12.49s） |
| `ruff check` 两生产文件 + 两测试文件 | All checks passed |
| `mypy` `paper_formal_daily.py` + `__init__.py` | Success: no issues found in 2 source files |
| cold import `run_formal_paper_daily_operator` | `FORMAL_DAILY_LAZY_IMPORT_PASS` |
| 独立对抗探针 | 37/37 PASS |

## 结论

**PASS** — R2-01 已按合同闭合：read-only 以 `type is str` 短路径拒绝不可 hash / 非 exact str action，不再泄漏 `TypeError`；合法 `"inspect"`/`"plan"` 仍只委派 operator；dispatch/reconcile 仍前置拒绝。R1-01 CLI/import 脱敏与 R1-02 operator exact str 闸门无回归。

本轮**只解锁主 Agent 终验**，**不代表** UA-M4-002、PAPER 启动、soak 或任何 Gate 通过。Windows 定向结果不是 WSL 平台终验。回滚仍是丢弃本包对 `paper_formal_daily.py`、`test_paper_formal_daily.py` 的未提交改动及 R3 交付/本报告；本报告不改变生产状态。
