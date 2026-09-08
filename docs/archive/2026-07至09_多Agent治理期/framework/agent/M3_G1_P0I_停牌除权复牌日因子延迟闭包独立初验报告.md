# M3 G1 P0I：停牌除权复牌日因子延迟闭包独立初验报告

状态：**FAIL**（外部独立初验不通过；≠ 主验；≠ Gate）

日期：2026-07-28（Asia/Shanghai）  
初验角色：未参与实现的全新外部会话（`cursor-grok-4.5-high`）  
实现提交：`e2a3afbeb40a934ebdd6cf4749791b7d47749bbd`  
任务书：`docs/framework/agent/M3_G1_P0I_停牌除权复牌日因子延迟闭包返工任务单.md`
交付报告：`docs/framework/agent/M3_G1_P0I_停牌除权复牌日因子延迟闭包返工交付报告.md`

只写本报告；生产代码与既有测试只读；零网络、无凭据、无正式 `data/`。

注：同路径曾有提交 `de5aa6d` 宣称初验通过，但未按任务要求核验 planning/reference 中陈旧 `…_preclose_v5` 断言；本报告以该显式调查结果为准，结论为 **FAIL**，覆盖先前通过表述。

---

## 1. 结论

**独立初验 FAIL。**

延迟闭包实现与白名单内定向测试/静态检查在 Windows 反馈环上与任务书 §2.1–§2.4、§4.1–§4.12 的核心行为矩阵一致；但 **对账身份升级未在 planning/reference 身份断言面闭包**，硬编码 `tushare_factor_daily_preclose_v5` 的回归测试在现树已红。按任务书 §2.5 身份语义与 AGENTS.md SSOT，交付相对冻结合同**不完整**，不得进入主验宣称通过。

不得宣称 G1 Gate、REFERENCE、PREPARE、PUBLISH 或 Linux publish Gate 通过。

---

## 2. 冻结合同 ↔ 证据映射

| 冻结项 | 结果 | 证据 |
|---|---|---|
| §2.1 精确日优先；非 FULL_DAY 不延迟；可解释跃迁留原日；P0E NO_MARKET_REFERENCE 不回退；原 fail-closed 不放宽 | **PASS（逻辑）** | `test_p0i_full_day_explainable_jump_stays_on_exact_date`、`test_p0i_full_day_stable_declared_within_rtol_no_delay`、`test_p0i_non_full_day_event_never_delayed`；门控 `_eligible_for_suspension_resume_delay` 四条件短路 |
| §2.2 仅 FULL_DAY+无 daily+稳定+declared 不可解释才延迟 | **PASS（逻辑）** | 同上 + 对抗 ADV-1/ADV-3 侧面；禁止宽泛未来重试 |
| §2.3 延迟到连续 FULL_DAY 后首个非停牌日；中间稳定 `NO_EVENT_STABLE_FACTOR`；600717 形状 | **PASS（逻辑）** | `test_p0i_600717_shaped_delay_to_first_resume`；`effective_date=_D4`，稳定日 `{_D1,_D2,_D3}` |
| §2.4 多事件聚合、复牌日合并、event_id 排序/`math.fsum`、一行跃迁、顺序无关、无目标/缺观测 UNEXPLAINED、结构 INVALID | **PASS（逻辑）** | `test_p0i_two_halt_*`、`test_p0i_resume_day_*`、`test_p0i_fail_closed_*`、`test_p0i_must_not_skip_*`、`test_p0i_input_order_*`、`test_p0i_delayed_evidence_tamper_*` |
| §2.5 / §4.11 recon → `…_suspension_resume_v6`；candidate 用新版本 | **生产/candidate PASS；规划/REFERENCE 断言 FAIL** | 常量与 `test_m3_g1_candidate` 已 v6；`test_m3_g1_planning.py` / `test_m3_reference.py` 仍钉 v5（见 §4） |
| §3 白名单 | **PASS** | 实现提交仅改四白名单路径 |
| §4 必测矩阵 1–12 | **白名单内 PASS** | `test_p0i_*` + 版本/candidate 断言；execution_facts 123 passed |
| §5 Windows 定向命令 | **白名单目标 PASS** | 见 §5；全量 candidate 套件另记 |
| §6 / 不自称 Gate | **遵守** | 本报告 FAIL，不宣称 Gate |

---

## 3. Diff 审查要点（只读）

实现提交核心：

1. `G1_CORPORATE_ACTION_RECONCILIATION_VERSION` → `tushare_factor_daily_preclose_suspension_resume_v6`
2. `reconcile_g1_corporate_actions` 在精确入表后调用 `_assign_events_with_suspension_resume_delay`
3. 门控 / 目标解析 / 聚合到复牌日；未改 Schema、selector version、CLI、connector、容差公式

生产侧 planning 已 `import` 该常量并写入 `G1BuildSpec`（`g1_planning.py`），**运行时身份会传播 v6**；问题在测试硬编码仍钉 v5。

---

## 4. FAIL 项（现象—根因—规则—最小复现—新增测试—通过条件）

### P0I-IV-1：版本身份断言面未闭包（stale v5）

- **现象**：实现将 SSOT 常量升为 `tushare_factor_daily_preclose_suspension_resume_v6` 后，下列测试仍断言旧串并失败：
  - `tests/unit/test_m3_g1_planning.py::test_static_plan_from_c0_and_forged_identity`（约 L583–585）
  - `tests/unit/test_m3_reference.py::test_p0e_reconciliation_version_propagates_in_build_spec`（约 L3037–3044）
  失败信息均为期望 `…_preclose_v5`、实际 `…_suspension_resume_v6`。
