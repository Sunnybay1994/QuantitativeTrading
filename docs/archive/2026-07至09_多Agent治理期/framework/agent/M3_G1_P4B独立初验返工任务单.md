# M3 G1-P4B：独立初验一次返工任务单

日期：2026-07-15  
状态：主 Agent 已复核独立初验否决项；返回原实现 Agent 返工，随后由全新外部会话复验  
原任务书：[`M3_G1_P4B跨源证据外部闭环任务单.md`](M3_G1_P4B跨源证据外部闭环任务单.md)  
实现交付：[`M3_G1_P4B跨源证据阻塞解除后交付报告.md`](M3_G1_P4B跨源证据阻塞解除后交付报告.md)  
独立初验：[`M3_G1_P4B跨源证据独立初验报告.md`](M3_G1_P4B跨源证据独立初验报告.md)

## 1. 返工范围

只允许修改：

- `src/quant/data/m3_reference.py`：收紧 `CrossSourceReconciliationBundle` 及其直接私有纯 helper；
- `tests/unit/test_m3_reference.py`：增加本任务单反例；
- 新增 `docs/M3_G1_P4B独立初验一次返工交付报告.md`。

不得修改 connector、P4A、RawStore、上游测试、配置、路线图或原有历史报告；不得改变公共字段或函数签名。

## 2. F1：同一 detail 上可伪造 summary/issues

### 现象

detail 含真实 mismatch 时，caller 可提供与该 detail digest 对齐、但把 mismatch/stats/issues/passed 写成全绿的
另一份自洽 summary；bundle 构造器接受。

### 根因

构造器只重建 caller 提供的 `field_stats/summary` 并核对 hash，没有从 detail 重新派生统计、问题和 passed。

### 应遵循规则

原任务书 §7.8 要求 bundle 从 detail 重算 digest/stats/summary digest/issues/passed。§8.9 仅把“整套
detail+summary 同时换成另一套真实自洽来源”的来源证明留给 `reconcile_cross_source`，不允许同一 detail 上撒谎。

### 最小复现

独立初验报告 ADV5：保留 mismatch detail 与真实 detail hash，伪造零 mismatch summary 及其真实 summary hash，
`issues=()`、`passed=True`，当前构造成功。

### 修复合同

用一个模块内纯 helper 同时供 `reconcile_cross_source` 和 bundle 构造器使用，避免两套统计语义。bundle 必须：

1. 验证 detail 精确 schema/dtype、3000 行、规范排序；键集合精确为
   `sample_plan.keys × (open,high,low,close,volume)`，每格恰好一次，拒 duplicate/extra/missing/wrong key/field；
2. 对每行验证 `missing_side`、null 组合、finite/nonnegative diff/tolerance、`matched` 与当前 summary 中 policy 数值的
   计算闭包；非法 List/Struct/Categorical 等不得冒泡底层 Polars 异常；
3. 从 detail 按唯一 `(symbol,trade_date)` 重算 `missing_primary_rows/missing_reference_rows`；`BOTH` 对两侧各计一行，
   INCOMPLETE 的 `count` 仍为两侧计数之和、evidence 为缺任一侧的排序唯一 key；
4. 重算 5 个 field stats、`mismatch_cells`、`mismatch_rate`、field max diff（无值为 `0.0`）；逐字段与 summary 精确比较；
5. 按 `mismatch_rate > max_mismatch_rate`（严格大于）重建两个冻结 issue 的精确 code/severity/message/count/evidence；
   caller issues 必须与重建结果完全相等，passed 与 summary.passed 必须等于“无重建 issue”；
6. 继续重算 detail/summary hash。浮点比较只可使用合同已有的精确值或明确的 `1e-12` rate 闭包，不放宽业务容差。

### 新增测试与通过条件

- 独立初验 ADV5 必拒；分别伪造 stats、missing row count、mismatch cells/rate、issue count/evidence/message、passed 必拒；
- detail 的 duplicate/extra/missing/wrong key/field、错误 dtype/null/missing_side/matched/tolerance/diff 必拒且只抛稳定
  `ValueError`，不泄露 raw 值或底层异常；
- 正常 reconcile bundle 和阈值等于/略超、缺行/停牌用例继续通过。

## 3. F2：跨源 issue 可使用 WARNING

### 现象与根因

构造器只验证两个 code，没有强制 `severity == "ERROR"`，因此自洽的 WARNING issue 可进入 bundle。

### 应遵循规则 / 最小复现

原任务书 §7.9 规定两个跨源 issue 均为 ERROR。独立初验 ADV9 已证明 WARNING 当前被接受。

### 新增测试与通过条件

两个 code 的 WARNING 分别必须被 bundle 拒绝；ERROR 正常通过；任意其他 code 仍拒绝。这里不修改共用
`G1QualityIssue` 的全局 severity 能力，只在跨源 bundle 语境收紧。

## 4. F3：主 Agent 同源复核发现的 bundle 可见闭包缺口

这不是扩大 P4B，而是把原任务书 §7.8 已冻结、且 bundle 自身已有输入可验证的闭包明确化：

1. `summary.primary_candidate_key == sample_plan.primary_candidate_key`；
2. `summary.sample_plan_sha256 == sample_plan.sample_plan_sha256`；固定 30/20/600/5/3000 继续闭合；
3. `reference_receipts` 精确 30 个、排序、request_id 唯一，且
   `summary.reference_receipt_digests == sorted(unique(stable_response_sha256))`；删一 receipt 或换 digest 必拒；
4. `summary.detail_sha256 == bundle.detail_sha256`。

`summary.primary_receipt_digests` 的原始 candidate 来源不在 bundle 字段中，仍由 `reconcile_cross_source` 和 P4C 原输入
重执行证明；不得伪称 bundle 能独立验证它。整套真实、自洽的另一来源 bundle 仍需由重执行区分。

必须增加每条闭包的单独漂移测试，并修正现有“删一 reference receipt 构造器可接受”的阶段性测试预期。

## 5. 验证和交付

实现者依次运行定向 P4B/P4A、全量 pytest、Ruff、mypy；全部通过后生成
`docs/M3_G1_P4B独立初验一次返工交付报告.md`，按 F1–F3 映射代码与新增测试，保留所有旧报告并互链。状态只能是
“待独立复验/待主验”。随后由未参与本轮返工的全新 Cursor 会话重放 ADV5/ADV9，并至少增加两个针对 F3 或 detail
schema 的新反例。复验通过前不得进入主 Agent 终验，不得声明 B4/G1/M3/Gate 通过。
