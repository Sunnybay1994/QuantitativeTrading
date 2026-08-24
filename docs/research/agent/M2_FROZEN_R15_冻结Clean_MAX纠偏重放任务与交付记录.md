# M2-FROZEN-R15 冻结 Clean MAX 纠偏重放任务与交付记录

## 1. 任务身份

- 任务 ID：`M2-FROZEN-R15`
- owner：投研领域经理
- 状态：`FROZEN`
- exact base：`39f7969e5a066a0b333b192c5a02ee28800c5349`
- branch：`codex/m2-frozen-r15-max-corrective-replay`
- worktree：`artifacts/dev_worktrees/m2-frozen-r15-max-corrective-replay`
- trial delta：`0`，仅为既有 MAX trial 的 corrective replay
- 结论上限：`RESEARCH_ONLY`；任一门禁失败为 `REJECTED`

本任务只纠偏重放既有 MAX 彩票偏好 lineage，不新增因子，不改写历史 run，不进入 forward、S2、PAPER 或
任何交易路径。

## 2. 冻结假设与不可变输入

- 因子：`max_daily_return_20`，即 20 个严格连续 exchange sessions 中最大的有符号日简单收益；
- 经济方向：`-1`，高 MAX 表示彩票偏好，低 MAX 优先；
- snapshot：`b79a7b5e66dee0ae439c030078414157ca6c1f3b6ce7fbe5e36ff3910c1089d2`；
- universe/portfolio：2019 年 Top800 冻结池、Top50、等权；
- 研究设计：3 folds、20-session rebalance、`close as_of -> next-session open`；
- 成本压力：`0.5x / 1x / 2x`；
- 既有 coverage、RankIC、redundancy、方向一致性和正 2x 成本门槛全部保持；
- 成本配置当前 canonical `[costs]` semantic SHA-256：
  `b2041d8495aa408de0bd264d6c03eb7e4d174e03f120289bc8471cbb5ea0a959`。

历史 run `10dea14f1fcbbbeb78871cddb7b00cd06d77cf005c3a776c4713f5a4f4129bb3` 保持 immutable/HOLD；
不得覆盖、改状态或作为修复后的 promotion 证据。

若公式、方向、universe、fold、成本经济值、阈值、snapshot 或 signal/execution timing 任一漂移，立即 STOP；
不得继续以 `trial_delta=0` 运行。

## 3. 本包关闭的边界

### 3.1 R12 后的新 lineage

新 run 必须使用已合流的 R12 outcome cohort 与持仓收益漂移语义。旧 targets、NAV、turnover、成本或分组证据
不复用、不回写。

### 3.2 主配置与成本语义身份

1. classic 主 config 只读取一次；同一内存 payload 完成 TOML parse 与 raw SHA-256；
2. cost TOML 只读取一次；同一 payload 完成严格 parse、period 构造与 canonical semantic SHA-256；
3. `[portfolio].cost_schedule_semantic_sha256` 必须是 exact 64 位小写十六进制，并在任何 snapshot verifier、
   repository 读取或 artifact 目录创建前与实际摘要比对；
4. 后续评估复用已绑定的 cost periods，不得重读；
5. `run.inputs` 第一项必须是
   `ResearchInputDigestV1(name="a-share-cost-schedule", rows=len(periods), min_date=None, max_date=None,
   content_sha256=semantic_sha)`；既有 market-data inputs 保持原相对顺序；
6. 注释、EOL、TOML 等价 Decimal 拼写及 `[costs]` 外 section 变化不得改变 semantic SHA；任何 `[costs]`
   经济语义变化必须改变摘要或稳定拒绝。
7. 只有已验证为 fifth/MAX R15 的主配置才执行 raw payload identity：冻结 Windows payload SHA-256 为
   `860ca0ef600dd4de107f5e60dc8593cbb03ca6c7a3cac0cad0adf2d56a778c9f`；任何字节漂移（包括注释、snapshot、
   universe、fold 或 admission bytes）均须在 cost binding、data/snapshot 读取和 artifact 创建前 STOP，
   不复制参数表，版本化 config 继续作为参数 SSOT；非 fifth classic 保持 base cost identity/read timing。

### 3.3 primary horizon=20 五组单调性

只使用 R12 已冻结的 signal cohort/group membership 与 outcome coverage evidence：

1. 仅 `period="test"`、`horizon=20` 参与门禁；1/5 日只作诊断；
2. 每个预注册 test signal date 必须精确存在 group 1..5 五行，且每行 coverage 为 `PASS`、观测数满足既有
   minimum-symbol 合同、收益为 finite；缺日期、缺组、重复组、非有限或 coverage 非 PASS 均整次 fail-closed；
3. 每个日期内先使用既有固定组成员的等权 holding return；fold 内每组再对全部预注册日期等权平均；
4. classic score 为 `factor * direction`，group 按 score 升序；固定方向 `-1` 时 group1 为高 MAX、
   group5 为低 MAX，低 MAX 优胜的 fold 通过条件为 `group1 <= group2 <= group3 <= group4 <= group5`；
   禁止容差、平滑、事后重排或选择子区间；证据字段使用 `*_le_*`。
