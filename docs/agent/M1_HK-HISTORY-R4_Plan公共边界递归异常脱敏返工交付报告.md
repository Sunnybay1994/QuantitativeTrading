# M1 HK-HISTORY-R4：Plan 公共边界递归异常脱敏返工交付报告

日期：2026-08-11（Asia/Shanghai）  
角色：全新外部 Cursor 实现 Agent（`cursor-grok-4.5-high`）  
任务单：[`M1_HK-HISTORY-R4_Plan公共边界递归异常脱敏返工任务单.md`](M1_HK-HISTORY-R4_Plan公共边界递归异常脱敏返工任务单.md)  
前置 FAIL：[`M1_HK-HISTORY-R3_递归异常图脱敏独立复验报告.md`](M1_HK-HISTORY-R3_递归异常图脱敏独立复验报告.md) §3 F1

状态：**实现自测完成；未宣称独立初验 / 主验 / M1 Gate**

## 1. 变更摘要

对齐已通过复验的 recover/evidence failure-flag 模式：`build_hk_history_plan_v2`、`load_hk_history_plan`、`write_or_verify_plan` 对任意 `Exception` 先记录内部失败分类，退出 active `except` handler 后统一 `raise HKHistoryBackfillError(stable_code) from None`，使 public 失败的 `__cause__` 与 `__context__` 均为 `None`，递归异常图 / traceback / repr 不含 hostile marker、供应商原文或绝对路径。

保留既有错误分类：`build` → `HK_HISTORY_REFERENCE_INVALID`；`load` / `write_or_verify` → `HK_HISTORY_PLAN_CONFLICT`；既有 `HKHistoryBackfillError` 码不互相吞并。成功路径的 canonical bytes、identity、journal/receipt、no-clobber/replay 与零网络语义未改。未触碰正式 `data/` / journal / clean；未联网；未 `git add` / commit。

## 2. 白名单改动

| 路径 | 作用 |
|---|---|
| `src/quant/data/hk_history_backfill.py` | 三入口宽捕获 `Exception` + failure-flag 后抛出 |
| `tests/unit/test_hk_history_backfill.py` | 三入口 hostile RuntimeError←ValueError 正式回归 + 控制组 |
| 任务单状态行 | 更新为实现自测完成 |
| 本报告 | 唯一交付报告 |

## 3. 新增正式回归（对照任务 §3）

1. `test_load_hk_history_plan_sanitizes_hostile_read_exception_graph`：hostile `Path.read_bytes` → exact `HK_HISTORY_PLAN_CONFLICT`；cause/context 空；walk+`format_exception` 无 marker/path；前置正常 load 控制组通过。
2. `test_build_hk_history_plan_v2_sanitizes_hostile_normalize_exception_graph`：hostile `_normalize_expected_dates` → exact `HK_HISTORY_REFERENCE_INVALID`；同级脱敏；前置正常 build 控制组通过。
3. `test_write_or_verify_plan_sanitizes_hostile_read_exception_graph`：既有 plan 上 hostile read → exact `HK_HISTORY_PLAN_CONFLICT`；同级脱敏；前置 write/replay/load 控制组通过。

断言均复用 `_assert_sanitized_exception`（递归 `__cause__`/`__context__` + traceback）。R3 recover/evidence hostile 与 R2 ABSENT replay、bar∩no-trade、01065、closure 重签、inode 绑定、attempts 预植、零网络/零 clean 回归保留并通过。

## 4. 验证摘要

### Windows 原生 Miniforge（`D:\Miniforge3\python.exe`）

```text
PYTHONPATH=<worktree>/src
pytest tests/unit/test_hk_history_backfill.py tests/unit/test_backfill_hk_history.py -q -p no:cacheprovider
→ 150 passed, 2 skipped

聚焦 hostile + R2 语义节点 → 35 passed

ruff check src/quant/data/hk_history_backfill.py tests/unit/test_hk_history_backfill.py
→ All checks passed!

mypy src/quant/data/hk_history_backfill.py
→ Success: no issues found in 1 source file

cold import → <worktree>\src\quant\data\hk_history_backfill.py
git diff --check -- 白名单源码/测试 → pass
```

### WSL Miniforge `base`（**DrvFS** `/mnt/f`，**非 ext4**）

```text
findmnt -T <worktree> → FSTYPE=drvfs
pytest 同组 → 152 passed
ruff / mypy / cold import → pass
```

不得将本 DrvFS 绿测表述为 ext4 Gate。

## 5. 边界

- 未宣称独立初验、主验、正式 HK60、licensed `01065`、M1 或 ext4 Gate。
- 本包仅修复 R3 F1：v2 plan/load/write_or_verify 公共边界递归异常图脱敏。
- 下一步：未参与本轮实现的全新 `cursor-grok-4.5-high` 会话独立复验；PASS 后仍须主 Agent 终验。
