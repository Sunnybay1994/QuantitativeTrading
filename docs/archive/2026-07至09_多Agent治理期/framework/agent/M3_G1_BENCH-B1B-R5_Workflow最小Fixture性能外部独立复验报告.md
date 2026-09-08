# M3 G1 BENCH-B1B-R5：Workflow 最小 Fixture 性能外部独立复验报告

| 项 | 内容 |
|---|---|
| 角色 | 外部独立复验 Agent（全新会话，未参与 R5 实现） |
| 模型 | `cursor-grok-4.5-high` |
| 权威任务 | `docs/framework/agent/M3_G1_BENCH-B1B-R5_Workflow最小Fixture性能返工任务单.md` |
| 实现证据 | `docs/framework/agent/M3_G1_BENCH-B1B-R5_Workflow最小Fixture性能外部返工交付报告.md` |
| 复用产物 | `artifacts/r5_independent_verify_20260722/`（本会话未启动 pytest / five_stage） |
| 只读约束 | 生产代码与实现者测试严格只读；唯一写入为本报告 |
| 复验结论 | **PASS**（R5 冻结证据面闭合；对抗探针全绿） |
| Gate | **不得、亦不宣布** B1B 关闭或 G1 Gate 通过 |

---

## 1. 范围与证据基线

已阅读：R5 返工任务单、R5 外部返工交付报告，以及下列预置复验日志（本会话**不**重跑）：

| 产物 | 用途 | 退出码摘要 |
|---|---|---|
| `resume_two.log` | 两恢复语义测定向复跑 + durations | `RC_RESUME=0`；2 passed / 42.66s |
| `history_max_new.log` | 非法预算拒收回归 | `RC_MAXNEW=0`；1 passed / 1.91s |
| `ruff.log` | 白名单文件静态检查 | `RC_RUFF=0`；All checks passed |
| `diff_check.log` | 行尾/空白 diff 卫生 | `RC_DIFFCHECK=0` |
| `adversarial_probe.log` | 实现者未覆盖的对抗性探针 | `RC_ADV=0`；`SUMMARY PASS failed=0` |

本轮仅核对 R5 冻结的最小 fixture 是否仍能证明恢复合同，而非空计划或 mock 绕过。未启动 `five_stage`、未跑全量 pytest、未触网、未改生产代码。

---

## 2. 任务单验收项 ↔ 证据映射

### 2.1 非空 HISTORY 计划（非空虚计划）

| 检查点 | 证据 | 结果 |
|---|---|---|
| 计划非 null / 非空 | `adversarial_probe.log`：`[PASS] plan_non_null`；`[PASS] plan_non_empty_and_scaled :: reqs=153 symbols=30` | PASS |
| 非虚空极小计划 | `[PASS] plan_not_vacuous_tiny :: reqs=153` | PASS |
| 相对 300 证券正式规模已收缩但仍有实质请求 | `[PASS] plan_far_below_300_symbol_scale :: reqs=153`；交付报告称 `30×5+fund=153` | PASS |
| 基金端点仍在计划中 | `[PASS] fund_endpoints_present :: pos=[56, 95, 143]`；`fund_count=3` | PASS |

判定：缩小后 HISTORY 计划为 **153 请求 / 30 证券**，含 fund 端点位置，非空、非虚空。

### 2.2 真实跨过基金身份

| 检查点 | 证据 | 结果 |
|---|---|---|
| 有界步进后进入 fund 身份 | `[PASS] crossed_into_fund_identity :: fund_ids=1 committed=57` | PASS |
| 跨 fund 前后 index-only / 精确 commit 边界 | `step_at_0/2/4/57` 系列全部 `[PASS]` | PASS |
| 基金身份唯一 | `[PASS] fund_identities_unique` | PASS |
| 完成路径上基金闭包 | `[PASS] fund_fake_closure :: expected_adj=1`；`[PASS] history_completes`；`done_commits_positive :: n=95` | PASS |

判定：有界执行真实推进并跨过至少一个 `fund_*` 身份，而非停在纯指数段。

### 2.3 Resume 前缀复用

| 检查点 | 证据 | 结果 |
|---|---|---|
| 跨 fund 后前缀稳定 | `[PASS] resume_prefix_stable_after_across_fund` | PASS |
| 两恢复语义测绿 | `resume_two.log`：`test_history_bounded_incomplete_then_resume_success` + `test_history_unbounded_incomplete_still_fail_closed` → 2 passed | PASS |
| 未 mock 恢复链 | `[PASS] resume_tests_do_not_mock_recovery_chain`；`[PASS] execute_tushare_batch_is_real :: mod=quant.data.m3_backfill` | PASS |

