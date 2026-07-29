# M3 G1 P0K-A 交付报告（停止：必须扩大白名单）

状态：**已停止，未实现代码**

日期：2026-07-29（Asia/Shanghai）

实现模型：`cursor-grok-4.5-high`

基线：`f21de9331da43d4c5137a6a8da2d9be32f4e7229` / `cursor/g1-p0-rework-20260726`

## 结论

按任务书第 7 节，`G1BuildInputs` 必须新增

- `cninfo_dividend_responses`
- `cninfo_share_change_responses`

并与 v3 request plan 精确闭包。该构造变更会立刻破坏白名单外生产代码
`src/quant/data/m3_release.py` 的 `_consume_build_inputs`（显式按字段重建
`G1BuildInputs`，约 L2166–L2182）。任务书第 7 节同时要求
REFERENCE/PREPARE/PUBLISH 的 identity/receipt closure 同步适配 v3，而 release 路径正是
该闭包的生产入口。

按第 8 节硬约束：**不得自行扩大白名单**。因此停止实现，不改动任何生产/测试源码。

## 证据

1. 任务书 §7：`G1BuildInputs` 必须携带两个新 verified response tuple。
2. 任务书 §7：REFERENCE/PREPARE/PUBLISH 若依赖 request plan / receipt projection，必须适配 v3。
3. 白名单含 `m3_g1_candidate.py` / `g1_workflow.py`，**不含** `m3_release.py`。
4. 现网调用链：
   - `g1_workflow._build_inputs_from_state` → `G1ReleaseInputs(build_inputs=...)`
   - `m3_release._consume_build_inputs` 重建 `G1BuildInputs(...)` 时未列出新字段 →
     TypeError / 语义缺口。
5. 附属测试（亦不在白名单，但会随构造变更失败）：
   - `tests/unit/test_m3_g1_release.py`（显式 `G1BuildInputs(...)`）
   - `tests/unit/test_m3_backfill_requests.py`（硬编码 `m3-g1-request-plan-v2` /
     三参 `_plan_hash`）

## 建议白名单扩容（需主 Agent 冻结后再实现）

最小生产扩容：

```text
src/quant/data/m3_release.py
```

建议同步纳入定向回归测试（否则 PREPARE/PUBLISH 与 plan v3 无定向证据）：

```text
tests/unit/test_m3_g1_release.py
tests/unit/test_m3_backfill_requests.py
```

说明：任务书 §10 已写 `tests/unit/test_m3_backfill.py`，仓库现有文件名为
`test_m3_backfill_requests.py`；扩容时应明确是新建 `test_m3_backfill.py` 还是改名/
改写现有文件。

## 未改动文件

除本报告外，未修改任何白名单源码/测试。工作区既有 `docs/agent/*` modified 未暂存、
未归一化、未覆盖。

## 未运行

- 定向 pytest / ruff / mypy（无实现可验）
- WSL Gate、正式网络 HISTORY、1274 请求、P0K-B、G1 Gate

## git

实现 Agent 仅提交本停止报告；不宣布 P0K-A / Gate 通过。
