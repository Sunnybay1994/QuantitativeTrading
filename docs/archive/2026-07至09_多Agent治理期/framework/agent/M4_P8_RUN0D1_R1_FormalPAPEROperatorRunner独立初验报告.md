# M4 P8 RUN-0D1 R1：Formal PAPER Operator Runner — 独立初验报告

日期：2026-08-15  
角色：外部独立初验 Agent（未参与实现；独立上下文）  
模型：`cursor-grok-4.6-high`  
结论：**FAIL（不得进入主验；返回外部实现返工）**

## 独立性与范围

只读核对：根 `AGENTS.md`、`.ai/README.md`、任务单、交付报告、白名单 diff、
`src/quant/execution/paper_formal_daily.py`、`src/quant/execution/__init__.py`、
`tests/unit/test_paper_formal_daily.py`、邻接 `quant.execution.cli.main`。

未改生产代码、实现者测试、任务书、交付报告；未读取 `data/`、`artifacts/`、ignored 配置或秘密；
未联网、未创建真实订单/soak；未 add/commit/push。唯一写入即本报告。

## 标准—证据—结论

| 合同 | 独立证据 | 判定 |
|---|---|---|
| 公开 `run_formal_paper_daily_operator` 六动作 + lazy 导出 | 签名/`__all__`/`_FORMAL_DAILY_EXPORTS`；cold import `FORMAL_DAILY_LAZY_IMPORT_PASS` | PASS |
| 每次调用只构造一次 `build_formal_paper_daily_dependencies` | 实现顺序 argv→deps→CLI；初验单次 `plan` `builds==[1]`；inspect/reconcile 各 1 次 | PASS |
| `inspect/plan/reconcile` 携 confirm/command 前置拒绝 | 实现者参数化测试 + `_forbid_deps_and_cli`；初验复跑绿 | PASS |
| `approve/paper-submit` 禁 `command_id`；无 confirm 返回 20 且零 staged/sent | 实现者测试 + 初验复跑 | PASS |
| `cancel` 缺非空 `command_id` 前置拒绝 | `None`/`""` 测试；非 str 初验拒绝 | PASS |
| 正确 digest：approve 只 stage；paper-submit 只发送已 stage；重复幂等 | 实现者 9 次调用/`APPROVAL_STAGED_REPLAY`/`SUBMIT_ALREADY_COMPLETE`；初验 cancel `CANCEL_ALREADY_COMPLETED` 且 `cancel_calls==1` | PASS |
| 错误 confirm 不 stage/不发送 | `CONFIRMATION_DRIFT` + 零 gateway | PASS |
| `UNKNOWN` 不自动重发；wrapper 不循环 | 实现者二次 `paper-submit` 仍 30、gateway=1；初验再带同一 confirm 与再次 challenge，gateway 仍 1 | PASS |
| 既有 read-only 只允许 inspect/plan，拒绝 dispatch/reconcile | 实现者参数化拒绝；初验 inspect/plan 真 CLI 成功且 gateway/broker=0；签名拒绝 `confirm_sha256` | PASS |
| 不复制 CLI confirmation/exit/幂等；不改 auto_trade；不注册调度/soak | diff 仅白名单三文件 + 本包报告；CLI 仍 SSOT | PASS |
| action exact type/大小写/空白 | bytes/int/None/list/`INSPECT`/`inspect `/`paper-Submit` 均 deps=0 拒绝；**`str` 子类 `StrInspect("inspect")` 会进入 deps** | **缺口** |
| confirm/command hostile 非 str | bytes/bytearray/int/bool/list/dict/object → `FormalPaperDailyRunnerError`，零 CLI | PASS |
| hostile fresh/dependency 递归异常图脱敏、零 CLI | 初验环形 `__cause__`/`__context__` + TOKEN/路径/账号 marker；str/repr/traceback 无泄漏 | PASS |
| **CLI hostile 递归异常图脱敏** | monkeypatch `cli.main` 抛同一环形图 → **原样 `RuntimeError` 泄漏，含 cause 与 marker** | **FAIL** |

## 问题

### RUN0D1-R1-01（阻断）：CLI 调用与 import 落在脱敏 try 外，hostile 异常图泄漏

- 现象：`run_formal_paper_daily_operator` 在 argv/deps 成功后执行
  `from quant.execution.cli import main` 与 `return main(...)`。将 `cli.main` 换成抛出
  `RuntimeError(TOKEN C:/secret sqlite:///hostile-path ACCOUNT-12345)` 且
  `__cause__`/`__context__` 互指的递归图时，调用方收到原始 `RuntimeError`，
  `str`/`repr`/`traceback.format_exception` 均含 marker；`__cause__` 为 `ValueError`；
  不是 `FormalPaperDailyRunnerError`。
