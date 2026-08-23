# M3 G1 P0 返工 A/B/C 实现交付报告

- 日期：2026-07-26
- 分支：`cursor/g1-p0-rework-20260726`
- 角色：外部实现 Agent（`cursor-grok-4.5-high`）
- **不宣称** Codex 终验 / Linux Gate / 正式 publish 通过

## 1. 改动摘要

### A — reconciliation fail-closed（B2C §9.2）

`src/quant/data/m3_execution_facts.py`：

- 无事件：仅 `abs(actual_factor_ratio-1)<=rtol` 才写 `NO_EVENT_STABLE_FACTOR`；否则 `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`。
- 有事件失败路径（缺前收、分母非法、actual/declared/market ≤1、PARTIAL/无 FULL_DAY 缺 daily、market/declared 均超 rtol）一律 raise，**不再**回退 `event_count=0` / `NO_EVENT_STABLE_FACTOR`。
- 删除“actual≈1 时清空 events”的伪装稳定路径。
- verifier 对 `NO_EVENT_STABLE_FACTOR` 增补 rtol / event_count 闭合检查。
- 未引入配股/增发等新事件源。

### B — candidate membership/eligible 权威重建

`src/quant/data/m3_g1_candidate.py`：

- 废止 audit 以 `count∈[1,300]` 为充分条件。
- audit 调用 `index_membership.build_observed_membership`，入参来自 candidate 的 observations/calendars/instruments、固定 universe、`signal_start/signal_end`、`expected_constituent_count=300`。
- 重建 membership / eligible_keys 与 candidate **逐字段相等** + content digest；不等则 `MEMBERSHIP_COUNT_MISMATCH`。
- 对抗：`eligible_keys.head(1)` 同步 digests/primary → 失败；单删非生命周期成员 → 失败；人工 299 → 失败。真实 299 仅当 builder 精确产出时可通过。

### C — 方法版本升级 + Windows PUBLISH 叙述

版本（相对已验收 v1，保留新语义故 bump）：

| 常量 | 新值 |
|---|---|
| `G1_PRICE_LIMIT_METHOD_VERSION` | `tushare_stk_limit_suspension_aware_v2` |
| `G1_CORPORATE_ACTION_SELECTION_VERSION` | `tushare_dividend_implemented_latest_v2` |
| `G1_CORPORATE_ACTION_RECONCILIATION_VERSION` | `tushare_factor_daily_preclose_v2` |

贯穿：`m3_execution_facts` 定义 → `m3_g1_candidate` / `g1_planning` 引用常量 → 单测断言。未为保 key 保留错误 v1。

#### Windows PUBLISH 实现要点（已存在于 `m3_release.py`，本轮补测试静态闭包）

1. **独占目录提交**：`os.name == "nt"` 时 `_renameat2_noreplace` → `_windows_movefileex_noreplace`，调用 `MoveFileExW(src, dst, flags=0)`；目标已存在映射 `ERROR_ALREADY_EXISTS(183)` / `ERROR_FILE_EXISTS(80)` → `G1_RELEASE_CONCURRENT_PUBLISH`。禁止 `os.rename` / `os.replace` 回退。
2. **二进制写入**：`_exclusive_write_bytes` flags 含 `os.O_BINARY`（及 `O_CREAT|O_EXCL|O_WRONLY|O_NOFOLLOW`），避免 Windows 文本模式破坏 parquet/json。
3. **目录 fsync**：`_fsync_directory` 在 Windows 上仅校验路径为目录后返回（NTFS 无可靠 directory-fd fsync）；文件侧已在写入后 `os.fsync`。
4. **宣称边界**：Windows 轨产物不冒充 Linux/ext4 Gate；Linux `renameat2(RENAME_NOREPLACE)` 路径未改。

`test_m3_g1_release.py` 静态断言补强：`MoveFileExW` / `_windows_movefileex_noreplace` / `O_BINARY` / `_exclusive_write_bytes` / `_fsync_directory`。

## 2. 自验结果

```text
tests/unit/test_m3_execution_facts.py  → 57 passed
tests/unit/test_m3_g1_candidate.py     → 37 passed
tests/unit/test_m3_g1_release.py       → 29 passed, 2 failed（环境既有限制，见下）
定向 ruff：修复 signal_sessions 未使用后通过
定向 mypy：m3_execution_facts.py + m3_g1_candidate.py → Success
git diff --check（白名单改动）：通过
```

### release 两项失败（非本轮语义回归）

- `test_extra_hidden_and_fifo_rejected`：`os.mkfifo` 在 Windows 不存在。
- `test_symlink_and_hardlink_rejected`：当前会话无创建 symlink 特权（WinError 1314）。

二者为 Windows 宿主能力限制；no-clobber / MoveFileEx / 静态二进制路径断言已通过。未宣称 Linux Gate。

## 3. 已知剩余风险 / 正式数据首败可能

1. **恢复 fail-closed 后**，原被伪装成 `NO_EVENT_STABLE_FACTOR` 的无 dividend 因子跳变（配股/增发等）将在 PREPARE/reconciliation 显式失败；正式 CSI300 history 若存在此类日，预期首败于 `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`，应保留首败证据，**不得**扩大事件源。
2. **方法版本 bump** 必然改变 build/plan/candidate identity；旧 release `3c9bda84…` 不可复用；需协调者按合同零网络 HISTORY → 有界 REFERENCE → PREPARE → Windows PUBLISH。
3. membership audit 每次权威重建增加 CPU；单测变慢属预期，非功能缺陷。
4. 本报告**不是**独立初验，也不是 Codex 终验。

## 4. 改动文件列表（白名单）

- `src/quant/data/m3_execution_facts.py`
- `src/quant/data/m3_g1_candidate.py`
- `tests/unit/test_m3_execution_facts.py`
- `tests/unit/test_m3_g1_candidate.py`
- `tests/unit/test_m3_g1_release.py`
- `docs/framework/agent/M3_G1_P0返工_A_B_C实现交付报告.md`（本文件）

未改无关 CRLF 脏 docs；未跑正式 `run_g1` publish/reference。
