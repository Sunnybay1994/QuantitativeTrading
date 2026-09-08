# M2 MAX 彩票偏好因子 R15 纠偏重放结果

> 状态：`STOPPED_BEFORE_PUBLICATION`
> 原因：`DIAGNOSTIC_SELECTED_TARGET_OUTCOMES_INVALID`
> 假设状态：`UNASSESSED/HOLD`
> run id：无

## 结论

R15 唯一真实 attempt 没有形成可评价的不可变研究 run。冻结输入预检、定向测试和静态检查通过后，运行在
固定 Top-K 组合的 chosen-target outcome 完整性检查处正常 fail-closed：至少一个已选证券的执行/退出收益
标签不满足 R12 合同。系统没有用下一名证券替补，也没有发布部分结果。

因此本次没有 `run.json`、不可变 run、public verification 或 canonical retained；不得把该 attempt 表述为
`REJECTED`、`RESEARCH_ONLY` 或已证明“无候选”。它计入既有 trial ledger 规则，但不是完整研究 trial 结果。
MAX corrective hypothesis 与历史 run `10dea14f1fcbbbeb78871cddb7b00cd06d77cf005c3a776c4713f5a4f4129bb3`
均继续 HOLD，历史 IC、组合和成本证据不会因本次 attempt 恢复有效性。

## 验证与停止边界

- 领域经理关键节点抽查：`13 passed`；Ruff、mypy、cold import、TOML 与成本语义身份通过；
- 冻结 snapshot fresh verify 通过，未读取 partial financial raw；
- 唯一真实 attempt 使用 `BelowNormal`、affinity `0xF00`、数值线程不超过 2；
- 终止点位于 artifact 发布之前，source `artifacts/research/runs/` 未产生目录；
- 禁止第二次运行、替补、调参、改方向或借本次失败进入 forward、S2、PAPER。
