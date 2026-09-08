# M4 P8 RUN-0D1 R2：Operator 输入与异常边界返工 — 独立复验报告

日期：2026-08-15  
角色：外部独立复验 Agent（未参与 R1/R2 实现或 R1 初验；独立上下文）  
模型：`cursor-grok-4.6-high`  
结论：**FAIL（不得进入主验；返回外部实现返工）**

关闭核对：`RUN0D1-R1-01`、`RUN0D1-R1-02`  
新阻断：`RUN0D1-R2-01`  
依据：`docs/framework/agent/M4_P8_RUN0D1_R1_FormalPAPEROperatorRunner任务单.md`、R1 交付/初验、R2 交付与最终 diff

## 独立性与范围

只读核对：根 `AGENTS.md`、`.ai/README.md`、R1 任务单/交付/初验、R2 交付、白名单 diff、
`src/quant/execution/paper_formal_daily.py`、`src/quant/execution/__init__.py`、
`tests/unit/test_paper_formal_daily.py`、邻接 `quant.execution.cli.main`。

未改生产代码、实现者测试、任务书、既有交付/初验报告；未读取 `data/`、`artifacts/`、ignored 配置或秘密；
未联网、未创建真实订单/soak；未 add/commit/push。唯一仓库写入即本报告。

实现者自测与 R2 交付仅作待核证据。下列对抗探针为本轮独立执行，未写入实现者测试。

## 标准—证据—结论

| 合同 | 独立证据 | 判定 |
|---|---|---|
| **R1-01**：CLI import/`main(...)` 纳入同一脱敏 `try`；`except FormalPaperDailyRunnerError: raise`；`except Exception` 包装 | 源码 485–504 行；实现者 CLI 环形图/ImportError 测试绿；本轮三节点 `__cause__`/`__context__` 环、自定义 `__str__`/`__repr__`、`add_note(MARKER)`、`ImportError` 递归图均 `FormalPaperDailyRunnerError`，code 稳定，cause/context 空，str/repr/traceback 无 marker | **PASS（R1-01 关闭）** |
| **R1-02**：operator `type(action) is str` 后成员判断 | `_formal_paper_operator_argv` 513 行短路径；str 子类/`bytes`/`bytearray`/`memoryview`/dict/set/不可 hash `__eq__`/`True`/`INSPECT`/`inspect `/`paper-Submit` 均 deps=0、cli=0、`FormalPaperDailyRunnerError` | **PASS（operator 路径关闭）** |
| 合法 int exit 原样返回 | patch `main` 返回 `0/20/30/2/70`：`type is int` 且 `is` 同一对象，不改写成异常 | **PASS** |
| 每次调用 deps exact once | 六动作各一次：`builds==[1]` 且 CLI argv 为 canonical 单次 | **PASS** |
| 六动作 / challenge / UNKNOWN / cancel 幂等 | 实现者 `45 passed`；本轮 approve 两步、submit 完成、cancel challenge→`CANCEL_COMPLETE`（`cancel_calls==1`）→再 challenge→`CANCEL_ALREADY_COMPLETED`（仍 1） | **PASS** |
| `UNKNOWN` 不自动重发 | 实现者二次 submit 仍 30、gateway=1；本轮未重复消耗 | **PASS** |
| read-only 仍只允许 inspect/plan 字符串 | `approve`/`paper-submit`/`cancel`/`reconcile` 仍 `FormalPaperDailyRunnerError`；str 子类 `inspect` 经 operator 闸门拒绝 | **字符串无回归；不可 hash 见 R2-01** |
| BaseException vs Exception | `KeyboardInterrupt`/`SystemExit`/`GeneratorExit` 原样穿透（marker 可在 BaseException 中）；`RuntimeError` 脱敏。与 R1-01 冻结的 `except Exception` 一致 | **既有合同，不升格** |
| `main` 返回 bool/str/None/float | 原样穿透，不包装为 `FormalPaperDailyRunnerError`（`return main(...)` 只捕获抛出）。R1-01 通过条件是 int 不改写 + 抛出 Exception 脱敏，未冻结返回值 runtime 类型闸门 | **既有合同解释；残留不升格** |
| **read-only 不可 hash action** | `action={...}` / `["inspect"]` / `bytearray` → **`TypeError: unhashable type: ...`**，不是 `FormalPaperDailyRunnerError` | **FAIL（R2-01）** |

## 问题

### RUN0D1-R2-01（阻断）：read-only 改用 frozenset 成员判断，不可 hash action 泄漏 TypeError

