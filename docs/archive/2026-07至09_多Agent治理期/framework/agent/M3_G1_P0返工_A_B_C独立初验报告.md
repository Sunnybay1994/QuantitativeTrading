# M3 G1 P0 返工 A/B/C 独立初验报告

- 日期：2026-07-27
- 角色：外部**独立初验** Agent（全新会话，未参与实现；模型 `cursor-grok-4.5-high`）
- 分支：`cursor/g1-p0-rework-20260726`
- 实现 commit：`d952cc99b99b68d2c5cadb41d05aa0d152d73840`
- 依据：冻结任务书、实现交付报告、Codex 裁定、B2C §9.2（均只读）
- **结论：通过**
- **本报告不等于 Codex 终验 / Linux Gate / 正式 publish 通过**

---

## 1. 合同对照只读审查（相对 d952cc9）

### A — reconciliation fail-closed（B2C §9.2）

| 合同点 | 代码事实 | 判定 |
|---|---|---|
| 无事件：仅 `abs(actual-1)<=rtol` → `NO_EVENT_STABLE_FACTOR`，否则 `FACTOR_UNEXPLAINED` | `_no_event_evidence_row` 在 `abs(actual-1)>rtol` 时直接 raise `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`；verifier 增补 rtol / `event_count==0` 闭合 | 成立 |
| 有事件失败路径不得回退 `event_count=0` / 伪装 `NO_EVENT_STABLE_FACTOR` | 删除“actual≈1 清空 events”与多处 `_no_event_evidence_row` 回退；缺前收/分母非法/ratio≤1/缺 daily 非 FULL_DAY/双路径超 rtol 一律 raise | 成立 |
| 禁止把未知资本事件装成稳定无事件 | 未引入配股/增发新事件源；无事件 jump 显式失败 | 成立 |

**缺口：** 无合同级缺口。正式 CSI300 上无 dividend 的因子跳变将首败于 `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`（实现交付已声明，属预期 fail-closed，非本初验否决项）。

### B — membership/eligible 权威重建

| 合同点 | 代码事实 | 判定 |
|---|---|---|
| 废止 `count∈[1,300]` 充分条件 | `audit_g1_candidate` 已删除按 session 数数门禁 | 成立 |
| 调用 `build_observed_membership`，入参来自 candidate + `expected_constituent_count=300` | `observations/calendars/instruments/universe/signal_start/signal_end` 齐全 | 成立 |
| 重建结果与 candidate 逐字段相等 + digest | `_frames_equal` + digest 双检；不等记 `MEMBERSHIP_COUNT_MISMATCH` | 成立 |
| 真实 299 仅当 builder 精确产出 | 人工裁剪 membership/eligible 无法通过权威重建比对 | 成立（独立探针 B 证实） |

**缺口：** 无合同级缺口。备注：失败码统一为 `MEMBERSHIP_COUNT_MISMATCH`（含 frame/digest 不等），命名偏窄但属 MEMBERSHIP 类，满足任务书“含 MEMBERSHIP 类失败”。

### C — 版本 v2 + Windows PUBLISH 职责闭包

| 合同点 | 代码事实 | 判定 |
|---|---|---|
| 三常量 bump 至 v2 且贯穿 | `m3_execution_facts` 定义 v2；`m3_g1_candidate` / `g1_planning` 引用常量写入 build_spec；单测断言 v2；无保留错误 v1 | 成立 |
| Windows PUBLISH（见 §4） | `m3_release.py` 既有路径与任务书一致；本轮补静态测试闭包 | 成立 |

**缺口：** 无合同级缺口。方法版本不在 YAML config 字面量中硬编码（由代码常量注入 plan/candidate），与现有架构一致，不构成返工项。

---

## 2. 定向 pytest（只读重跑）

命令：

```text
set PYTHONPATH=F:\AI_Coding\QuantitativeTrading\src
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_execution_facts.py tests/unit/test_m3_g1_candidate.py tests/unit/test_m3_g1_release.py -q --tb=line
```

结果（本机实测）：

```text
2 failed, 123 passed, 1046285 warnings in 3432.35s (0:57:12)
```

