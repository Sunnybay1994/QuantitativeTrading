# M3 G1-P2 B3：独立初验 P1-1 一次返工独立复验报告

日期：2026-07-14  
角色：**外部独立复验 Agent**（从未参与原实现或本轮返工）  
实际模型标识：`cursor-grok-4.5-high`  
返工任务：[`M3_G1_P2_B3PIT成员状态初验一次返工任务单.md`](M3_G1_P2_B3PIT成员状态初验一次返工任务单.md)  
返工交付：[`M3_G1_P2_B3PIT成员状态初验一次返工交付报告.md`](M3_G1_P2_B3PIT成员状态初验一次返工交付报告.md)  
不通过证据：[`M3_G1_P2_B3PIT成员状态独立初验报告.md`](M3_G1_P2_B3PIT成员状态独立初验报告.md)  
原任务书：[`M3_G1_P2_B3PIT成员状态外部闭环任务单.md`](M3_G1_P2_B3PIT成员状态外部闭环任务单.md)

## 结论

**一次返工独立复验通过，可交主 Agent 终验。**

本报告不宣称 B3 / P2 / G1 / Gate 完成。唯一仓库写入为本报告；未修改生产代码、Schema、配置、实现者测试、原报告或任务书；未联网、未读 token、未访问 `_old/`。临时对抗脚本仅位于 WSL `/tmp/b3_p1_reverify.py`，验收后已清理。

---

## 1. 返工范围与源码核对

| 检查项 | 证据 | 结果 |
|---|---|---|
| 允许修改文件 | `index_membership.py`、`test_index_membership.py`、本轮交付报告 | 与任务单 §3 一致 |
| 禁止越权 | 未改 `m3_identity.py`、领域 Schema、包根导出、配置、路线图、Gate | 只读核对通过 |
| `__post_init__` write-back | 先验证三表 → `object.__setattr__` 写回 → 仅对公开 frame 重算 digest 比较 | 与任务单 §2/交付 §2 一致 |
| eligible 规范化 | `_validate_eligible_frame` 对可 coercion 的 `as_of`/`symbol` cast；List/Struct fail-closed | 与交付说明一致 |
| 冻结设计 | 成功构造并规范化写回（非拒绝可合法 coercion 输入） | 对抗 R1–R8 证实 |

---

## 2. P1-1 独立对抗（不同于实现者精确样例）

主 fixture：**2024-05/06/07**（`20240531` Fri → `20240603` Mon as_of），非实现者 `_fri_mon_fixture`（2016-01-29）。列组合与不可 coercion 形状亦与实现者回归不同。

| ID | 要点（相对实现者差异） | 结果 |
|---|---|---|
| R1 | observations：`observation_date`+`weight` 同时 Utf8；公开 dtype→Date/Float64；digest 闭合 | **PASS** |
| R2 | membership：仅 `effective_from` Utf8（实现者双列） | **PASS** |
| R3 | membership：仅 `effective_to` Utf8 | **PASS** |
| R4 | eligible：`as_of` Utf8 → Date；digest 闭合 | **PASS** |
| R5 | 三表同时混合 coercion（obs 双列 Utf8 + mem 仅 to + elig as_of） | **PASS**（逐表 obs/mem/elig 重算==公开 digest） |
| R6 | happy-path 三表公开 frame / 公开 digest / 重算闭合 | **PASS** |
| R7a | Struct `observation_date` 拒绝；`__cause__ is None` | **PASS** |
| R7b | List `effective_to` 拒绝（`INTERVAL_INVALID`）；无泄露 | **PASS** |
| R7c | Struct `as_of` 拒绝；无泄露 | **PASS** |
| R8 | 原初验 P1-1 探针变体（Utf8 date + coerced digest，2024 窗口） | **PASS**（Date 写回且 digest==exposed） |

**逐表闭合证明（R5/R6）：** 对 `index_constituent_observation` / `universe_membership` / `eligible_keys` 分别调用 `clean_table_content_sha256(公开 frame)`，均等于对应公开 `*_sha256`；公开日期列为 `pl.Date`。

---

## 3. 原初验 C1–C10 中 identity / Schema / result 相关变体

在 2024 主窗口（及 C9 的 2018-03 对照窗口）复跑，数据与组合未复用实现者/原初验精确用例。

| ID | 类别 | 结果 |
|---|---|---|
| C1a/b/c | receipt_sha / frame 漂移；错误 digest 构造拒绝 | **PASS** |
| C4a/b | Utf8 weight 可 coercion 并消费；List weight 拒绝 | **PASS** |
| C8a–d | `-0.0/0.0`、hex64、datetime 拒绝、重复行敏感 | **PASS** |
| C9a–d | 单 frame/单 hash 错配；跨窗口合法表混入后 verify 拒绝；happy verify | **PASS** |
| C10a/b | 恶意 symbol/universe 路径与 token marker；`str`/`repr`/`cause` 无泄露 | **PASS** |
| PIT smoke | Fri 2024-05-31 无 as_of；Mon 2024-06-03 有 | **PASS** |

对抗合计：**26 PASS / 0 FAIL**。

未将 C2/C3/C5/C6/C7（跳月/跨 response 重复键/周五调仓细节/退市重入/warmup）整段重跑——按返工任务 §5，本轮聚焦 **identity/Schema/result** 相关变体与 P1-1 闭合；上述类别已在原初验通过，且本轮全量回归未退化。

---

## 4. WSL 验证命令（Miniforge `base`，`/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`）

| 命令 | 结果 |
|---|---|
| 定向 pytest（membership/identity/backfill/mappers） | **168 passed** |
| 全量 `pytest -q` | **562 passed**（既有 Pandera/Polars deprecation warnings） |
| `ruff check src tests` | All checks passed |
| `mypy src` | Success: no issues found in 75 source files |
| 独立对抗 `/tmp/b3_p1_reverify.py` | **26 PASS / 0 FAIL** |

未使用 Windows Python/conda 跑项目测试。

---

## 5. 非阻断观察（不作为本轮否决）

- eligible 无独立领域 Schema，规范化在 `_validate_eligible_frame` 内完成；与返工交付边界说明一致，未复制 Schema SSOT。
- membership 不可 coercion 路径稳定映射为 `G1_MEMBERSHIP_INTERVAL_INVALID`（与实现者非 coercible 回归约定一致）。
- Polars `String→Date` cast deprecation 警告存在于 coercion 路径；不影响本轮 P1-1 闭合判定。

---

## 6. 裁决与下一步

**一次返工独立复验通过。**

P1-1 已关闭：成功构造的 `ObservedMembershipResult` 对三张表均消费 validator 返回 frame 并写回；公开 frame 的重算 digest 与公开 digest 字段立即相等；不可 coercion 输入继续 fail-closed 且无敏感泄露。

请主 Agent 执行第 4 步终验。复验 Agent **不得**更新路线图或宣称 P2 / G1 / Gate 通过。