5. 三个 test folds 至少 `2/3` 通过；同时把三个 fold 的全部预注册 test 日期合并后，按同一“日期等权”口径
   计算 pooled group 1..5，pooled 也必须非递减；
6. fold 与 pooled 的五组均值、逐相邻比较和 pass 状态进入可验证输出/summary；最终 admission 必须真实消费该
   gate，不能只生成诊断表。

本包不关闭 PIT 的对称 redundancy coverage、audit-v4、R3 或财务 version Gate。

## 4. exact 写白名单

1. `src/quant/research/run_classic_factors.py`
2. `configs/research/m2_classic_daily_factors_fifth_batch.toml`
3. `tests/unit/test_run_classic_factors.py`
4. `docs/research/M2_MAX彩票偏好因子假设卡.md`
5. `docs/research/M2_MAX彩票偏好因子R15纠偏重放结果.md`（仅唯一真实 run 后新增）
6. `docs/research/README.md`（仅索引 hunk）
7. `docs/research/agent/M2_FROZEN_R15_冻结Clean_MAX纠偏重放任务与交付记录.md`
8. `docs/research/roadmaps/M2_策略与因子库并行建设路线图.md`（仅状态/证据 hunk）

禁止修改 factor 实现、Schema、repository、publisher、facade、`run_daily*`、PIT、依赖或新增 runner/import 边；
禁止读取 `data/raw/`、`data/run_state/`、`data/clean/tushare_financials/`、ledger 或 partial financial raw；禁止
修改 shared governance、integration 或 finance writer。

## 5. 必须覆盖的反例

1. 主 config 或 cost payload 被读取第二次即测试失败；读取后磁盘漂移不改变本次 parse/hash/periods；
2. expected cost SHA 缺失、格式错误、大写或不匹配，在 snapshot verifier 和 artifact mkdir 前拒绝；
3. cost 注释/EOL/等价 Decimal 拼写变化摘要不变；任一 `[costs]` 经济字段变化摘要改变；
4. MAX 在 redundancy pair 的任一侧都不得绕过本包自身既有门禁；本包不宣称关闭 PIT 对称 coverage；
5. 任一 test fold 的任一预注册日期缺 group、重复 group、coverage 非 PASS、收益非有限，最终结果稳定拒绝；
6. 只有 1/3 folds 单调、2/3 folds 单调但 pooled 不单调、pooled 单调但少于 2 folds 单调，均拒绝；
7. 恰好 2/3 folds 且 pooled 非递减通过单调门禁；相邻组相等允许通过；
8. horizon 1/5 结果变化不改变 primary gate；未选中证券 outcome 变化不得改变固定 group membership；
9. 历史 run 目录存在时不得覆盖；新 run 只能发布到新的不可覆盖 lineage。

## 6. 验证与资源合同

顺序执行：

1. focused `tests/unit/test_run_classic_factors.py`（含直接相关 MAX 节点）；
2. Ruff：改动生产文件与测试；
3. mypy：改动生产文件；
4. cold import、TOML、cost identity 与 cached diff-check；
5. 开发检查全绿后，唯一一次真实 `RESEARCH_ONLY` run；
6. public verifier、run outputs closure、结果文档和 no-clobber canonical retained。

真实运行仅 Windows 单实例，`BelowNormal`、affinity `0xF00`（CPU8-11）、数值线程 `<=2`；不得与其他
`0xF00` 任务并发，finance writer 的 `0x3` 不受影响。不跑全量测试、PIT、网络或 PAPER。

## 7. STOP 与交付

- 白名单不足、合同冲突、冻结输入漂移、验证失败或资源冲突时立即停止，不自行扩边界或重复真实 run；
- 实现 Worker 只提交 source SHA、exact paths、压缩验证证据、run/retained 状态和残余风险；
- 独立初验必须由未参与实现的隔离上下文执行，并增加至少一个实现者未使用的对抗反例；
- 领域经理主验后向统筹申请 merge-tree/no-ff 合流；worktree 与 branch 由统筹 archive-first 退休。

## 8. 交付记录

### Worker 实现交付（P1/P2 返工开发检查完成）

- 状态：`DELIVERED / SELF-VERIFIED`，等待未参与实现的独立初验；结论上限仍为
  `RESEARCH_ONLY`，本记录不宣称任何 Gate 已最终关闭。
- parent：`e2a5fcbfb3f21021a5c2a0e708455b877999137e`；source commit 为本次返工唯一 source
  commit，full SHA 由 Worker 最终交付报告给出，不在本记录中自引用。
