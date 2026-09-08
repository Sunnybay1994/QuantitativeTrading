# M3 G1 P0D-R1：audit 与 scoped reconciliation 拓扑绑定返工任务单

- 冻结日期：2026-07-27
- 前置实现：`8e53d05 Complete G1 P0D scoped factor publication`
- 否决证据：`2a7d9a4 Review G1 P0D scoped factor publication`
- 实现：全新外部 `cursor-grok-4.5-high` 会话
- 复验：另一全新、未参与 R1 实现的 `cursor-grok-4.5-high` 会话
- 环境：Windows 原生 Miniforge 仅作反馈环；不宣称 Linux Gate

## 1. 现象—根因—规则—最小复现—通过条件

| 项 | 冻结内容 |
|---|---|
| 现象 | 从合法 candidate 删除一条 scoped factor transition 对应的 `corporate_action_reconciliation` 行，重算该表 digest、全部 table digests 和 `primary_candidate_key` 后，`audit_g1_candidate` 仍 `passed=True`、`issues=[]` |
| 根因 | audit 仅验证 reconciliation Schema、表 digest、行内公式和 receipt lineage；没有从 candidate 自带的 scoped `adjustment_factors` 重建相邻 transition 拓扑 |
| 应遵循规则 | P0D §2.1/§2.2：audit、publish 与 reconciliation 必须消费同一 scoped factor 语义；reconciliation 行数精确等于 `sum(max(n-1,0))`，每行必须对应同 symbol 的立即相邻 factor transition |
| 最小复现 | `build_g1_candidate(happy)` → 删除 `('000001.SZ', 2016-02-01, 2016-02-02)` evidence → 重绑自包含身份 → 当前 audit 通过 |
| 通过条件 | 删除、增加或改写 transition evidence 并重绑身份后 audit fail-closed；合法 candidate 与既有 P0D/P0 测试继续通过 |

## 2. 冻结实现合同

在 `audit_g1_candidate` 内仅使用 candidate 自带表完成以下闭包；不得给 audit 新增
`G1BuildInputs` 参数，不得把本检查推给 `verify_g1_candidate`：

1. 按 `symbol,effective_date` 对 `candidate.adjustment_factors` 排序。
2. 对每个 symbol 重建所有立即相邻 transition：
   `(symbol, previous_factor_date, effective_date)`。
3. expected key 集合必须与
   `candidate.corporate_action_reconciliation` 的同三字段 key 集合精确相等：
   不得缺行、增行、跳过中间 factor 或把 previous date 指向非立即相邻日。
4. expected 行数必须精确等于
   `sum(max(scoped_factor_rows_per_symbol - 1, 0))`。
5. 每条 evidence 的 `actual_factor_ratio` 必须精确等于
   `effective_factor / previous_factor`；两边均来自已验证 Float64 candidate 表，
   不用业务 rtol 放宽身份绑定。
6. 任一拓扑、行数、ratio 或读取异常都追加稳定 issue：
   `code="CORPORATE_ACTION_FACTOR_MISMATCH"`，message 明示
   `scoped factor transition topology mismatch`；audit 继续收集其他 issue，
   不抛出未封装异常。
7. 现有 `verify_corporate_action_reconciliation_result`、receipt lineage、
   窗外 factor bar-span 检查和 frozen-input `verify_g1_candidate` 均保留。

本轮是对已冻结 v3 audit 合同的缺陷修复，不改变发布表内容、mapper 或 reconciliation
生成算法，因此保持：

- `m3-g1-tushare-mapper-v3`
- `tushare_factor_daily_preclose_v3`
- `m3-g1-manifest-v3`

源码树变化仍会自然改变 `build_code_version` 与新正式 identity；不得保留旧 key。

## 3. 文件白名单

外部实现仅可写：

- `src/quant/data/m3_g1_candidate.py`
- `tests/unit/test_m3_g1_candidate.py`
- `docs/framework/agent/M3_G1_P0D-R1_audit与reconciliation拓扑绑定返工交付报告.md`

外部独立复验唯一可写：

- `docs/framework/agent/M3_G1_P0D-R1_audit与reconciliation拓扑绑定独立复验报告.md`

其余生产代码、测试、配置、正式 data/raw/journal/receipt、路线图只读。实现与复验
必须是不同全新会话。

## 4. 必测矩阵

至少覆盖：

1. 删除一条合法 evidence，重绑 table digest/primary → audit 返回
   `CORPORATE_ACTION_FACTOR_MISMATCH`。
2. 把一条 evidence 的 `previous_factor_date` 改为同 symbol 的非立即相邻 factor 日，
   重绑身份 → audit 失败。
3. 增加一条 schema 合法但不属于 expected topology 的 evidence，重绑身份 → audit 失败。
4. 改写 `actual_factor_ratio` 并同步所有能同步的自包含字段与身份 → audit 仍因 factor
   ratio 绑定失败。
5. symbol 只有一个 scoped factor 时 expected transitions 为 0，空 evidence 合法。
6. 首末 bar 之间的停牌 session factor 形成两条相邻 transition；删任一条均失败。
7. P0D ADV3a 保持：恢复窗外 factor 并重绑后，audit 仍因 bar-span 失败；
   `verify_g1_candidate` 仍从 frozen inputs 拒绝。
8. 合法 happy candidate audit 通过；既有 no-event jump、event proof、membership
   对抗不得回退。

## 5. 禁止项

- 修改 scope 投影、reconciliation 生成算法、mapper/manifest/method 版本；
- 给 audit 注入 frozen inputs 或用 verify 兜底；
- 放宽 factor rtol、恢复任意 jump 的 `NO_EVENT_STABLE_FACTOR`；
- symbol/date 特例；
- 正式 status/reference/prepare/publish/G2A、网络或真实凭据；
- reset/checkout、批量换行、修改任务书外文件；
- 用 Windows 绿测宣称 G1/Codex/Linux Gate 通过。

## 6. 自验

```text
D:\Miniforge3\python.exe -m pytest tests/unit/test_m3_g1_candidate.py -q --tb=line
D:\Miniforge3\python.exe -m ruff check \
  src/quant/data/m3_g1_candidate.py tests/unit/test_m3_g1_candidate.py
D:\Miniforge3\python.exe -m mypy src/quant/data/m3_g1_candidate.py
git diff --check -- \
  src/quant/data/m3_g1_candidate.py tests/unit/test_m3_g1_candidate.py \
  docs/framework/agent/M3_G1_P0D-R1_audit与reconciliation拓扑绑定返工交付报告.md
```

实现报告记录实际命令、退出码、对抗断言和未验证项；不得宣布 Gate。实现提交后，
由另一全新会话逐项复验并新增至少一个“删除停牌中间 factor 的一侧 evidence”或
“保持行数但交换 previous date”的反例。复验 FAIL 时继续返回实现返工，不进入主验。
