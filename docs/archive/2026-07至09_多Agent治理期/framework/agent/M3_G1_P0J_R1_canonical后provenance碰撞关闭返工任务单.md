# M3 G1 P0J-R1：canonical 后 provenance 碰撞关闭返工任务单

状态：**冻结，待外部返工实现 → 外部独立复验**

日期：2026-07-29（Asia/Shanghai）

返工基线：`af76cee`（P0J 独立初验 FAIL 报告）

上游实现：`f467c1a`

权威任务书：
[`M3_G1_P0J_Tushare分红跨end_date精确重复折叠返工任务单.md`](M3_G1_P0J_Tushare分红跨end_date精确重复折叠返工任务单.md)

失败证据：
[`M3_G1_P0J_Tushare分红跨end_date精确重复折叠独立初验报告.md`](M3_G1_P0J_Tushare分红跨end_date精确重复折叠独立初验报告.md)

## 1. 目标和冻结裁定

只关闭 P0J 独立初验发现的一个 provenance 洗白路径：

- 跨 `end_date` exact 簇 canonical 到最大 `end_date` 后；
- 若与该 canonical `end_date` 下另一候选具有相同 version rank 和 decision fields；
- 但两者的“除 `end_date` 外全部正式字段身份”不同；
- 必须稳定抛出 `G1_CORPORATE_ACTION_VERSION_CONFLICT`，不得累加 `raw_row_count`、不得静默生成一个事件。

本轮选择 **fail-closed**，不尝试生成两个 ledger 事件。原因：

1. 两候选 canonical 后的现有 `event_id` 经济字段完全相同，强行保留两事件会产生身份碰撞或要求扩大哈希/
   Schema 合同；
2. 正式冻结数据扫描确认当前 637 个 dividend response、26,409 行中
   `post_canonical_candidate_identity` 碰撞为 `0`，因此 fail-closed 不改变当前正式事件集；
3. provenance 不一致且缺少供应商版本排序信号时，拒绝比猜测哪个候选正确更符合既有冲突语义。

P0J 的 selection version 保持：

```text
tushare_dividend_cninfo_rights_capital_iso_date_cross_end_exact_fold_v6
```

v6 尚未通过独立初验和主验，本次是在同一冻结语义内补齐实现，不升级 v7。

## 2. 现象—根因—规则—最小复现—新增测试—通过条件

### 2.1 现象

三行输入：

```text
A1 = end_date=20241231, base_share=100, 其余正式字段相同
A2 = end_date=20251231, base_share=100, 其余正式字段相同
B  = end_date=20251231, base_share=101, 其余 rank/decision 字段相同
```

当前实现先把 A1/A2 exact 折叠并 canonical 到 `20251231`，随后 A 与 B 落入同一经济 group。
`_fold_identical_candidates` 只比较 version rank + decision fields，又把 A/B 合并，输出
`ledger.height=1`、`evidence.height=1`、`raw_row_count=3`。

### 2.2 根因

`_fold_dividend_cross_end_exact_duplicates` 已正确区分 A/B 的 exact identity，但其输出 wrapper 没有把该身份
传给后续 candidate folding。canonical 改写 `end_date` 后，后续较窄的 candidate identity 覆盖了前一层
provenance 区分。

### 2.3 应遵循规则

- cross-end exact fold 的输出必须携带可比较的 exact identity；
- `_fold_identical_candidates` 只有在 version rank、decision fields、exact identity 三者都相同时才累计
  `raw_row_count`；
- version rank 相同、decision fields 相同、exact identity 不同时抛
  `G1_CORPORATE_ACTION_VERSION_CONFLICT`；
- version rank 相同、decision fields 不同仍沿用既有
  `G1_CORPORATE_ACTION_VERSION_CONFLICT`；
- 不用 factor、行情、证券/日期白名单或输入顺序解决冲突。

同一 `end_date` 下出现相同 rank/decision 但 `base_date`、`base_share` 或其他正式 provenance 字段不同时，
也执行相同 fail-closed 语义。这样 canonical 前后只有一套候选冲突规则。

### 2.4 新增测试

至少增加：

1. A1+A2+B 最小复现，精确断言 `G1_CORPORATE_ACTION_VERSION_CONFLICT`；
2. 只有 A1+A2 时仍折为一个事件，canonical max，`raw_row_count=2`；
3. 同 `end_date`、同 rank/decision、仅 `base_share` 不同，精确断言同一冲突码；
4. 同 `end_date` 的完全 exact duplicate 仍累加 `raw_row_count`；
5. 输入顺序反转后冲突码不变；
6. 既有 600733、600930、null≠0、provenance 两行阻断、版本冲突、对账只计一次和 v6 钉扎继续通过。