- 实现：主配置只读一次为 bytes payload 并计算 raw SHA；仅已验证的 fifth/MAX R15 在成本绑定、
  snapshot verifier、repository 与 artifact mkdir 前核对冻结 Windows payload SHA-256
  `860ca0ef600dd4de107f5e60dc8593cbb03ca6c7a3cac0cad0adf2d56a778c9f`，字节漂移 fail-closed；
  成本配置只绑定一次且 `run.inputs` 首项为标准 `a-share-cost-schedule`。非 fifth classic 恢复
  base 的 snapshot 后 `_cost_periods` 位置、无 pre-snapshot cost binding、无 cost input digest 与
  cost identity 变更。primary 仍仅消费 `test`/`horizon=20`，按预注册日期等权固定五组；score 为
  `factor * direction` 且 group 按 score 升序，固定方向 `-1` 时 group1 为高 MAX、group5 为低 MAX，
  使用 `group1 <= ... <= group5`、至少 2/3 folds 且 pooled 单调通过，并把 `*_le_*` 比较、均值和状态
  写入输出与 summary。
- 精确变更路径：`src/quant/research/run_classic_factors.py`、`tests/unit/test_run_classic_factors.py`、
  `docs/research/M2_MAX彩票偏好因子假设卡.md`、
  `docs/research/agent/M2_FROZEN_R15_冻结Clean_MAX纠偏重放任务与交付记录.md`、
  `docs/research/roadmaps/M2_策略与因子库并行建设路线图.md`；配置与 README 未改动，R15 结果文档未创建。
- 验证：focused 测试 `28 passed`；覆盖 frozen payload 通过、snapshot/universe/fold/admission/注释字节
  漂移在 cost/snapshot/artifact 前拒绝、主配置与成本各单读一次、legacy 无 early cost read 且无 cost
  input、fifth cost input 首项及 cost semantic drift。Ruff（生产文件与主测试）、mypy（生产文件）、
  cold import、TOML/cost identity/raw SHA、git diff-check 均通过。
- 运行边界：未执行真实 run、网络、PIT、PAPER 或全量测试；历史 run
  `10dea14f1fcbbbeb78871cddb7b00cd06d77cf005c3a776c4713f5a4f4129bb3` 未触碰，保持 immutable/HOLD。
  开发 Python 检查均为单实例 `BelowNormal`、affinity `0xF00`、数值线程不超过 2；R15 临时目录已清理。
- 剩余 STOP：须由独立初验与领域经理主验后，才可授权唯一真实 `RESEARCH_ONLY` run、由领域经理创建
  R15 结果文档，并由统筹执行后续合流；本 Worker 不关闭 PIT 对称 redundancy coverage、audit-v4、R3
  或任何交易 Gate。

### REWORK3_TEST_CLOSURE（测试闭环）

- reviewer：`PASS`（本轮测试闭环要求已通过；独立 reviewer 仍由 dispatcher 在交付后快速复核）。
- 新增直接回归测试：非 fifth classic 主流程带有额外
  `[portfolio].cost_schedule_semantic_sha256` 时，`main()` 仍先 snapshot 后调用 `_cost_periods`，不调用
  `_cost_schedule_binding`，不产生 `a-share-cost-schedule` input，report 与非成本 run identity 字段保持不变；
  frozen MAX 主配置由 CRLF 转 LF 后确认实际转换、raw SHA 漂移，并在 cost binding、snapshot/data reader、artifact
  publisher 前 fail-closed。
- 验证：focused `tests/unit/test_run_classic_factors.py` 为 `30 passed`；Ruff（修改测试文件）与
  `git diff --check` 通过。生产源码未修改，未执行真实 run、网络、PIT 或 PAPER。

### 领域经理主验与唯一真实 attempt 收口

- 最终实现 source：`6e54227c6b0c8935eb3539470dd641c4470f36fc`；独立复验结论 `REVIEW_PASS`。
- 主验：冻结身份、legacy 隔离、CRLF 漂移、成本单读与五组单调门禁等关键节点 `13 passed`；Ruff、mypy、
  cold import、TOML、成本语义身份、cached/working diff-check 均通过；冻结 snapshot
  `b79a7b5e66dee0ae439c030078414157ca6c1f3b6ce7fbe5e36ff3910c1089d2` fresh verify 通过。
- 唯一真实 attempt 按 `BelowNormal`、affinity `0xF00`、数值线程不超过 2 启动并自然终止；在 artifact 发布前，
  `build_diagnostic_factor_targets` 对固定 Top-K chosen outcomes 执行 R12 完整性门禁并抛出
  `diagnostic selected target outcomes are invalid`。冻结状态为
  `STOPPED_BEFORE_PUBLICATION / DIAGNOSTIC_SELECTED_TARGET_OUTCOMES_INVALID`。
- R12 Gate 正常生效：没有使用第 K+1 名替补，也没有第二次运行。没有生成 run id、不可变 run、public
  verification 或 canonical retained；历史 run `10dea14f…129bb3` 未触碰并继续 HOLD。
- 本次 attempt 计入既有 trial ledger 规则，但不得冒充完整研究 trial 结果；MAX corrective hypothesis 保持
  `UNASSESSED/HOLD`，不是 `REJECTED`，也不构成“无候选”的经济证据。
