# M1 HK-HISTORY-R3：递归异常图脱敏独立复验报告

日期：2026-08-11（Asia/Shanghai）  
角色：未参与本轮实现的全新外部 Cursor 独立初验 Agent（`cursor-grok-4.5-high`）  
任务单：[`M1_HK-HISTORY-R3_递归异常图脱敏返工任务单.md`](M1_HK-HISTORY-R3_递归异常图脱敏返工任务单.md)  
交付报告：[`M1_HK-HISTORY-R3_递归异常图脱敏返工交付报告.md`](M1_HK-HISTORY-R3_递归异常图脱敏返工交付报告.md)  
前置 FAIL：[`M1_HK-HISTORY-R2_无行情事实与零网络恢复独立初验报告.md`](M1_HK-HISTORY-R2_无行情事实与零网络恢复独立初验报告.md) §3 F1  

结论：**FAIL**

本 PASS/FAIL 仅面向主 Agent 合同复验；**不解锁**正式 HK60 / licensed `01065` / M1 / ext4 Gate。

## 1. 范围与只读边界

- 只读核对：任务单、R2 FAIL 报告、R3 交付报告、`src/quant/data/hk_history_backfill.py`、`tests/unit/test_hk_history_backfill.py`。
- 唯一写入：本报告。未改生产代码/测试/任务单/既有报告；未 `git add/commit`；未联网；未触正式 `data/`/journal/clean。
- 验证环境：Windows `D:\Miniforge3\python.exe`；WSL Miniforge `base` 于 `/mnt/f`（**DrvFS，非 ext4**）。

## 2. 合同映射（摘要）

| 冻结项 | 独立核对 |
|---|---|
| recover hostile `_read_anchored_path` 递归图 | **PASS**：exact `HK_HISTORY_REFERENCE_INVALID`；`__cause__`/`__context__` 均为 `None`；walk+traceback 无 marker/path（正式单测 + 独立 A6/B4） |
| evidence / seed / binding / receipt / raw 五站点分类不漂移 | **PASS**：正式 `test_recover_hostile_sites_keep_error_classification` |
| 直接 `load_hk_no_trade_evidence` hostile | **PASS**：正式单测 + 独立 B5 |
| R2 其余语义（ABSENT replay / bar∩no-trade / 01065 / 重签 / hardlink inode / attempts 预植 / 零网络零 clean） | **PASS**：正式回归绿 |
| **v2 plan / load / write_or_verify 同类脱敏** | **FAIL**（§3 F1）：`RuntimeError` 敌对递归图原样泄漏 |
| Windows + WSL DrvFS 定向 pytest / Ruff / mypy / cold import | **PASS**（见 §5）；WSL `git diff --check` 因 worktree gitdir 路径在 DrvFS 不可用，改以 Windows scoped check 为准 |

## 3. FAIL 项（现象—根因—规则—最小复现—新增测试—通过条件）

### F1. v2 `build` / `load` / `write_or_verify` plan 公共边界未对非窄异常类型做 failure-flag 脱敏

- **现象**：对 `Path.read_bytes` / `_normalize_expected_dates` 注入 `RuntimeError(MARKER + abs_path) from ValueError(MARKER)` 后：
  - `load_hk_history_plan` → **泄漏** `RuntimeError`，`__context__` 仍为含 marker 的 `ValueError`；
  - `build_hk_history_plan_v2` → **泄漏** 同一 `RuntimeError`；
  - `write_or_verify_plan` → **泄漏** 同一 `RuntimeError`。  
  对照：同注入下 `recover_existing_hk_history_requests` 与 `load_hk_no_trade_evidence` 已稳定为 public code 且 cause/context 空。
- **根因**：三处仍用窄 `except` 元组，未对齐 recover/evidence 的「任意异常 → 内部 failure 码 → handler 外 `raise ... from None`」：
  - `build_hk_history_plan_v2`：仅 `(KeyError, TypeError, ValueError)`；
  - `load_hk_history_plan`：仅 `(KeyError, OSError, TypeError, ValueError, json.JSONDecodeError)`；
  - `write_or_verify_plan`：仅 `HKHistoryBackfillError` / `OSError`。  
  `RuntimeError`（及实现者自用 `_raise_hostile_graph` 同类）不进入 failure-flag，直接穿出 public API。