判定：连续有界恢复保持前缀稳定；恢复链仍走真实 backfill 路径。

### 2.4 完成后再调用零新增

| 检查点 | 证据 | 结果 |
|---|---|---|
| reuse 完成 | `[PASS] reuse_completed` | PASS |
| 零新增 | `[PASS] reuse_zero_new` | PASS |
| 零额外网络 | `[PASS] reuse_zero_extra_network :: delta=0` | PASS |
| fund 身份集合不变 | `[PASS] reuse_fund_identities_unchanged` | PASS |

判定：HISTORY 完成后再次无界调用零新增、零额外网络，符合任务单冻结证据第 4 项。

### 2.5 Monkeypatch 不泄漏到生产规模字面量

| 检查点 | 证据 | 结果 |
|---|---|---|
| patch 可缩小 expected / dates | `[PASS] patch_shrinks_expected_count :: got 30`；`[PASS] patch_shrinks_dates :: dates=2 keys=60` | PASS |
| undo 恢复 expected / dates / policy / field_specs | `monkeypatch_undo_restores_*` 四项全部 `[PASS]`；undo 后 `index=300` | PASS |
| 探针结束后模块字面量仍为生产规模 | `[PASS] module_literals_still_production_scale_after_probe :: index=300 dates=20` | PASS |
| `_fast_config` 仍 300 成分 | `[PASS] fast_config_still_300_constituents :: got=300`；`[PASS] fast_config_no_constituent_shrink` | PASS |
| patch 调用点仅限目标测试 | `[PASS] patch_call_sites_only_two_tests :: count=3`；`resume_*_call_sites :: count=3` | PASS |
| 非法预算测试仍独立绿 | `history_max_new.log`：1 passed（未改其 300 规模合同面） | PASS |

判定：fixture patch 可逆、不泄漏；正式 `_fast_config`/模块字面量保持 300 规模。

### 2.6 对抗性反例（实现者交付报告未展开的探针）

任务单要求独立初验增加对抗检查，确认「非空计划、真实跨基金、resume 前缀复用、最终零新增，而非空计划或 mock」。`adversarial_probe.log` 正覆盖该面，且额外包含：

- PRE 字面量快照：`index_expected=300`、`dates_per_symbol=20`、`key_count=600`、`policy_fn=_build_cross_source_policy`
- 真实 `execute_tushare_batch` 模块归属断言
- resume helper / patch 调用点计数约束
- `FAILURES []`；`SUMMARY PASS failed=0`；`RC_ADV=0`

判定：对抗反例面闭合，且与交付报告 §4「剩余风险」中要求的独立确认一一对应。

---

## 3. 性能与静态卫生（复用日志）

| 项 | 记录 | 相对任务单 |
|---|---|---|
| 两恢复语义合计 | `resume_two.log`：42.66s（bounded 38.66s + unbounded 1.88s） | 满足「通常 ≤60s」（WSL 产物口径；与交付报告 42.02s 同量级） |
| Ruff | `ruff.log`：通过 | PASS |
| `git diff --check` | `diff_check.log`：`RC_DIFFCHECK=0` | PASS |

说明：交付报告已声明 Windows 同 fixture 可能更慢；本复验复用的是既有 WSL 产物，不把 Windows 绿测表述为 Gate。

---

## 4. 未削弱合同面的抽查结论

对照任务单 §2 冻结证据与交付报告 §2：

1. 严格正整数预算校验：`history_max_new` 仍绿，且对抗探针确认 `_fast_config` 仍 300。
2. 有界双轮预算内提交 + 前缀稳定：对抗 `step_*` / `resume_prefix_stable_*` + `resume_two` 绿。
3. 真实跨 fund：`crossed_into_fund_identity` PASS。
4. 完成后零新增：`reuse_zero_new` / `reuse_zero_extra_network` PASS。
5. 无界截断 fail-closed：由 `test_history_unbounded_incomplete_still_fail_closed` 在 `resume_two.log` 中通过覆盖（本会话未另开 five_stage）。
6. 基金闭包：`fund_fake_closure` PASS。
7. 正式 637/3185/3190：本轮只读证据未显示 R5 改动生产/planning 合同测试；对抗确认 patch 调用点仅限两恢复测。

---

## 5. 结论

**初验结论：PASS。**

R5 将 HISTORY 恢复语义 fixture 缩至 30 证券 / 153 请求后，复用产物证明：计划非空、真实跨基金身份、resume 前缀复用、完成后零新增、monkeypatch 可逆不泄漏，且对抗探针全绿。两恢复测合计约 43s，落在任务单性能目标内。

**明确不宣布**：B1B Gate、G1 Gate、全量回归或主验通过。后续仍由主 Agent 做契约/跨模块/文档一致性终验。
