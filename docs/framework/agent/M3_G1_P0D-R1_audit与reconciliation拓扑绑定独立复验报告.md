# M3 G1 P0D-R1：audit 与 reconciliation 拓扑绑定独立复验报告

- 日期：2026-07-27
- 角色：外部**独立复验** Agent（全新会话，未参与 R1 实现；模型 `cursor-grok-4.5-high`）
- 分支：`cursor/g1-p0-rework-20260726`
- 实现 commit：`1749905149cf1c0a8f138e215b7bf33287d00988`
- 依据：
  [`M3_G1_P0D-R1_audit与reconciliation拓扑绑定返工任务单.md`](M3_G1_P0D-R1_audit与reconciliation拓扑绑定返工任务单.md)、
  [`M3_G1_P0D-R1_audit与reconciliation拓扑绑定返工交付报告.md`](M3_G1_P0D-R1_audit与reconciliation拓扑绑定返工交付报告.md)、
  [`M3_G1_P0D首bar前factor发布作用域独立初验报告.md`](M3_G1_P0D首bar前factor发布作用域独立初验报告.md)（前序 FAIL / ADV3b）
- **结论：PASS**
- **本报告不等于 Codex 终验 / Linux Gate / 正式 status / G1 通过**
- 生产代码与实现者测试严格只读；唯一写入为本报告

---

## 1. 合同逐项核对（不复述交付报告）

### §2 冻结实现合同

| # | 合同点 | 证据 | 判定 |
|---|---|---|---|
| 1 | 按 `symbol,effective_date` 排序 scoped factors | `_audit_scoped_factor_reconciliation_topology`：`sort(["symbol","effective_date"])` | 成立 |
| 2 | 重建立即相邻 `(symbol, previous_factor_date, effective_date)` | 同函数 `series[index-1] → series[index]` | 成立 |
| 3 | expected key 集与 evidence 三字段 key 集精确相等 | `actual_keys != expected_keys` → mismatch | 成立 |
| 4 | 行数 `sum(max(n-1,0))` | `expected_rows` 与 `len(evidence_rows)` 比对；矩阵 5 空 evidence | 成立 |
| 5 | `actual_factor_ratio` 精确 `effective/previous`（无业务 rtol） | `actual_ratio != expected_ratio`；矩阵 4 + 复验 ADV_RATIO | 成立 |
| 6 | 失败码 `CORPORATE_ACTION_FACTOR_MISMATCH` + `scoped factor transition topology mismatch`；不抛未封装异常 | `try/except` → 稳定 issue；对抗全中该码/文案 | 成立 |
| 7 | 保留 row-formula verify、receipt lineage、bar-span、`verify_g1_candidate` | `audit_g1_candidate` 仍先调用 `verify_corporate_action_reconciliation_result`；拓扑检查附加；矩阵 7 ADV3a | 成立 |
| 8 | audit 无 `G1BuildInputs`；不把本检查推给 verify | `inspect.signature(audit_g1_candidate)=(*, candidate)` | 成立 |
| 9 | 版本保持 v3 | mapper / reconciliation / manifest 字面量未改（见 §4） | 成立 |
| 10 | 实现白名单 | commit `1749905` 仅改 candidate 源码、单测与交付报告 | 成立 |

### §4 必测矩阵（实现者用例，本轮复跑）

| 矩阵 | 用例 | 复验 |
|---|---|---|
| 1 | 删 evidence 重绑 → topology mismatch | 定向 pytest 绿 |
| 2 | previous 非立即相邻 → fail | 绿 |
| 3 | 增 schema 合法非拓扑行 → fail | 绿 |
| 4 | 改写 ratio（同步公式字段）→ topology fail，非仅 row-formula | 绿 + 独立 ADV_RATIO |
| 5 | 单 factor → 0 transition / 空 evidence 合法 | 绿 + 独立探针 |
| 6 | 停牌 mid factor 两条 transition；删任一条 fail | 绿 + 独立 ADV2 |
| 7 | ADV3a 窗外 factor → `FACTOR_INVALID`；verify `IDENTITY_MISMATCH` | 绿 |
| 8 | 合法 happy 通过；既有 no-event/membership 未回退 | 全文件 49 绿 |

---

## 2. 定向命令与退出码

环境：`D:\Miniforge3\python.exe`（Windows 反馈环，非 Linux Gate）。