- **应遵循规则**：任务单 §1/§2.2——所有相关 public 失败须在退出 active handler 后抛稳定 code；`__cause__` 与 `__context__` 均为 `None`；递归图/traceback/repr 不得含 token、供应商原文或绝对路径；须同步收紧 **v2 plan/load/recover** 与 evidence，避免同 R2 API 因入口不同而泄漏。
- **最小复现**（系统临时目录；示意）：
  1. `plan_path.write_bytes(b"{}")`；monkeypatch `Path.read_bytes`：对 `plan_path` 抛 `RuntimeError(f"{MARKER} path=/secret/...") from ValueError(MARKER)`；
  2. 调用 `load_hk_history_plan(plan_path)`；
  3. 观察到未捕获的 `RuntimeError`，且 `__context__` 含 marker（而非 `HKHistoryBackfillError("HK_HISTORY_PLAN_CONFLICT")` 且 cause/context 空）。  
  对 `build_hk_history_plan_v2`（patch `_normalize_expected_dates`）与 `write_or_verify_plan`（既有 plan + 冲突文件上 patch `read_bytes`）同构。
- **新增测试要求**（实现者当前未覆盖）：
  1. `load_hk_history_plan` / `build_hk_history_plan_v2` / `write_or_verify_plan` 各自至少一案：hostile **RuntimeError←ValueError** 递归图 → exact 稳定码（`PLAN_CONFLICT` 或 `REFERENCE_INVALID`，按既有分类），cause/context 空，walk+`format_exception` 无 marker/path；
  2. 断言不得只检查 `str(public_error)`；须递归 `__cause__`/`__context__`；
  3. 保持错误分类不漂移（不得把 plan conflict 一律吞成 reference invalid）。
- **通过条件**：上述三入口与 recover/evidence 同级脱敏；独立复验对抗脚本对 RuntimeError 图全 PASS；Windows/WSL DrvFS 定向组再绿；正式声明不得把 DrvFS 写成 ext4 Gate。

## 4. 独立对抗反例（实现者未用）

| 反例 | 结果 |
|---|---|
| R2 F1 精确复现：recover + `_read_anchored_path` RuntimeError←ValueError | **PASS** |
| `load_hk_no_trade_evidence` 同构 RuntimeError 图（对照） | **PASS** |
| `load_hk_history_plan` + RuntimeError 敌对图 | **FAIL**（§3 F1） |
| `build_hk_history_plan_v2` + RuntimeError 敌对图 | **FAIL**（§3 F1） |
| `write_or_verify_plan` + RuntimeError 敌对图 | **FAIL**（§3 F1） |
| 正式 R2 六组语义回归（ABSENT/bar∩no-trade/01065/重签/hardlink/attempts） | **PASS**（定向 pytest） |

脚本仅落系统临时目录，不入仓库。

## 5. 验证证据

### Windows 原生 Miniforge（`D:\Miniforge3\python.exe`）

```text
PYTHONPATH=<worktree>/src
pytest tests/unit/test_hk_history_backfill.py tests/unit/test_backfill_hk_history.py -q -p no:cacheprovider
→ 147 passed, 2 skipped

聚焦 hostile+R2 节点 → 15 passed

ruff check src/quant/data/hk_history_backfill.py tests/unit/test_hk_history_backfill.py → All checks passed!
mypy src/quant/data/hk_history_backfill.py → Success: no issues found in 1 source file
cold import → <worktree>\src\quant\data\hk_history_backfill.py
git diff --check -- src/quant/data/hk_history_backfill.py tests/unit/test_hk_history_backfill.py → pass
```

### WSL Miniforge `base`（**DrvFS** `/mnt/f`，**非 ext4**）

```text
findmnt -T <worktree> → FSTYPE=drvfs
pytest 同组 → 149 passed
ruff / mypy / cold import → pass
git diff --check：DrvFS 上 worktree gitdir 解析失败（非测试失败）；以 Windows scoped check 为准
```

不得将本 DrvFS 绿测表述为 ext4 Gate。

## 6. 已确认通过的子集（不升格总评）

- R2 F1 在 **recover / evidence / seed 可达路径** 上已按 finalize-v3 failure-flag 模式修复，实现者正式 hostile 单测与本轮独立复现均绿。
- journal/receipt 字节幂等、identity、零网络、无行情互斥等 R2 语义未见回归。
- 生产/测试改动文件名落在任务白名单核心集（`hk_history_backfill.py` + 对应单测）；本轮未审查并行脏工作区其他模块为 R3 范围。

## 7. 结论

**FAIL** — 阻断进入主验关闭本子项。须按 §3 F1 将 **v2 plan/load/write_or_verify** 公共边界与 recover/evidence 对齐为宽捕获 + handler 外稳定抛出，并补实现者未覆盖的 RuntimeError 递归图正式回归后，再交未参与该轮实现的外部初验复验。本报告不授权正式 HK60/M1/ext4 Gate 推进。
