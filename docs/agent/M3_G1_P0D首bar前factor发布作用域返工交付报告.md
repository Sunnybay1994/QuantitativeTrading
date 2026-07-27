# M3 G1 P0D：首 bar 前 factor 发布作用域返工交付报告

- 角色：外部实现接管 Agent（全新会话，`cursor-grok-4.5-high`）
- 任务单：[`M3_G1_P0D首bar前factor发布作用域返工任务单.md`](M3_G1_P0D首bar前factor发布作用域返工任务单.md)
- 主裁定：[`20260727_M3_G1_P0返工Codex主验通过但正式G1仍阻塞.md`](20260727_M3_G1_P0返工Codex主验通过但正式G1仍阻塞.md)
- 接管 Prompt：`artifacts/g1_component_diag_20260722/cursor_p0d_takeover_prompt.md`
- 日期：2026-07-27

## 结论

接管上一实现会话未提交白名单改动并完成交付：发布级 `adjustment_factor` /
apply / reconcile / verify 统一消费 `first_bar..last_bar` scoped factors；mapper /
reconciliation / manifest 升至 v3；`audit_g1_candidate` 仅做 candidate 自包含范围校验，
精确 scoped 重建由 `verify_g1_candidate`（frozen inputs）承担。Windows 定向自验绿。
**不宣称 G1 / Codex 主验 / Linux Gate 通过。**

## 接管动作

1. 保留既有有效实现（scope 投影、reconcile 窗外省略、manifest v3、矩阵测试）。
2. 修正职责声明与测试：
   - audit 注释明确为 candidate 表自包含 bar-span 校验；
   - 攻击用例同时断言 audit `FACTOR_INVALID` 与 verify `IDENTITY_MISMATCH`；
   - 投影用例覆盖首末之间停牌日 factor 保留。
3. 未触碰任务书外文件；未跑正式 status/reference/prepare/publish/G2A。

## 改动文件

| 文件 | 目的 |
|---|---|
| `src/quant/data/m3_g1_candidate.py` | `project_scoped_adjustment_factors`；build 统一消费 scoped；audit 自包含范围校验；mapper v3 |
| `src/quant/data/m3_execution_facts.py` | reconciliation v3；窗外 ledger 省略；允许单 factor（0 transition） |
| `src/quant/research/m3/g1_planning.py` | mapper v3 |
| `src/quant/data/m3_release.py` | `G1ManifestV3` + 当前 publish；保留 v1/v2 历史 strict-read |
| `tests/unit/test_m3_execution_facts.py` | P0D 矩阵（000553 结构、P0 防回退、窗外 ledger、行数/digest） |
| `tests/unit/test_m3_g1_candidate.py` | scope 投影（含停牌日）、build、audit/verify 攻击分工、缺 factor |
| `tests/unit/test_m3_g1_release.py` | manifest v3 / mapper 精确锁；历史 v1/v2 仍可读 |
| `tests/unit/test_m3_reference.py` | build_spec mapper v3 字面量 |
| `tests/unit/test_m3_g1_planning.py` | mapper 断言同步 v3 |
| 本报告 | 唯一实现交付报告 |

## 关键设计

1. 每 symbol 由 `bars_no_factor` 取 `first_bar/last_bar`，投影
   `first_bar <= effective_date <= last_bar`；保留首末之间停牌 session factor，不裁成仅 bar 键。
2. raw/receipt 不动；candidate 表与 apply/reconcile/verify 同 scoped 输入。
3. `ex_date` 在 scoped 范围外：不 matching、不抛 `FACTOR_INVALID`；范围内原 P0 fail-closed。
4. 身份：`m3-g1-tushare-mapper-v3` + `tushare_factor_daily_preclose_v3`；manifest 当前为
   `m3-g1-manifest-v3`，旧 v1/v2 仍精确锁各自 mapper。
5. **audit vs verify**：`audit_g1_candidate` 仅持有 candidate，做自包含
   `[first_bar,last_bar]` 范围校验；`verify_g1_candidate` 从 frozen inputs 经
   `build_g1_candidate` 重建 scoped 表并比对身份。

## 命令与退出码

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

## 关键断言（矩阵映射）

1. 首 bar 前 jump + ledger：unscoped 仍 `FACTOR_UNEXPLAINED`；scoped 后 build/reconcile 不因它失败。
2. 首 bar 后无 event 大 jump：仍 `FACTOR_UNEXPLAINED`。
3. 既有 FULL_DAY declared/no-market 与 PARTIAL 失败合同保持（原测试继续绿）。
4. 窗外 ledger 省略；篡改回 scope 内 + 未解释 jump → fail-closed。
5. bar 缺 factor / 非法 factor 仍失败。
6. scoped 边界包含、停牌日保留、行数 `sum(max(n-1,0))`、乱序 digest 稳定。
7. 恢复被裁 factor 并重绑 digest/primary → audit `FACTOR_INVALID`（自包含范围）；
   同攻击 → verify `G1_CANDIDATE_IDENTITY_MISMATCH`（frozen inputs 重建）。
8. mapper/reconciliation/manifest v3 贯穿；v2 伪装 v3、跨版本混入失败；历史 v1/v2 可读。
9. `eligible_keys.head(1)` 与 no-event `1.5` jump 对抗继续通过。

## 未验证 / 剩余风险

- 未跑正式零网络 `status` / REFERENCE / PREPARE / PUBLISH / G2A（任务禁止）。
- 未跑 WSL/Linux Gate；Windows 绿测不等于 Linux Gate。
- 主裁定已预警：首 bar 后无 dividend 大 jump、`600733` 双计数等仍可能成为下一首败，需另立合同。
- `tests/unit/test_m3_reference.py` / `test_m3_g1_planning.py` 仅同步版本字面量，未扩实现范围。
