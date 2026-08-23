# M3 G1 P0D-R1：audit 与 scoped reconciliation 拓扑绑定返工交付报告

- 角色：外部返工实现 Agent（全新会话，`cursor-grok-4.5-high`）
- 任务单：[`M3_G1_P0D-R1_audit与reconciliation拓扑绑定返工任务单.md`](M3_G1_P0D-R1_audit与reconciliation拓扑绑定返工任务单.md)
- 否决证据：[`M3_G1_P0D首bar前factor发布作用域独立初验报告.md`](M3_G1_P0D首bar前factor发布作用域独立初验报告.md) ADV3b
- 前置实现：`8e53d05 Complete G1 P0D scoped factor publication`
- 日期：2026-07-27

## 结论

`audit_g1_candidate` 现仅用 candidate 自带 `adjustment_factors` 重建立即相邻
transition 拓扑，并与 `corporate_action_reconciliation` 的 key 集、行数
`sum(max(n-1,0))` 与精确 `actual_factor_ratio` 绑定；删除/增行/改写 previous/
ratio 并重绑身份后 audit fail-closed。未改 scope 投影、reconciliation 生成算法或
v3 版本字面量；未给 audit 注入 frozen inputs。Windows 定向自验绿。
**不宣称 G1 / Codex 主验 / Linux Gate 通过。**

## 改动文件（白名单）

| 文件 | 目的 |
|---|---|
| `src/quant/data/m3_g1_candidate.py` | `_audit_scoped_factor_reconciliation_topology`；`audit_g1_candidate` 调用 |
| `tests/unit/test_m3_g1_candidate.py` | P0D-R1 攻击矩阵 1–8 |
| 本报告 | 唯一实现交付报告 |

## 关键设计

1. 按 `symbol,effective_date` 排序 scoped factors，重建
   `(symbol, previous_factor_date, effective_date)`。
2. expected key 集必须与 evidence 三字段 key 集精确相等；行数精确等于
   `sum(max(n-1,0))`。
3. 每行 `actual_factor_ratio` 必须精确等于 `effective_factor / previous_factor`
   （Float64 恒等，无业务 rtol 放宽）。
4. 任一拓扑/行数/ratio/读取异常追加
   `CORPORATE_ACTION_FACTOR_MISMATCH` /
   `scoped factor transition topology mismatch`；继续收集其他 issue。
5. 保留既有 `verify_corporate_action_reconciliation_result`、receipt lineage、
   窗外 bar-span 与 `verify_g1_candidate`（frozen inputs）。
6. 版本保持：`m3-g1-tushare-mapper-v3` /
   `tushare_factor_daily_preclose_v3` / `m3-g1-manifest-v3`。

## 命令与退出码

环境：`D:\Miniforge3\python.exe`（Windows 反馈环，非 Linux Gate）。

```text
pytest tests/unit/test_m3_g1_candidate.py -q --tb=line
→ 49 passed, EXIT 0

ruff check src/quant/data/m3_g1_candidate.py tests/unit/test_m3_g1_candidate.py
→ All checks passed!, EXIT 0

mypy src/quant/data/m3_g1_candidate.py
→ Success: no issues found in 1 source file, EXIT 0

git diff --check -- <白名单三文件>
→ EXIT 0
```

## 对抗断言（矩阵映射）

1. 删除 `('000001.SZ', D0, D1)` evidence 并重绑 → topology mismatch；verify
   `IDENTITY_MISMATCH`。
2. `previous_factor_date` 改为非立即相邻日 → topology mismatch。
3. 增加 schema 合法但非 expected topology 的 evidence → topology mismatch。
4. 改写 `actual_factor_ratio`（同步 `declared_dividend_relative_error`，保持
   NO_EVENT rtol）→ 仍 topology mismatch；非仅 row-formula verify 失败。
5. 单 scoped factor → 0 transition，空 evidence，audit 通过。
6. 首末 bar 间停牌 session factor 形成两条 transition；删任一条均失败。
7. ADV3a：恢复窗外 factor → `FACTOR_INVALID`；verify `IDENTITY_MISMATCH`。
8. 合法 happy audit 通过；既有 no-event / membership 对抗未回退（全文件 49 绿）。

## 未验证 / 剩余风险

- 未跑正式 status / REFERENCE / PREPARE / PUBLISH / G2A、网络或真实凭据。
- 未跑 WSL Miniforge `base` / Linux Gate；Windows 绿测不等于 Gate。
- 本报告不等于独立复验；需另一全新只读会话写复验报告。