- 现象：`run_formal_paper_daily_read_only(action={"inspect": 1} | ["inspect"] | bytearray(b"inspect"))` 抛出
  `TypeError: unhashable type: 'dict'|'list'|'bytearray'`，`type` 不是 `FormalPaperDailyRunnerError`。
  对照：同一不可 hash 值交给 `run_formal_paper_daily_operator` 时，因 `type(action) is not str` 短路径，
  deps/CLI 均为 0 且稳定 `FormalPaperDailyRunnerError`。R1 读路径使用 `action not in ("inspect", "plan")`
  （tuple 走等式、不 hash），dict/list/bytearray 会得到 `FormalPaperDailyRunnerError`；R2 改为
  `action not in _READ_ONLY_ACTIONS`（frozenset 要 hash）后回归。
- 根因：R2 把 read-only 闸门从 tuple 换成模块级 frozenset，且该 `in` 检查位于 operator 脱敏 `try` 之外，
  也没有与 operator 对称的 `type(action) is str` 短路径。实现者只测了 operator 的 str 子类/bytes/int/None/list，
  未测 read-only 不可 hash。
- 应遵循规则：R1-02 通过条件「非法 action 一律 `FormalPaperDailyRunnerError` 且零 deps/CLI」；任务单 §3.7
  稳定异常必须是 `FormalPaperDailyRunnerError`，cause/context 清空；本轮复验要求覆盖 action 不可 hash
  变体并确认 read-only 无回归。frozenset 成员判断不得把 TypeError 漏给调用方。
- 最小复现：禁止 deps/CLI；调用
  `run_formal_paper_daily_read_only(action={"inspect": 1}, environment=object(), policy=object(), composition=object(), session_date=..., now=...)`。
  当前为 `TypeError`；operator 对同一 action 为 `FormalPaperDailyRunnerError`。
- 必须新增的测试：read-only 对 dict / list / bytearray / `__hash__ = None` 的 `__eq__` 对象；断言
  `type is FormalPaperDailyRunnerError`、code 稳定、cause/context 空、零 deps/CLI。保留 str 子类
  `inspect`/`plan` 与四类 dispatch 字符串拒绝。不得只测 operator。
- 通过条件：read-only 在任何 `in _READ_ONLY_ACTIONS` 之前要求 `type(action) is str`（与 operator 对称），
  非法类型一律 `FormalPaperDailyRunnerError() from None`；合法 `"inspect"`/`"plan"` 字符串仍委派 operator；
  operator 六动作与 R1-01 脱敏保持不变。返工后由未参与该轮实现的外部初验复验本反例、实现者定向测试、
  Ruff/mypy/cold import。

## 独立对抗核对（实现者未用）

| 反例 | 结果 |
|---|---|
| CLI 三节点 cause/context 环 + 自定义 `__repr__`/`__str__` + `add_note(MARKER)` | 脱敏，PASS |
| `from quant.execution.cli import main` 缺 `main`；`__getattr__` 抛带环的 `ImportError` | 脱敏，PASS |
| `KeyboardInterrupt` / `SystemExit` / `GeneratorExit` | 按 `except Exception` 穿透，既有合同 |
| operator str 子类 / 不可 hash dict·set·`__hash__=None` / 大小写空白 | 前置拒绝，PASS |
| read-only dict / list / bytearray / `__hash__=None` | **TypeError，R2-01** |
| `main` 返回 `True`/`False`/`"0"`/`None`/`0.0` | 原样穿透；既有合同解释（非 Exception、非 int 闸门） |
| 合法 int `0/20/30/2/70` | 原样 int，PASS |
| 六动作 deps exact once | PASS |
| cancel 两步 + `CANCEL_ALREADY_COMPLETED` 且 `cancel_calls==1` | PASS |

## 验证

Windows `D:\Miniforge3\python.exe`，`PYTHONPATH=src`；独立 `--basetemp`；不替代 WSL Gate。

| 命令 | 结果 |
|---|---|
| `pytest tests/unit/test_paper_formal_daily.py tests/unit/test_execution_cli.py -q` | `45 passed`（实现者测试绿，不能掩盖 R2-01） |
| `ruff check` 白名单三路径 | All checks passed |
| `mypy` 两生产文件 | Success: no issues found |
| cold import `run_formal_paper_daily_operator` | `FORMAL_DAILY_LAZY_IMPORT_PASS` |
| 独立对抗探针 | 合同表所列；read-only 不可 hash **FAIL** |

## 结论

**FAIL** — R1-01 CLI/import 脱敏与 operator 侧 R1-02 exact `str` 闸门在 Windows 定向证据下已关闭；
合法 int exit、deps once、六动作 challenge/UNKNOWN/cancel 幂等无回归。但 R2 将 read-only 成员判断
改为 frozenset 后，不可 hash action 泄漏 `TypeError`，破坏稳定异常合同与 read-only 无回归。

本轮**只解锁返工，不解锁主验**。回滚仍是丢弃本轮对 `paper_formal_daily.py`、`test_paper_formal_daily.py`
的改动及 R2 交付报告；本报告不改变生产状态。
