# M1 HK-HISTORY-R4：Plan 公共边界递归异常脱敏返工任务单

日期：2026-08-11  
状态：**实现、全新外部独立复验与主 Agent 最终验收均已通过；不解锁 licensed 01065/HK60/M1/ext4 Gate**  
交付报告：[`M1_HK-HISTORY-R4_Plan公共边界递归异常脱敏返工交付报告.md`](M1_HK-HISTORY-R4_Plan公共边界递归异常脱敏返工交付报告.md)

## 1. 返工原因与不变量

R3 独立初验确认 recover/evidence/seed 路径已经关闭 R2 的异常图泄漏，但三个 v2 plan 公共入口仍会让
`RuntimeError` 及其递归 `__context__` 原样越过边界：

- `build_hk_history_plan_v2`
- `load_hk_history_plan`
- `write_or_verify_plan`

同一业务失败不得因为从不同 public API 进入而改变脱敏强度。所有相关失败必须在退出 active `except` handler
后抛既有稳定码，且 `__cause__`、`__context__` 均为 `None`；异常对象图、traceback 和 repr 不得保留 hostile marker、
供应商文本或绝对路径。

## 2. 精确实现要求

1. 三个入口采用与已通过复验的 recover/evidence 路径相同的 failure-flag/finalize 模式：在 handler 内只记录内部
   失败分类，退出 handler 后统一 `raise HKHistoryBackfillError(stable_code) from None`。
2. 捕获所有会从依赖、路径、JSON、规范化和验证逻辑逸出的 `Exception`；不得只扩充一两个异常类型。
3. 保留既有错误分类，不得把所有 plan conflict、reference invalid、source invalid 等压成一个通用码。
4. 成功路径的 canonical bytes、identity、journal/receipt、no-clobber/replay 与零网络语义不得改变。
5. 不修改 public API、Schema、配置、正式数据、scheduler 或其他 M1 模块。

## 3. 必须新增的正式回归

对三个入口分别注入至少一个实现者此前未覆盖的 `RuntimeError(MARKER + abs_path) from ValueError(MARKER)`：

1. `load_hk_history_plan`：hostile `Path.read_bytes`。
2. `build_hk_history_plan_v2`：hostile `_normalize_expected_dates` 或同级内部依赖。
3. `write_or_verify_plan`：既有 plan/冲突路径上的 hostile read/verify。

每例必须断言：

- exact 既有稳定错误码；
- `__cause__ is None`、`__context__ is None`；
- 递归遍历异常图与 `traceback.format_exception` 均不含 marker、绝对路径或原始 hostile 文本；
- 正常 plan build/load/write-or-verify 控制组仍通过。

同时保留 R3 recover/evidence hostile 回归与 R2 的 ABSENT replay、bar∩no-trade、01065、closure 重签、inode
绑定、attempts 预植、零网络/零 clean 反例。

## 4. 文件白名单

只允许修改：

- `src/quant/data/hk_history_backfill.py`
- `tests/unit/test_hk_history_backfill.py`
- 本任务单状态行
- 唯一交付报告 `docs/framework/agent/M1_HK-HISTORY-R4_Plan公共边界递归异常脱敏返工交付报告.md`

禁止修改 R2/R3 历史报告、其他生产模块、其他测试、正式 `data/`、journal、scheduler、配置和路线图；不得联网、
`git add` 或 commit。

## 5. 验证与交付

- Windows：两份 history 定向测试、Ruff、mypy、cold import、scoped diff check。
- WSL Miniforge `base`：同一测试与静态检查；`/mnt/f` 只能写作 DrvFS 兼容证据，不是 ext4 Gate。
- 交付后必须由未参与 R4 实现的全新外部 Agent 独立复验；初验 PASS 后才允许主 Agent 最终验收。

## 6. 停止条件

若保持既有错误分类需要修改公共错误码、Schema、其他模块或事实语义，立即停止并提交脱敏证据，不得自行扩大范围。
