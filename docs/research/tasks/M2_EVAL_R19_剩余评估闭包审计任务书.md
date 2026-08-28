# M2-EVAL-R19 剩余评估闭包审计任务书

> 状态：`TASKBOOK_READY / STATIC_ONLY`
> task id：`M2-EVAL-R19-REMAINING-CLOSURE-AUDIT`
> 结论上限：`IMPACT_MATRIX_FROZEN`
> trial delta：`0`
> exact base：`3e74dd7d4a43fc09b8e6f361dd183da55f9576cc`
> branch/worktree：待统筹准入；本阶段不创建
> CPU/真实 I/O：`NONE`

## 1. 目标

对 `M2-EVAL-STOP-001` 原始六项做一次 latest-main 只读影响审计，建立可复核的逐项矩阵：

- 原始不变量和直接消费链；
- latest main 的权威代码、测试与文档证据；
- R12/R13/R14/R15/R16/R17 各自关闭的精确消费者边界；
- 状态只能为 `CLOSED_FOR_FROZEN_CONSUMER`、`PARTIAL_SCOPE_ONLY` 或 `OPEN`；
- 每个仍存 `OPEN` 的实现项的权威 SSOT、最小代码包候选、对抗反例和验收边界。

本包只冻结影响矩阵，不修改生产代码/测试/配置，不关闭
`M2-EVAL-STOP-001`，不授权 audit-v4、R3、financial snapshot 或 PIT 真实运行，不新增或重开
任何研究 trial。

## 2. 原始六项与待审基线

Worker 必须从 latest main 独立复核以下基线，不得只复述历史交付报告。如代码与基线冲突，
交付报告必须 `STOP / CONTRACT_DRIFT`，不得为了得出“全部已关闭”而放宽消费者边界。

| # | 原始不变量 | latest-main 待审基线 | 预期分类 |
|---|---|---|---|
| 1 | signal cohort/group 必须在 future outcome pairing 前冻结，完整 date/grid/coverage fail-closed | R12 已修正 shared `evaluate_factor_period`；须核对代码、反例和 merge ancestry | `CLOSED_FOR_FROZEN_CONSUMER` |
| 2 | 调仓与 terminal sell 使用持有期收益后漂移权重，不得沿用上期 target | R12 已修正 shared diagnostic simulator 及直接调用链 | `CLOSED_FOR_FROZEN_CONSUMER` |
| 3 | redundancy pair 的两侧 incident/coverage 必须对称、多 pair 严格 all、缺 pair 失败 | R16 关闭首个 PIT direct-call chain；R17 关闭 classic corrective-replay 调用点；不扩大为全部未审 runner | `CLOSED_FOR_FROZEN_CONSUMER` / 其他 runner `PARTIAL_SCOPE_ONLY` |
| 4 | 主 config 与 cost config 各自 single-payload parse/hash，canonical cost semantic SHA 作标准 run input | R13 关闭首个 PIT；R15 + portable R2 关闭 frozen MAX lineage；全局 runner provenance 债不属于本 STOP 的首 PIT 闭包 | `CLOSED_FOR_FROZEN_CONSUMER` / 全局债 `PARTIAL_SCOPE_ONLY` |
| 5 | primary horizon=20 五组单调性必须在真实结果前定义并被 admission 消费 | R15 只关闭 MAX lineage；首个 PIT runner 仍未实现 per-factor fixed-direction + h20 fold/pooled Gate | MAX `CLOSED_FOR_FROZEN_CONSUMER`；首 PIT `OPEN` |
| 6 | PIT 单季前驱版本须绑定 current `available_date` cutoff，并在 latest 前限定 `comp_type=1` | R14 关闭 runtime version/comp-type chain；真实 singleton `allowed_report_types` 仍须 audit-v4 证据后冻结，但不得误报为 R14 runtime 未实现 | `CLOSED_FOR_FROZEN_CONSUMER`；singleton 外部前置 `OPEN` |

任务书中的“关闭”只表示精确冻结消费者的代码/测试合同已进入 latest main，不表示真实数据
质量、试验结果、promotion 或 PAPER 已通过。

## 3. 权威证据与影响矩阵 schema

交付报告必须包含六行 exact matrix，每行至少有：

1. `item`、`invariant`、`frozen_consumers`、`status`；
2. latest-main 生产符号、测试节点和版本化文档，均给出 exact relative path + symbol/heading；
3. source commit、no-ff merge commit 和 archive tag；若 tag 不存在或文档未记录，如实标为证据缺口，不得猜测；
4. `remaining_gap`、`minimum_future_package`、`adversarial_examples`、`acceptance_boundary`；
5. 对局部闭包显式写出未审消费者，禁止用“shared helper 已修复”推导全局所有 runner 已关闭。

权威实现/测试读取范围仅限：

- `src/quant/research/classic_factor_evaluation.py`
- `src/quant/research/run_classic_factors.py`
- `src/quant/research/run_pit_quality_factors.py`
- `src/quant/data/financial_pit.py`
- `src/quant/research/pit_quality_research.py`
- 对应 `tests/unit/test_classic_factor_evaluation.py`、`test_run_classic_factors.py`、
  `test_run_pit_quality_factors.py`、`test_financial_pit.py`、`test_pit_quality_research.py`