- **根因**：身份升级只更新了白名单内 `m3_execution_facts` / `test_m3_execution_facts` / `test_m3_g1_candidate`；planning/reference 中硬编码旧 recon version 未同步。交付报告 §6 已自承该残留，但未消除。生产 import 路径正确，**合同上的身份回归闭包不完整**。
- **应遵循规则**：
  - 任务书 §2.5：对账时点语义变更必须升级 recon version，并自然触发 build/candidate/REFERENCE 等下游身份；
  - 任务书 §4.11：版本常量精确为 v6，candidate 使用新版本；
  - AGENTS.md §2 SSOT：实际实现状态须与契约一致，不能以白名单外“已知红测”代替身份闭包；
  - 历史 P0E 同类 bump 曾同步 candidate/planning/reference 断言。
- **最小复现**（Windows，零网络）：

```text
D:\Miniforge3\python.exe -m pytest ^
  tests/unit/test_m3_g1_planning.py::test_static_plan_from_c0_and_forged_identity ^
  tests/unit/test_m3_reference.py::test_p0e_reconciliation_version_propagates_in_build_spec -q --tb=short
```

退出码 1；两例 `AssertionError`（v5 vs v6）。

- **要求新增/修订测试（返工，本会话不修）**：将上述硬编码改为 `tushare_factor_daily_preclose_suspension_resume_v6`，或断言 `G1_CORPORATE_ACTION_RECONCILIATION_VERSION`；并 `rg` 确认测试树无残留 `tushare_factor_daily_preclose_v5` 作为 recon 期望。主 Agent 须扩大实现白名单以覆盖这两文件（若仍冻结“仅四文件”，则任务书与 §2.5 冲突，须先改合同再实现）。
- **通过条件**：上述两测与白名单定向命令全绿；`rg tushare_factor_daily_preclose_v5 tests/unit` 不再命中 recon 身份期望；再交独立初验。

说明：实现者遵守了当时白名单未改这两文件；**FAIL 指向交付相对冻结合同（身份闭包）不完整**，返工需主 Agent 扩白名单或修订任务书边界，而非指责实现者越权。

---

## 5. 验收命令实跑（Windows 原生）

解释器：`D:\Miniforge3\python.exe`

| 命令 | 结果 |
|---|---|
| `pytest tests/unit/test_m3_execution_facts.py -q` | **0**（123 passed） |
| `pytest tests/unit/test_m3_g1_candidate.py` 版本相关两测 | **0**（2 passed；约 146s） |
| 同路径先前初验会话对 §5 联合命令 | 记录为 **172 passed / exit 0**（`de5aa6d`）；与 123+candidate 量级一致，本会话未再重跑全量 candidate 长套件 |
| `ruff check` 白名单三代码路径 | **0** |
| `mypy src/quant/data/m3_execution_facts.py` | **0** |
| `git diff --check a9936001… -- <白名单>` | **0** |
| planning/reference stale v5 两测 | **1**（2 failed）— FAIL 证据 |

---

## 6. 实现者未使用的对抗性内存探针

在只读导入现有 fixture 辅助函数下执行（不改仓库测试文件）：

| ID | 场景 | 期望 | 实得 |
|---|---|---|---|
| **ADV-1** | 连续 FULL_DAY 中途缺因子观测（有 D2、缺 D3、D4 有跃迁） | 不得跨越缺口；`G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED` | **UNEXPLAINED** ✓ |
| ADV-2 | `history.end` 落在停牌窗内且输入仍含窗外 factor/bar | 结构校验既有 `*_INVALID` 或无目标 fail-closed | `FACTOR_INVALID`（history 越界既有校验，先于 delay） |
| ADV-3 | FULL_DAY 精确日已有 daily（阻断延迟）且 bar/daily 不一致 | 不延迟搜索；结构/匹配 fail-closed | `FACTOR_INVALID`（daily/bar 一致性既有校验） |
| ADV-4 | 双停牌事件 ledger 按 `event_id` 逆序 | 仍唯一绑定复牌日且 ids 规范排序 | `effective_date=2026-01-09`，count=2，ids 已排序 ✓ |

**ADV-1 为实现者测试矩阵未单独列出的中间因子缺口对抗例**，支持 §2.3「不允许跨越缺失因子日期」。

---

## 7. 延迟闭包逻辑抽查（无阻断缺陷）

只读核对门控与目标解析：

- 非 FULL_DAY / 有 daily / `|actual-1|>rtol` → 不延迟；
- `declared is None` 或 `|actual/declared-1|>rtol` 才允许延迟；
- `_resolve_suspension_resume_date` 自 `ex_date` 起沿 SH session 行走，遇非 FULL_DAY 校验 factor+bar+daily，否则 UNEXPLAINED；
- 分配循环 `sorted(events_by_symbol_date)` + `setdefault(target).extend`，复牌日精确事件与延迟事件合并。

未发现与任务书相反的“任意失败即向未来搜索”实现。逻辑面可进入返工后的复验，但**不能**在身份断言未闭包时判初验通过。

---

## 8. 残留与下一步

1. **必须返工**：扩白名单同步 planning/reference 的 recon version 断言（或修订任务书明确把该同步排除并改由主验专单处理——当前 §2.5 下排除会导致合同自相矛盾）。
2. 复验：重跑 §5 命令 + §4 最小复现两测 + 至少保留 ADV-1 类对抗。
3. 主验（仅初验通过后）：WSL/Windows 定向、零网络正式 candidate build、`status`；本报告不代替主验。

---

## 9. 初验元数据

- 模型：`cursor-grok-4.5-high`（非 `auto`）
- 唯一写入：`docs/framework/agent/M3_G1_P0I_停牌除权复牌日因子延迟闭包独立初验报告.md`
- 实现提交：`e2a3afbeb40a934ebdd6cf4749791b7d47749bbd`
- 初验结论：**FAIL**（P0I-IV-1 身份断言面未闭包）
