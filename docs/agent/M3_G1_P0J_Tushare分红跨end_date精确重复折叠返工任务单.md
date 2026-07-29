# M3 G1 P0J：Tushare 分红跨 `end_date` 精确重复折叠返工任务单

状态：**冻结，待外部实现 → 外部独立初验**

日期：2026-07-29（Asia/Shanghai）

实现基线：`f34e3c6`

上游主验：
[`M3_G1_P0I_停牌除权复牌日因子延迟闭包主Agent最终验收报告.md`](M3_G1_P0I_停牌除权复牌日因子延迟闭包主Agent最终验收报告.md)

正式首败：
[`20260729_P0I后正式status首败_600733有事件declared不合.md`](20260729_P0I后正式status首败_600733有事件declared不合.md)

## 1. 目标与不变量

只修复 Tushare `dividend` 同一实施记录被多个 `end_date` 重复投影、进而在除权日重复累加现金或送股腿的问题。

必须同时保持：

1. 只有“除 `end_date` 外全部正式输出字段相同”的跨 `end_date` 行才折叠为一个经济事件；
2. `end_date` 不同但其他任一字段不同的记录仍是不同事件；特别是正式 `600930.SH` 两条不同
   `ann_date` 的同日分红必须继续生成两个 `event_id`；
3. 不使用复权因子、行情、停牌、证券代码白名单或日期硬编码决定 selection；
4. 原始 response、receipt、snapshot 和 raw 不改写；selection 只产生新的派生语义；
5. dividend event/evidence 身份闭包、CNINFO rights、P0E/P0F/P0H/P0I、no-event fail-closed 和对账容差不变；
6. 选择语义变化必须升级 selection version，并自然触发 build/candidate/reference/release 身份漂移。

非目标：不修复 P0J 之后可能出现的下一正式首败；不重抓 HISTORY；不启动 REFERENCE/PREPARE/PUBLISH；
不改 reconciliation 公式或容差；不扩展到其他 Tushare endpoint 或 CNINFO。

## 2. 现象—根因—规则—最小复现—通过条件

### 2.1 现象

正式冻结响应中 `600733.SH / ex_date=20180919` 有两条 `div_proc=实施`：

- `end_date=20180823`
- `end_date=20180201`

两行的 `ann_date`、`imp_ann_date`、送转/现金腿、登记日、除权日、上市日、`base_date` 和 `base_share`
全部相同。当前选择器因 economic key 包含 `end_date` 而生成两个事件，得到 `stock_ratio=5.0`、
declared factor `6.0`；正式 adj factor 实际为 `8.192 / 2.34 = 3.5008547008547013`。单条
`stock_ratio=2.5` 的 declared factor `3.5` 在既有 `rtol=0.001` 内匹配。

### 2.2 根因

当前实现把 `end_date` 无条件视为经济事件身份。Tushare 官方合同将该字段定义为“分红年度”，并不保证同一
实施动作只归属一个值。供应商对同一实施事实给出多个年度投影时，现有逻辑把投影数量误当作经济动作数量。

### 2.3 应遵循规则

对于同一 verified dividend response：

- 先按本任务 §3 的“跨年度精确重复身份”聚合；
- 聚合中出现多个不同 `end_date` 时，它们只代表一个实施事件；
- canonical `end_date` 固定取聚合内按日期升序的最大值。该规则只用于稳定身份，不声称最大值是新的公告日；
- 聚合的全部原始行数进入最终候选的 `raw_row_count`；
- 若除 `end_date` 外任一字段不同，则不得进入同一精确重复聚合，继续走既有经济事件分组、版本排序和冲突
  fail-closed。

不得按“同 symbol/ex/cash/stock”宽松去重，也不得按 factor 是否能对上来反向选择事件。

### 2.4 最小复现

1. `600733` 形状：两行只有 `end_date` 不同，其余字段完全相同。预期一个 ledger 事件、一个 selected
   evidence，canonical `end_date=max(end_date)`，`raw_row_count=2`。
2. `600930` 形状：两行 `end_date` 不同，且 `ann_date` 不同，其余实施字段相同。预期仍为两个 ledger
   事件、两个 selected evidence、两个不同 `event_id`。