- 根因：脱敏 `try/except` 只包住 `_formal_paper_operator_argv` 与
  `build_formal_paper_daily_dependencies`（约 485–501 行）。CLI import 与调用在 except 之后
  （502–504 行）。实现者只测了 deps `RuntimeError`，未测 CLI 边界。
- 应遵循规则：任务单 §3.7 稳定异常必须是 `FormalPaperDailyRunnerError`，cause/context 清空，
  不泄露路径/账号/输入；独立初验合同要求 CLI hostile 递归异常图脱敏。§3.3 仍要求 CLI
  **exit code/stdout/stderr** 为 SSOT：仅当 `main` **返回 int** 时原样返回；**抛出** 的
  `Exception` 不得穿透 wrapper。
- 最小复现：patch `build_formal_paper_daily_dependencies` 返回任意 sentinel；patch
  `quant.execution.cli.main` 抛出上述环形图；调用 `action="inspect"`。
- 必须新增的测试：上述 CLI 递归图；另测 `from quant.execution.cli import main` 失败（ImportError
  带绝对路径 marker）。断言：`FormalPaperDailyRunnerError`、code 稳定、`__cause__`/`__context__`
  为 None、marker 不出现在 str/repr/traceback；正常 `main` 返回 0/20/30 不变。
- 通过条件：将 CLI import 与 `main(...)` 移入同一 sanitizing `try`；`except FormalPaperDailyRunnerError: raise`；
  `except Exception: raise FormalPaperDailyRunnerError() from None`。不得把 CLI 的 int 退出码改写成异常。
  返工后由未参与该轮实现的外部初验复验本反例、实现者定向测试、Ruff/mypy/cold import。

### RUN0D1-R1-02（随返工补齐）：action 未做 exact `type is str`

- 现象：`_formal_paper_operator_argv` 用 `action not in _OPERATOR_ACTIONS` 做成员判断。
  `StrInspect("inspect")`（`str` 子类）会调用 deps（初验 `deps=1`）。对比：`confirm_sha256`/
  `command_id` 已用 `type(...) is not str`。
- 根因：action 路径缺少与 confirm/command 对称的 exact type 闸门。
- 应遵循规则：独立初验要求覆盖 action exact type；本项目运行时身份用 `type is` 而非 `in`/`isinstance`。
- 最小复现：`class S(str): pass`；`action=S("inspect")` + 禁止 deps/CLI 的 patch；当前会打到 deps。
- 必须新增的测试：`type(action) is not str` 的子类/bytes 在 deps/CLI 前拒绝。
- 通过条件：非法 action 一律 `FormalPaperDailyRunnerError` 且零 deps/CLI；合法六动作字符串行为不变。

## 独立对抗核对（实现者未用）

| 反例 | 结果 |
|---|---|
| action bytes/int/None/list/`INSPECT`/`inspect `/`paper-Submit`/`CANCEL` | 前置拒绝，PASS |
| action `str` 子类 | 进入 deps，见 R1-02 |
| confirm/command bytes/bytearray/int/bool/list/dict | 前置拒绝，PASS |
| 空/空白/大写 hex confirm、空白 `command_id` | wrapper 交给 CLI（确认语义 SSOT），不构成本包阻断 |
| 单次调用 deps exact once；inspect/reconcile 各一次 | PASS |
| deps 环形异常图 + marker | 脱敏且零 CLI，PASS |
| CLI 环形异常图 + marker | **泄漏，R1-01** |
| read-only inspect/plan 真 CLI；拒绝四类 dispatch；无 confirm 形参 | PASS |
| cancel 两步 challenge、错误 confirm、重复完成 | `CANCEL_COMPLETE` / `CANCEL_ALREADY_COMPLETED`，cancel_calls=1，PASS |
| UNKNOWN 后再带同一 confirm、再 challenge | 均 30，gateway 仍 1，PASS |

## 验证

Windows `D:\Miniforge3\python.exe`，`PYTHONPATH=src`；独立 `--basetemp`；不替代 WSL Gate。

| 命令 | 结果 |
|---|---|
| `pytest tests/unit/test_paper_formal_daily.py tests/unit/test_execution_cli.py -q` | `34 passed`（实现者测试绿，不能掩盖 R1-01） |
| `ruff check` 白名单三路径 | All checks passed |
| `mypy` 两生产文件 | Success: no issues found |
| cold import `run_formal_paper_daily_operator` | `FORMAL_DAILY_LAZY_IMPORT_PASS` |
| 初验对抗探针 | 合同表所列；CLI 图脱敏 **FAIL** |

## 结论

**FAIL** — 参数矩阵、一次 deps、read-only 兼容、challenge/幂等、UNKNOWN 零重发在 Windows 定向证据下成立，
但公开 operator 未闭合 CLI 边界脱敏。本轮**只解锁返工，不解锁主验**。
回滚仍是丢弃白名单实现 + 交付报告；本报告不改变生产状态。
