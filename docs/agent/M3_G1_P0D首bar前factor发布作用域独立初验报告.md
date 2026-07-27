# M3 G1 P0D：首 bar 前 factor 发布作用域独立初验报告

- 日期：2026-07-27
- 角色：外部**独立初验** Agent（全新会话，未参与实现；模型 `cursor-grok-4.5-high`）
- 分支：`cursor/g1-p0-rework-20260726`
- 实现 commit：`8e53d05fefd7ad40b33d21cc06e15140f69182bd`
- 依据：
  [`M3_G1_P0D首bar前factor发布作用域返工任务单.md`](M3_G1_P0D首bar前factor发布作用域返工任务单.md)、
  [`M3_G1_P0D首bar前factor发布作用域返工交付报告.md`](M3_G1_P0D首bar前factor发布作用域返工交付报告.md)、
  [`20260727_M3_G1_P0返工Codex主验通过但正式G1仍阻塞.md`](20260727_M3_G1_P0返工Codex主验通过但正式G1仍阻塞.md)
- **结论：FAIL**
- **本报告不等于 Codex 终验 / Linux Gate / 正式 status / G1 通过**
- 生产代码与实现者测试严格只读；唯一写入为本报告

---

## 1. 任务书 §2 / §5 / §7 映射（不复述交付报告）

### §2.1 发布级 factor scope

| 合同点 | 代码/证据 | 判定 |
|---|---|---|
| 每 symbol `first_bar/last_bar` 来自 `bars_no_factor` | `project_scoped_adjustment_factors` 自 bars 聚合 bounds | 成立 |
| `first_bar <= effective_date <= last_bar` 投影 | 同函数；ADV1/ADV4 探针证实边界外裁、窗内停牌日保留 | 成立 |
| apply / candidate 表 / reconcile 同 scoped | `build_g1_candidate` 先投影再 apply/reconcile | 成立 |
| raw/receipt 不删改 | 无 raw/journal 写路径改动 | 成立 |
| 不裁成“仅 bar 键”；停牌 session factor 保留 | 投影保留 mid-span 无 bar 日；ADV4 PASS | 成立 |

### §2.2 公司行动边界

| 合同点 | 代码/证据 | 判定 |
|---|---|---|
| 窗外 `ex_date` 不 matching、不抛 `FACTOR_INVALID` | `reconcile` omit `<scoped_first/>scoped_last`；ADV2 PASS | 成立 |
| 窗内无事件 jump / 有事件失败仍 fail-closed | ADV1、ADV2 last-day/follow-on；既有 P0 测试绿 | 成立 |
| 禁止回退 `NO_EVENT_STABLE_FACTOR` | `_no_event_evidence_row` 仍仅 `abs(actual-1)<=rtol` | 成立 |
| 行数 `sum(max(n-1,0))` | reconcile 内 `expected_rows` 校验；实现者矩阵测试绿 | 成立 |

### §2.3 身份与方法版本

| 合同点 | 代码/证据 | 判定 |
|---|---|---|
| mapper → `m3-g1-tushare-mapper-v3` | candidate / planning / manifest V3 精确锁 | 成立 |
| reconciliation → `tushare_factor_daily_preclose_v3` | `m3_execution_facts` 常量 + build_spec | 成立 |
| 历史 v1/v2 strict-read；跨版本伪装失败 | release 定向 4 测 PASS；`G1ManifestV3` 锁 mapper v3 | 成立 |

### §5 实现矩阵抽查

1–6、8–9：实现者测试 + 本轮定向 pytest/对抗探针覆盖，**语义成立**。  
7：**部分成立**：恢复窗外 factor → `audit` `FACTOR_INVALID` + `verify` `IDENTITY_MISMATCH`（ADV3a PASS）；但 **audit 未把 reconciliation evidence 拓扑与 scoped factor transitions 精确绑定**（ADV3b FAIL，见 §3/#3 与返工项）。

### §7 独立初验强制反例

见 §3；其中 #3 后半为否决项。

---

## 2. 定向命令与退出码

环境：`D:\Miniforge3\python.exe`（Windows 反馈环，非 Linux Gate）。

```text
pytest tests/unit/test_m3_execution_facts.py tests/unit/test_m3_g1_candidate.py -q --tb=line
→ 102 passed, EXIT 0

pytest tests/unit/test_m3_g1_release.py::test_b1b_manifest_v1_strict_read_v2_current_and_forged_rejected \
       tests/unit/test_m3_g1_release.py::test_b1b_r4_manifest_mapper_version_exact_lock \
       tests/unit/test_m3_g1_release.py::test_inputs_exact_rebuild \
       tests/unit/test_m3_g1_release.py::test_publish_verify_happy_path -q --tb=line
→ 4 passed, EXIT 0

ruff check <白名单生产+测试>
→ All checks passed!, EXIT 0

mypy <白名单生产模块>
→ Success: no issues found in 4 source files, EXIT 0

git diff --check -- <白名单>
→ EXIT 0
```

未跑：正式 status / reference / prepare / publish / G2A、网络、真实凭据、WSL/Linux Gate。

---

## 3. 对抗性验证（实现者未使用的组合）

### #1 多窗外 jump + 窗内无事件 jump

构造：factors `D-2=0.5, D-1=0.8, first=1.0, last=1.5, after=1.5`；bars 仅 `first..last`。

