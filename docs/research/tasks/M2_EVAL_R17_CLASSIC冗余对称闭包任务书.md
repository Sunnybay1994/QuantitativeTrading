# M2-EVAL-R17 classic 冗余对称闭包任务书

> 状态：`TASK_READY / STATIC_ONLY`
> task id：`M2-EVAL-R17-CLASSIC-REDUNDANCY-SYMMETRY`
> trial delta：`0`
> exact base：`a063f56651ab3af6380a4c07a5ea3bf38fcffb8c`
> branch：`codex/m2-eval-r17-classic-redundancy-symmetry`
> worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-eval-r17-classic-redundancy-symmetry`

## 1. 目标

关闭 classic corrective-replay 直接调用链的候选间冗余聚合非对称缺口。当前
`evaluate_factor_redundancy` 对候选—候选组合只生成按名称排序的唯一 pair；若 admission gate 仅按
`factor_a` 聚合，排序后位于 `factor_b` 的候选会漏掉该 incident pair。本包只修正这一 fail-closed
准入语义，不新增因子、试验、运行器或研究结论。

## 2. 冻结合同

1. 对 summary 中每个 candidate，汇总 `redundancy_summary` 中
   `factor_a == candidate` 或 `factor_b == candidate` 的全部 incident pairs，并取其
   `median_abs_rank_corr` 最大值。
2. candidate—candidate pair 同时约束两侧候选；reference/control 若不在 summary 中，只作为 pair
   端点，不得生成 summary 行。
3. 四个现有 classic 调用点必须统一调用同一私有 helper，不复制四份聚合实现；不得新增模块或
   `run_*` cross-import。
4. summary candidate 集合来自 summary 的 exact 唯一 factor 行集。summary factor、`factor_a`、
   `factor_b` 必须为严格 `String`、非 null、非空；`median_abs_rank_corr` 必须为有限实数且不得接受 bool。
5. candidate 无 incident pair、summary factor 重复、pair 重复或反向重复、字段缺失、类型错误、null、
   空端点、非有限相关值或不能形成唯一聚合时稳定拒绝；不得静默去重、隐式 cast 或以缺失为通过。
6. pair 端点顺序和输入行顺序不得改变结果。输出保持原 summary factor 行集与既有排序。
7. 只允许 `RESEARCH_ONLY → REJECTED`；已有 `REJECTED` 绝不升级。数值阈值继续来自原配置，不改变
   相关性计算、因子公式、方向、成本、coverage、调仓、config、schema 或 output 合同。
8. 本包只关闭 classic corrective-replay 的冗余对称债，不关闭 PIT 分组单调、audit-v4、R3 或整个
   `M2-EVAL-STOP-001`；历史 immutable run 不回写、不重跑、不恢复 promotion 资格。

## 3. 文件所有权

最终提交 exact 6 路径：

1. 经理唯一写：`docs/research/tasks/M2_EVAL_R17_CLASSIC冗余对称闭包任务书.md`；
2. 经理唯一写：`docs/research/roadmaps/M2_策略与因子库并行建设路线图.md` 的本包状态/evidence hunk；
3. 实现者唯一写：`src/quant/research/run_classic_factors.py`；
4. 实现者唯一写：`tests/unit/test_run_classic_factors.py`；
5. 实现者唯一写：`docs/research/deliveries/M2_EVAL_R17_CLASSIC冗余对称闭包交付报告.md`；
6. 独立初验者唯一写：`docs/research/reviews/M2_EVAL_R17_CLASSIC冗余对称闭包独立初验报告.md`。

各角色不得交叉写入对方路径。生产代码、测试与交付报告由一个全新外部实现上下文完成；独立初验由另一个
未参与实现的全新外部上下文只读执行，除自己的唯一报告外不得写文件。

## 4. 必测反例

- candidate 分别位于 `factor_a` 与 `factor_b`，结果一致；
- candidate—candidate 单一 pair 同时约束两侧，任一超过阈值均拒绝；
- reference/control 不在 summary 时不生成新行；
- candidate 无 incident pair 稳定拒绝；
- 完全重复 pair 与反向重复 pair 均稳定拒绝，不静默去重；
- summary factor 重复在 join 前拒绝；
- factor/status/端点的 null、非 String、空字符串以及相关值 null、bool、NaN、正负 infinity 均拒绝；
- 输入行与端点顺序置换不改变合法结果；
- 已有 `REJECTED` 在所有通过条件满足时仍保持 `REJECTED`；
- 通用入口、market-risk、fourth-batch、fifth-batch 四个调用点均消费同一 helper，并保留既有经济门禁。

独立初验必须增加至少一个实现者未使用的对抗反例，并逐项给出合同映射。发现问题时报告须写明
“现象—根因—应遵循规则—最小复现—新增测试—通过条件”，返工仍交回原实现者。

## 5. 验证与资源

当前只允许 `STATIC_ONLY`，CPU 资源为 `NONE`。实现与初验完成并通过经理 scope 核对后，另向中央申请
Windows 原生定向验证资源；未经授权不得运行 Python。

获批后的验证顺序固定为：

1. `test_run_classic_factors.py` 中本 helper 与四个调用点的 focused 节点；
2. Ruff：生产文件与对应测试；
3. mypy：生产文件；
4. cold import；
5. exact 6 scope、cached name-status 与 diff-check。

禁止真实 run、全量 pytest、网络、PAPER、data/raw、ledger、financial clean 或 partial financial raw I/O。
财务 writer PID 7692 / affinity `0x3` 不得被读取秘密、修改、重启、终止或变更资源。

## 6. 停止条件与交付

出现以下任一情况立即 `STOP`：合同需要扩大文件范围；需要修改 evaluator/config/schema/output；需要改变
阈值、公式、方向或历史状态；出现双写、资源冲突或无法保留既有行为。不得自行扩白名单。

实现者以唯一交付报告记录改动、反例和未运行项；独立初验通过后才能申请主验。主验全绿且证据复核后才允许
精确暂存和安全提交；随后由统筹执行 merge-tree、no-ff、integration 回归及 archive-first 退休。
