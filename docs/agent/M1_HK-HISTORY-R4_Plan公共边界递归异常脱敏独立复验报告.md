# M1 HK-HISTORY-R4：Plan 公共边界递归异常脱敏独立复验报告

日期：2026-08-11（Asia/Shanghai）  
角色：未参与本轮实现的全新外部 Cursor 独立初验 Agent（`cursor-grok-4.5-high`）  
任务单：[`M1_HK-HISTORY-R4_Plan公共边界递归异常脱敏返工任务单.md`](M1_HK-HISTORY-R4_Plan公共边界递归异常脱敏返工任务单.md)  
交付报告：[`M1_HK-HISTORY-R4_Plan公共边界递归异常脱敏返工交付报告.md`](M1_HK-HISTORY-R4_Plan公共边界递归异常脱敏返工交付报告.md)  
前置 FAIL：[`M1_HK-HISTORY-R3_递归异常图脱敏独立复验报告.md`](M1_HK-HISTORY-R3_递归异常图脱敏独立复验报告.md) §3 F1  

结论：**PASS**

本 PASS/FAIL 仅面向主 Agent 合同复验；**不解锁**正式 HK60 / licensed `01065` / M1 / ext4 Gate。

## 1. 范围与只读边界

- 只读核对：任务单、R3 FAIL 报告、R4 交付报告、`src/quant/data/hk_history_backfill.py`、`tests/unit/test_hk_history_backfill.py`。
- 唯一写入：本报告。未改生产代码/测试/任务单/既有报告；未 `git add/commit`；未联网；未触正式 `data/`/journal/clean。
- 验证环境：Windows `D:\Miniforge3\python.exe`；WSL Miniforge `base` 于 `/mnt/f`（**DrvFS，非 ext4**）。

## 2. 合同映射（摘要）

| 冻结项 | 独立核对 |
|---|---|
| R3 F1 原样重放：`load` / `build` / `write_or_verify` + `RuntimeError←ValueError` | **PASS**：exact `HK_HISTORY_PLAN_CONFLICT` / `HK_HISTORY_REFERENCE_INVALID` / `HK_HISTORY_PLAN_CONFLICT`；`__cause__`/`__context__` 均为 `None`；walk+`format_exception` 无 marker/path（正式单测 + 独立 A1–A3） |
| 宽捕获 + failure-flag/finalize（handler 外 `raise ... from None`） | **PASS**：三入口源码均为 `except Exception` 记码后出 handler 再抛 |
| 既有错误分类不漂移 | **PASS**：build→`REFERENCE_INVALID`；load/write→`PLAN_CONFLICT`；既有 `HKHistoryBackfillError` 码不互相吞并（独立 B7） |
| recover / evidence hostile 不回归 | **PASS**：正式节点 + 独立 C1/C2 |
| R2 语义（ABSENT replay / bar∩no-trade / 01065 / 重签 / hardlink inode / attempts 预植 / 零网络零 clean） | **PASS**：聚焦 18 passed |
| canonical plan write/load/replay + conflict 分类 | **PASS**：独立 D1 |
| 实现者未用的异常类型 / 递归图 / traceback 反例 | **PASS**：独立 B1–B6（见 §4） |
| Windows + WSL DrvFS 定向 pytest / Ruff / mypy / cold import | **PASS**（见 §5）；WSL `git diff --check` 因 worktree gitdir 路径在 DrvFS 不可用，改以 Windows scoped check 为准 |

## 3. FAIL 项

无。

## 4. 独立对抗反例（实现者未用）

实现者正式回归仅覆盖 `RuntimeError←ValueError` + `Path.read_bytes` / `_normalize_expected_dates`。本轮额外注入：

| 反例 | 结果 |
|---|---|
| A1–A3：R3 F1 精确重放（三入口 RuntimeError←ValueError） | **PASS** |
| B1：`load` ← `_strict_json` → `OSError←KeyError` | **PASS** → `PLAN_CONFLICT` |
| B2：`build` ← `_serialize_plan_values` → 三级 `TypeError←LookupError←AttributeError` | **PASS** → `REFERENCE_INVALID` |
| B3：`write` 创建路径 ← `_write_once` → `ConnectionError←PermissionError` + `__notes__` 含 marker/path | **PASS** → `PLAN_CONFLICT`；notes 亦不泄漏 |
| B4：`load` ← `_plan_from_dict` → 单节点 `MemoryError` | **PASS** → `PLAN_CONFLICT` |
| B5：`build` ← `_make_request` → 隐式 `__context__`（except 内无 `from`） | **PASS** → `REFERENCE_INVALID` |
| B6：`write` 既有 plan ← `BrokenPipeError←UnicodeDecodeError` | **PASS** → `PLAN_CONFLICT` |
| B7：`load` 内既有 `HKHistoryBackfillError("HK_HISTORY_RAW_INVALID")` 不被吞成 `PLAN_CONFLICT` | **PASS** |
| C1/C2：recover / evidence 同构 RuntimeError 图 | **PASS** |
| D1：canonical write/load/replay + 坏 JSON 仍 `PLAN_CONFLICT` | **PASS** |

脚本仅落系统临时目录，不入仓库。Windows 与 WSL DrvFS 各跑一遍，均为 `fails=0 total=13`。

## 5. 验证证据

### Windows 原生 Miniforge（`D:\Miniforge3\python.exe`）

```text
PYTHONPATH=<worktree>/src
pytest tests/unit/test_hk_history_backfill.py tests/unit/test_backfill_hk_history.py -q -p no:cacheprovider
→ 150 passed, 2 skipped

聚焦 hostile + R2 语义节点 → 18 passed

独立对抗脚本 → 13 PASS

ruff check src/quant/data/hk_history_backfill.py tests/unit/test_hk_history_backfill.py
→ All checks passed!

mypy src/quant/data/hk_history_backfill.py
→ Success: no issues found in 1 source file

cold import → <worktree>\src\quant\data\hk_history_backfill.py
git diff --check -- src/quant/data/hk_history_backfill.py tests/unit/test_hk_history_backfill.py → pass
```

### WSL Miniforge `base`（**DrvFS** `/mnt/f`，**非 ext4**）

```text
findmnt -T <worktree> → FSTYPE=drvfs
pytest 同组 → 152 passed
聚焦节点 → 18 passed
独立对抗脚本 → 13 PASS
ruff / mypy / cold import → pass
git diff --check：DrvFS 上 worktree gitdir 解析失败（非测试失败）；以 Windows scoped check 为准
```

不得将本 DrvFS 绿测表述为 ext4 Gate。

## 6. 已确认通过的子集

- R3 F1 在 **v2 `build_hk_history_plan_v2` / `load_hk_history_plan` / `write_or_verify_plan`** 上已对齐 recover/evidence 的 failure-flag 模式；正式 hostile 单测与独立 R3 重放/扩展反例均绿。
- recover/evidence、journal/receipt 相关 R2 语义、canonical plan 与错误分类未见回归。
- 生产/测试改动文件名落在任务白名单核心集（`hk_history_backfill.py` + 对应单测）；本轮未审查并行脏工作区其他模块为 R4 范围。

## 7. 结论

**PASS** — 可进入主 Agent 最终验收。本报告不授权正式 HK60/M1/ext4 Gate 推进；DrvFS 绿测不得升格为 ext4 Gate。