3. 三个 `end_date` 的精确重复行加任意输入顺序。预期结果和两个内容 digest 顺序无关，
   canonical `end_date` 为最大值，`raw_row_count=3`。

### 2.5 通过条件

- 上述三个最小复现全部通过；
- 600733 形状送股只计一次，并能通过现有 declared-factor 路径；
- 600930 既有双事件闭包继续通过；
- 任意 provenance/实施字段差异均阻止跨 `end_date` 折叠；
- 选择结果仍通过 Schema、digest 和 ledger↔evidence closure；
- selection version 精确升级，旧 v5 不能冒充当前产物。

## 3. 冻结的精确重复身份

只比较 `div_proc=实施`、`ex_date` 在 history window 内且已通过既有事件合法性检查的行。

跨年度精确重复身份包含 Tushare dividend 当前正式输出的全部字段，**唯独排除 `end_date`**：

1. `ts_code`
2. `ann_date`
3. `div_proc`
4. `stk_div`
5. `stk_bo_rate`
6. `stk_co_rate`
7. `cash_div`
8. `cash_div_tax`
9. `record_date`
10. `ex_date`
11. `pay_date`
12. `div_listdate`
13. `imp_ann_date`
14. `base_date`
15. `base_share`

比较语义：

- 日期沿用 Tushare `YYYYMMDD` 严格解析；nullable 日期保留 `null`；
- 数值沿用现有 strict finite scalar 语义；nullable 辅助字段保留 `null`，不得把 `null` 与显式 `0` 当作
  精确相同；
- current decision leg 仍沿用既有 `_parse_dividend_leg_amount` 语义，不改变空腿合同；
- 不复制 endpoint 字段列表为新的 SSOT；实现应在当前 selector 内以最小窄 helper 表达该身份；
- `base_date/base_share` 仅用于证明两个 raw 投影是否完全相同，不进入经济金额或因子公式。

聚合计数必须兼容既有同 `end_date` exact duplicate folding：最终 `raw_row_count` 是所有被折叠原始行的总数，
不得只计不同 `end_date` 数量。

## 4. 正式证据和反例

零网络诊断产物（均在既有 ignored `artifacts/g1_component_diag_20260722/`）：

- `inspect_600733_p0j.json`
- `inspect_600930_p0j.json`
- `scan_dividend_end_date_collisions_p0j.json`
- `validate_exact_end_date_collisions_p0j.json`

冻结数据结论：

- 637 个 dividend response、26,409 行中共有 11 组“仅 `end_date` 不同”的精确碰撞；
- 另有且仅有 1 组实施身份相同但不精确相同的碰撞，即 `600930.SH`，其两行 `ann_date` 不同；
- 11 组中 8 组在除权日有直接 adj-factor transition；重复累加方案 0/8 在 `rtol=0.001` 内匹配；
- 其中 6/8 的单事件方案直接匹配；另 2 组存在同日其他公司行动或仍需后续正式对账裁定，不能据此把重复
  投影恢复为多事件；
- `600733` 单事件误差约 `0.0002442`，重复事件误差约 `0.4165242`；
- `600930` 两行 `ann_date` 分别为 `20260108`、`20260124`，必须保留为两事件。

以上因子证据只验证任务合同，不允许进入生产 selection 决策。

## 5. 版本与身份传播

`G1_CORPORATE_ACTION_SELECTION_VERSION` 从：

```text
tushare_dividend_cninfo_rights_capital_iso_date_v5
```

精确升级为：

```text
tushare_dividend_cninfo_rights_capital_iso_date_cross_end_exact_fold_v6
```

约束：

- dividend `_economic_event_key_sha256`、`_candidate_id_sha256`、`_event_id_sha256` 的哈希字段公式和标签不变；
- canonical 行继续用其 canonical `end_date` 生成既有 event/evidence 身份；
- selection version 必须在生产常量和版本钉扎测试中同步；
- mapper、reconciliation、planning schema、manifest 和 table schema 本轮不升级；
- build code version、primary candidate key、REFERENCE 抽样和 release identity 的自然漂移是预期行为，不得
  为复用旧 journal 保留 v5 或伪造旧 key。

## 6. 实现约束