| 失败用例 | 现象 | 归类 |
|---|---|---|
| `test_extra_hidden_and_fifo_rejected` | `AttributeError: module 'os' has no attribute 'mkfifo'` | **宿主能力**：Windows 无 `os.mkfifo`，非本轮 P0 语义回归 |
| `test_symlink_and_hardlink_rejected` | `OSError: [WinError 1314]` 无创建 symlink 特权 | **宿主能力**：会话无 symlink 特权，非产品缺陷 |

语义相关用例（execution_facts / candidate / release 静态与 no-clobber 路径）均通过。与实现交付报告一致。

---

## 3. 两个 P0 对抗探针（独立构造，非复述实现者测试名）

探针脚本（仅诊断产物）：

- `artifacts/g1_component_diag_20260722/p0_indep_probe_a_reconciliation.py`
- `artifacts/g1_component_diag_20260722/p0_indep_probe_b_membership_audit.py`

### 探针 A — reconciliation

命令：

```text
$env:PYTHONPATH='F:\AI_Coding\QuantitativeTrading\src'
D:\Miniforge3\python.exe artifacts\g1_component_diag_20260722\p0_indep_probe_a_reconciliation.py
```

构造路径摘要（自建，符号 `600519.SH`、日期 2026-03-02..06，hex=`b*64`）：

1. **A1** 无 dividend ledger + D0→D1 factor 跳至 1.5 → 必须 `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`
2. **A2** 有现金分红事件，但 actual=1.5 相对 declared/market≈1.0101 双路径超 rtol → raise，不得落到 `NO_EVENT_STABLE_FACTOR`
3. **A3** 有事件、缺 ex-date daily、`PARTIAL` 停牌 → raise，不得落到 `NO_EVENT_STABLE_FACTOR`

结果：`PROBE_A_ALL_PASS`（exit 0）

### 探针 B — membership audit

命令：

```text
$env:PYTHONPATH='F:\AI_Coding\QuantitativeTrading\src'
D:\Miniforge3\python.exe artifacts\g1_component_diag_20260722\p0_indep_probe_b_membership_audit.py
```

构造路径摘要（探针内自建 300 成分 CSI300 输入 → `build_g1_candidate`；config_version=`m3-g1-indep-probe-v1`）：

1. **B0** baseline `audit_g1_candidate` → `passed=True`，`eligible_keys.height=300`
2. **B1** `eligible_keys.head(1)`，同步 table digests / required digest / `primary_candidate_key` 后 audit → `passed=False`，含 `MEMBERSHIP_COUNT_MISMATCH`
3. **B2** 同步删除 membership+eligible 中非生命周期成员 `000001.SZ` → `passed=False`，含 MEMBERSHIP 类失败

结果：`PROBE_B_ALL_PASS`（exit 0，约 53s）

---

## 4. Windows PUBLISH 独立核对（只读 `m3_release.py`）

| 检查项 | 结论 |
|---|---|
| `MoveFileExW(..., flags=0)` | 成立（`_windows_movefileex_noreplace`） |
| `_exclusive_write_bytes` 含 `O_BINARY` | 成立 |
| Windows `_fsync_directory` 仅校验目录后 return（跳过 dir-fd fsync） | 成立 |
| `m3_release.py` 内无 `os.rename(` / `os.replace(` 回退 | 成立（计数 0） |
| 非 Windows 仍走 `libc.renameat2(..., RENAME_NOREPLACE)` | 成立 |
| 目标已存在 → `G1_RELEASE_CONCURRENT_PUBLISH`（80/183） | 成立 |

**宣称边界：** 以上仅为 Windows 轨实现与静态路径核对，**不冒充** Linux/ext4 Gate，也不等于正式 PUBLISH 现场通过。

---

## 5. 初验结论

### 通过

A/B/C 合同点在 `d952cc9` 上成立；独立对抗探针 A/B 通过；定向 pytest 除 2 项 Windows 宿主能力限制外全部通过。

### 明确不是

- 不是 Codex 终验
- 不是 Linux Gate
- 不是正式 HISTORY/REFERENCE/PREPARE/PUBLISH 现场验收

### 返工项

无。

### 协调者后续（非本初验范围）

按冻结任务书：零网络 status →（key 变则隔离旧 baostock journal）有界 REFERENCE → PREPARE → Windows PUBLISH → 磁盘 `verify_g1_release` → 更新 handoff/总览（仍不宣称 Linux Gate）。