### 2.5 通过条件

- A∪B 不再静默合并；
- 冲突发生在 selection，错误码稳定且不暴露原始值；
- exact identity 只用于内部选择，不新增 Schema、公开字段或旁路 digest；
- P0J 既有成功路径和 CNINFO rights 不退化；
- 改动、测试和报告严格在白名单内且 `git diff --check` 通过。

## 3. 正式数据证据

零网络 ignored 诊断：

`artifacts/g1_component_diag_20260722/scan_dividend_end_date_collisions_p0j.json`

本轮在实现提交 `f467c1a` 上重新验证 637 个正式 dividend response：

```text
response_count=637
raw_row_count=26409
exact_except_end_date=11
implementation_identity=12
post_canonical_candidate_identity=0
```

该统计只用于证明 fail-closed 规则不会击中当前正式响应；生产实现不得读取该产物或硬编码计数。

## 4. 实现约束

- 最小修复现有 `_fold_dividend_cross_end_exact_duplicates` 与 `_fold_identical_candidates` 数据传递和冲突检查；
  不建立第二套 selector。
- exact identity 必须复用 P0J 已冻结的 `_dividend_cross_end_exact_identity`，不得复制另一套字段 tuple。
- 不把 exact identity 写入 ledger/evidence Schema；raw snapshot 和 selection result digest 闭包保持现状。
- 不改变 canonical `max(end_date)`、event/candidate/economic-key 哈希公式或标签。
- 不修改 selection version、mapper、reconciliation、candidate/planning/release/workflow/CLI/config/connector。
- 零网络；不运行正式 full status，不改正式 data/raw/receipt/journal 或 ignored artifacts。
- 发现正式代码无法在不改公共身份的情况下稳定冲突时，停止扩大并报告证据。

## 5. 文件白名单

生产：

- `src/quant/data/m3_execution_facts.py`

测试：

- `tests/unit/test_m3_execution_facts.py`

文档：

- 唯一新报告：
  `docs/framework/agent/M3_G1_P0J_R1_canonical后provenance碰撞关闭返工交付报告.md`

禁止修改上游任务书、上游交付/初验报告、其他生产代码、其他测试和其他文档。工作区已有 modified docs 保留
未暂存。

## 6. 实现 Agent 验证

Windows 原生反馈环：

```powershell
D:\Miniforge3\python.exe -m pytest `
  tests/unit/test_m3_execution_facts.py `
  -k "dividend or corporate_action_selection or reconciliation or version_constants" -q

D:\Miniforge3\python.exe -m ruff check `
  src/quant/data/m3_execution_facts.py `
  tests/unit/test_m3_execution_facts.py

D:\Miniforge3\python.exe -m mypy src/quant/data/m3_execution_facts.py

git diff --check af76cee HEAD -- `
  src/quant/data/m3_execution_facts.py `
  tests/unit/test_m3_execution_facts.py `
  docs/framework/agent/M3_G1_P0J_R1_canonical后provenance碰撞关闭返工交付报告.md
```

实现者只提交三个白名单文件和压缩交付报告，不宣称独立初验、主验、正式 status 或 Gate 通过。

## 7. 独立复验

返工后由未参与 R1 实现的另一全新 `cursor-grok-4.5-high` 会话执行。生产代码、测试和既有报告只读，唯一
允许写：

`docs/framework/agent/M3_G1_P0J_R1_canonical后provenance碰撞关闭独立复验报告.md`

复验必须：

1. 复跑 A∪B canonical 碰撞并精确确认 `G1_CORPORATE_ACTION_VERSION_CONFLICT`；
2. 新增实现者未使用的辅助字段碰撞，例如 `base_date` 或 `cash_div` 不同但 rank/decision 相同；
3. 确认同 end 完全 exact duplicate 仍正常累计，而 provenance 不同不会被计入同一 `raw_row_count`；
4. 复核 600733/600930/null≠0/输入顺序/v6；
5. 检查白名单、零网络、Ruff、mypy、定向 pytest 和本轮 diff hygiene；
6. 只给 PASS，或按完整返工六要素给 FAIL；不修改生产代码和实现者测试。

复验 PASS 后才进入主 Agent 的 Windows/WSL 定向测试、正式 637-response 零网络 selection/status 和下一首败
裁定。