- `configs/research/m2_pit_quality_factors.toml`、`configs/research/m2_classic_daily_factors_fifth_batch.toml`
- R12–R17 任务/交付/初验文档、本路线图与 `docs/governance/CODEX_HANDOFF.md`。

允许用 `rg`、`git show`、`git log`、`git merge-base --is-ancestor` 做只读追溯。禁止运行 Python、
pytest、Ruff、mypy、cold import，也禁止打开或遍历 `data/`、`artifacts/research/runs/`
和任何金融 raw/ledger/clean。

## 4. 唯一剩余实现项的冻结候选

若审计没有发现 latest-main 回归，六项中唯一剩余实现项应是“首个 PIT h20 单调准入”，
但它仍须在 audit-v4/snapshot 后与 R3 其他身份一起最终冻结。本审计只登记下列候选，不创建实现包：

- 核心最小 code/test/config 候选：
  `src/quant/research/run_pit_quality_factors.py`、
  `tests/unit/test_run_pit_quality_factors.py`、
  `configs/research/m2_pit_quality_factors.toml`；
- 权威方向：`PIT_QUALITY_FACTOR_SPECS` 的 `higher -> +1`、`lower -> -1`，禁止修改 shared evaluator
  或 cross-import MAX helper；
- 每个 factor 以相同 panel/folds/cost/signal identity 单独调用现有 evaluator，结果按权威
  schema/key/grid 闭合后 canonical concat；
- h20 使用 direction-adjusted score 的 `group1 <= ... <= group5`，每个 signal date 等权；
  `>=2/3` folds 且 pooled 通过；h1/h5 只诊断；
- 缺 date/group、重复 key、coverage 非 PASS、非有限值、方向/身份漂移或四 factor 结果网格不闭合
  都必须 fail-closed，并只允许 `RESEARCH_ONLY -> REJECTED`；
- 验收不得仅测 helper：必须锁定 four-call orchestration、严格方向、Gate 顺序、report v2、
  exact factor summary schema、现有 13 outputs 集合和最终 conclusion。

上述候选必须继续保留已登记的 no-clobber trial-attempt receipt、config/admission identity、
per-factor result closure 和正式平台 durability 边界；本包不重复整套 R3 合同，也不把它们写成已实现。

## 5. 文件所有权

未来最终提交 exact 4：

1. 经理唯一写：`docs/research/tasks/M2_EVAL_R19_剩余评估闭包审计任务书.md`；
2. 经理唯一写：`docs/research/roadmaps/M2_策略与因子库并行建设路线图.md` 的 R19/下一队列 exact hunk；
3. 唯一审计实现者写：`docs/research/deliveries/M2_EVAL_R19_剩余评估闭包审计交付报告.md`；
4. 不同独立审查者唯一写：`docs/research/reviews/M2_EVAL_R19_剩余评估闭包审计独立初验报告.md`。

各角色不得交叉写入。Worker 只做源码/历史证据的只读审计并写 delivery；reviewer 仅读同一
exact base 与 delivery，只写 review。

## 6. 必须覆盖的对抗反例

- 历史文档标记“已实现”，但对应 source/merge 不是 latest main ancestor：不得标 `CLOSED`；
- shared helper 已修正，但某 runner 绕过或复制旧逻辑：该消费者仍 `OPEN/PARTIAL_SCOPE_ONLY`；
- R15 MAX h20 Gate 存在：不得推导首 PIT h20 Gate 已关闭；
- R14 version selector 已关闭但 `allowed_report_types=[]`：必须分开 runtime 闭包与真实 singleton 证据前置；
- R16 关闭 PIT coverage、R17 关闭 classic correlation aggregation：不得把两者混成“全部 runner 已闭包”；
- audit-v4 PASS 或 snapshot READY 的假设：仍不能代替 R3 h20/admission/receipt 实现；
- 只在测试名或文档中找到关键词，却未核对生产调用顺序与 fail-closed 边界：不足以标记关闭。

独立 reviewer 必须新增至少一个实现者未使用的对抗反例，并以当前 source symbol/test node
证明，不得只校对文字。

## 7. 验收、STOP 与交付

审计交付必须同时满足：

1. exact 六行矩阵，且六项与本路线图原始编号一一对应；
2. R12–R17 source/merge ancestry 可复现，每个“关闭”都有生产符号+反例测试+历史身份三类证据；
3. 局部消费者边界与外部数据/identity 前置分开；
4. 唯一剩余实现项的最小候选包与反例、验收边界完整；
5. 结论明确保持 `M2-EVAL-STOP-001=OPEN`，且 UA-M2-001、audit-v4、R3、snapshot/PIT
   皆未获得运行授权。

出现以下任一情形立即 `STOP`：需要修改 exact4 外文件；需要运行 Python 或读取数据；
代码与冻结基线冲突；无法证明 source/merge ancestry；或需要重新解释 trial、方向、阈值、
promotion 状态。

Worker 完成后只回 `DELIVERY_READY <path>`。经理核 scope 后再派不同 reviewer；初验上限为
`REVIEW_PASS / IMPACT_MATRIX_FROZEN`。本包无 CPU 验证阶段、无真实 run，完成后只依流程申请 exact4 文档安全提交与统筹合流。