```text
pytest tests/unit/test_m3_g1_candidate.py -q --tb=line
→ 49 passed, 374582 warnings in 912.29s, EXIT 0

ruff check src/quant/data/m3_g1_candidate.py tests/unit/test_m3_g1_candidate.py
→ All checks passed!, EXIT 0

mypy src/quant/data/m3_g1_candidate.py
→ Success: no issues found in 1 source file, EXIT 0

git diff --check -- \
  src/quant/data/m3_g1_candidate.py \
  tests/unit/test_m3_g1_candidate.py \
  docs/framework/agent/M3_G1_P0D-R1_audit与reconciliation拓扑绑定返工交付报告.md
→ EXIT 0
```

---

## 3. 独立对抗（实现者矩阵外）

只读探针（临时脚本，未入库；用 `_mid_halt_scoped_candidate` + `_rebind_identity`）。

### ADV1 — 保持行数，previous 指向同 symbol 非立即相邻 factor 日

| 项 | 内容 |
|---|---|
| 构造 | mid-halt 合法 base：factors `[D0,D1,D2]`，evidence 两行 `(D0→D1),(D1→D2)`；将第二行 `previous_factor_date` 改为 `D0`（跳过 `D1`），行数不变，重绑 digests/primary |
| 与实现者差异 | 矩阵 2 将 previous 改到**非 factor 日历日** `2016-01-29`；本攻击指向**同 symbol 已发布 factor 日**且非立即相邻 |
| 结果 | `audit.passed is False`；issue `CORPORATE_ACTION_FACTOR_MISMATCH` / `scoped factor transition topology mismatch`（count=2） |
| 备注 | 字面量「两行 previous 互换」在 2-edge 链上会产生 `previous==effective`，`CorporateActionReconciliationSchema` 在重绑阶段即拒绝，无法形成可 audit 的自包含 identity；合同「交换**或**指向非立即相邻」的 schema 可审计形态即本 ADV1。另测双 previous 塌缩到 `D0` 亦 mismatch |

### ADV2 — 首末 bar 间停牌 session factor；删前侧/后侧 evidence

| 项 | 内容 |
|---|---|
| 构造 | 合法 mid-halt candidate（audit 先通过）；分别删除 `(D0,D1)` 与 `(D1,D2)` 后重绑 |
| 结果 | 两侧均 `CORPORATE_ACTION_FACTOR_MISMATCH` / topology mismatch |
| 合法对照 | 同 base 与 happy candidate `audit.passed is True`、`issues==()` |

### 附带核对

- exact ratio 绑定：改写 `actual_factor_ratio=1.0005`（NO_EVENT rtol 内）并同步 relative error → 仍 topology mismatch，且无 `reconciliation result failed verification`
- 单 factor 零 transition：空 evidence audit 通过
- 版本钉：`m3-g1-tushare-mapper-v3` / `tushare_factor_daily_preclose_v3` / `m3-g1-manifest-v3`

独立对抗脚本退出码：`0`（`ALL_REVIEW_ADV PASS`）。

---

## 4. 未回退项

| 项 | 证据 |
|---|---|
| P0 fail-closed / no-event / membership | `test_m3_g1_candidate.py` 全量 49 绿 |
| ADV3a 窗外 factor bar-span | 矩阵 7：`FACTOR_INVALID` + verify `IDENTITY_MISMATCH` |
| v3 版本未回退 | candidate `_MAPPER_VERSION`、`G1_CORPORATE_ACTION_RECONCILIATION_VERSION`、release manifest V3 字面量保持 |
| 未改 scope 投影 / reconciliation 生成算法 | R1 diff 仅新增拓扑 audit 闭包与测试；无 mapper/manifest 算法改动 |

---

## 5. 未验证项

- 正式零网络 `status` / REFERENCE / PREPARE / PUBLISH / G2A
- 网络或真实凭据
- WSL Miniforge `base` / Linux Gate / ext4 发布语义
- Codex 主验

---

## 6. 结论

**PASS**（实现 commit `1749905`）。前序 FAIL（ADV3b：删 transition evidence 重绑后 audit 仍通过）已由自包含拓扑绑定关闭；实现者矩阵 1–8 复跑绿；独立 ADV1（保行数非相邻 previous）与 ADV2（停牌 mid factor 删前/后侧）均返回 `CORPORATE_ACTION_FACTOR_MISMATCH`；合法 candidate 通过；ratio 精确绑定、单 factor 零 transition、ADV3a、P0 fail-closed 与 v3 版本未见回退。

不宣布 G1 / Codex / Linux Gate 通过。可进入主 Agent 终验队列。