- `project_scoped_adjustment_factors` → 仅 `[first,last]`，窗外两跳被裁。
- scoped reconcile → `G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`（窗内 1.0→1.5）。

**PASS**：只裁窗外，窗内仍 fail-closed。

### #2 ledger 边界：前一天 / 首日 / 末日 / 后一天

scoped factors=`[first, mid_halt, last]`（flat 1.0）；ledger 四日现金事件。

- before / first / after 省略 matching → reconcile 出 2 条 `NO_EVENT_STABLE_FACTOR`。
- first-only 省略后，窗内 mid 人为 1.5 jump → 仍 `FACTOR_UNEXPLAINED`（未吞后续异常）。
- last-day 事件不省略：flat+cash → `FACTOR_UNEXPLAINED`。

**PASS**：包含边界精确；首日可因无 prior transition 省略证据。

### #3 攻击：恢复窗外 factor；删除 scoped transition evidence

**3a 恢复窗外 factor 并重绑 digest/primary**

- `audit_g1_candidate` → `passed=False`，`FACTOR_INVALID` / `adjustment factor outside publish bar scope`
- `verify_g1_candidate` → `G1_CANDIDATE_IDENTITY_MISMATCH`（frozen inputs 重建）

**PASS**；且两条 API 能力区分成立：audit=自包含 bar-span；verify=inputs 精确重建。

**3b 删除一条 scoped factor transition 对应 reconciliation 行并重绑自包含 hashes**

- 自 happy candidate（recon height=300）删除
  `('000001.SZ', 2016-02-01, 2016-02-02)` 的 `NO_EVENT_STABLE_FACTOR` 行后重绑。
- 相对 scoped factors 拓扑缺失 **1** 条 transition。
- **`audit_g1_candidate` → `passed=True`，issues=[]**
- `verify_g1_candidate` → `G1_CANDIDATE_IDENTITY_MISMATCH`

根因：`audit` 仅调用 `verify_corporate_action_reconciliation_result`（行内公式 + 表 digest）与 receipt lineage；**不**校验
`evidence` 键集/行数是否等于 scoped adjacent factor transitions。既有 `audit` API 无 frozen inputs，亦无自包含拓扑闭合。

按初验 Prompt：**不得淡化为仅由 verify 兜底** → **FAIL（否决项）**。

### #4 停牌 session factor 保留

bars=`[first,last]`，factors 含 mid；scoped 保留 mid。**PASS**（与实现者投影测互补）。

### #5 无特例 / rtol / P0 未回退

- 生产模块无 `000553`/`600733` 硬编码。
- `_validate_rtol` 仍要求 `0<=rtol<=0.01` 的 float；未放宽。
- 无事件大 jump、有事件失败路径仍 raise，未见回退 `NO_EVENT`。

**PASS**。

### #6 mapper/reconciliation/manifest v3

candidate/planning/build_spec/manifest V3 精确锁 mapper v3；历史 v1/v2 可读、伪造跨版本失败；定向 release 测绿。**PASS**。

---

## 4. 返工项（FAIL）

### R1 — audit 必须自包含绑定 scoped factor ↔ reconciliation topology

| 项 | 内容 |
|---|---|
| 现象 | 删除一条 scoped transition 的 reconciliation evidence 并重绑 table digests / primary key 后，`audit_g1_candidate` 仍 `passed=True`；仅 `verify_g1_candidate` 拒绝 |
| 根因 | audit 对 reconciliation 只做 schema/digest/行内公式与 daily receipt 校验，不对照 candidate `adjustment_factors` 的相邻 transition 键集与 `sum(max(n-1,0))` 行数公式 |
| 应遵循规则 | 任务书 §2.1（audit 与 scoped factors 同作用域语义）、§5.7 / §7（audit 拒绝自包含攻击）；初验 Prompt #3 明确要求 evidence 拓扑与 scoped factors 精确绑定，不得仅依赖 verify |
| 最小复现 | `build_g1_candidate(happy)` → 删 1 条 recon 行 → 重算 digests/primary → `audit_g1_candidate` 现为 True；期望 False |
| 新增测试 | 独立用例：删/改写一条 scoped transition evidence 并重绑后，`audit.passed is False` 且 issue 明示 topology/row-count/键集不匹配；verify 仍 `IDENTITY_MISMATCH` |
| 通过条件 | 上述攻击下 audit 失败；ADV3a（窗外 factor）仍失败；不引入 frozen inputs 到 audit 也可，但必须用 candidate 内 bars/factors/recon 自包含闭合；不得宣称“verify 已覆盖故 audit 免检” |

---

## 5. 未验证项

- 正式零网络 `status` / REFERENCE / PREPARE / PUBLISH / G2A
- WSL Miniforge `base` / Linux Gate / ext4 发布语义
- 主裁定预警的首 bar 后无 dividend 大 jump、`600733` 双计数等后续真实数据风险（本轮范围外）

---

## 6. 结论

**FAIL**（实现 commit `8e53d05`）。scoped 投影、窗外 omit、窗内 fail-closed、版本 v3 与 ADV3a audit/verify 分工大体成立，但 **audit 缺少 scoped factor transition ↔ reconciliation evidence 拓扑绑定**，对抗 #3b 未通过。返回主 Agent 形成返工；本 Agent 不修改生产代码或实现者测试。