- 优先在 `select_g1_corporate_actions` 进入既有 `groups` 前完成窄化的精确折叠；不得建立第二套 selection。
- 输入顺序不得影响 canonical 行、rank、digest 或 ledger。
- 精确重复折叠后，既有同经济事件多公告版本排序、冲突检测、Schema 验证和 closure 仍是唯一后续路径。
- 不增加配置旋钮、证券特例、日期特例、factor 查询或网络调用。
- 不修改 raw、receipt、journal、正式 data 或 ignored 诊断脚本。
- 默认开发和测试零网络；外部 Agent 不运行 full formal status。
- 发现 frozen fingerprint 无法同时保留 600930 或与现有 Schema 冲突时，停止扩大并写证据，由主 Agent
  重新冻结，不自行改变身份字段。

## 7. 文件白名单

生产：

- `src/quant/data/m3_execution_facts.py`

测试：

- `tests/unit/test_m3_execution_facts.py`

文档：

- 唯一新交付报告：
  `docs/agent/M3_G1_P0J_Tushare分红跨end_date精确重复折叠返工交付报告.md`

禁止修改本任务书、Schema、candidate/planning/release/workflow/CLI、配置、connector、其他测试和其他文档。
若确需白名单外文件，停止并报告具体接口证据。

## 8. 必须新增或修订的测试

至少覆盖：

1. 600733 形状两行折为一事件、max `end_date`、`raw_row_count=2`；
2. 三 `end_date` + 反向/乱序输入，ledger/evidence digest 完全一致；
3. 原始完全重复与跨 `end_date` 重复同时存在时，`raw_row_count` 为总原始行数；
4. 600930 形状用不同 `ann_date` 明确保留两事件；修订既有
   `test_dividend_distinct_end_dates_same_ex_fields_pass_closure`，使“不同经济事件”的证据不再只依赖
   `end_date`；
5. 分别改变 `imp_ann_date`、任一现金/送转字段、pay/list、`base_date`、`base_share`，均不得被精确折叠；
6. 600733 形状接入现有 reconciliation 最小 fixture 时只累加一次并通过；
7. 版本常量精确为 v6，v5 断言失败；
8. 既有版本冲突、空腿、缺 `ex_date`、event-id closure、CNINFO rights 定向回归不退化。

测试不得通过硬编码正式证券代码进入生产逻辑；测试 fixture 可在 docstring 中注明来自哪个正式失败形状。

## 9. 实现 Agent 验证

Windows 原生反馈环：

```powershell
D:\Miniforge3\python.exe -m pytest `
  tests/unit/test_m3_execution_facts.py `
  -k "dividend or corporate_action_selection or reconciliation or version_constants" -q

D:\Miniforge3\python.exe -m ruff check `
  src/quant/data/m3_execution_facts.py `
  tests/unit/test_m3_execution_facts.py

D:\Miniforge3\python.exe -m mypy src/quant/data/m3_execution_facts.py

git diff --check f34e3c6 HEAD -- `
  src/quant/data/m3_execution_facts.py `
  tests/unit/test_m3_execution_facts.py `
  docs/agent/M3_G1_P0J_Tushare分红跨end_date精确重复折叠返工交付报告.md
```

实现者只回传压缩交付报告和必要摘要，不回传完整日志。自测通过不等于 Gate 通过。

## 10. 独立初验要求

由未参与实现的另一全新 `cursor-grok-4.5-high` 会话执行，只能写唯一报告：

`docs/agent/M3_G1_P0J_Tushare分红跨end_date精确重复折叠独立初验报告.md`

独立初验必须：

1. 逐项核对 §2、§3、§5、§8；
2. 自建实现者未使用的“同 ex/同金额但 `ann_date` 不同”反例，证明不会宽松折叠；
3. 自建“同一 exact cluster 中 end_date 顺序和原始行重复数变化”反例，证明 deterministic 和计数闭包；
4. 尝试改变 `base_share` 后同步重算 result digest，确认不会伪装成同一 folded candidate；
5. 核对 diff 白名单、旧 v5 字面量、`git diff --check` 和无网络事实；
6. 结论只能是 PASS 或按“现象—根因—规则—最小复现—新增测试—通过条件”给出 FAIL。

初验 PASS 后，主 Agent 才执行 WSL base 定向测试、正式 637-response 零网络 selection/status 和下一首败裁定。
