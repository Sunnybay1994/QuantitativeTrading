# M3 G7A R2：Decimal 循环小数算术主 Agent 最终验收报告

日期：2026-08-09  
结论：**PASS（正式 TargetArtifact 工程合同）**

## 1. 结论

G7A 正式 target builder/verifier 已完成 G1→G5B fresh 闭包、完整 eligible/scorable/prediction 域、Top-k零权重
投影、14-input/3-output receipt与事务发布。R1 唯一阻断——合法 `0.9/7` 被有限 Decimal 尾差误判超配——
已由 formal/development 共用的固定算术 helper关闭。

R2 使用 exact capped 分支判断；未capped分支在私有 `Context(prec=50, ROUND_DOWN)` 内计算，保留
`total <= investable` 断言，不依赖全局 Decimal context、epsilon或删除防线。

## 2. 验证

- 实现者：Windows与WSL base各 `12 passed`；两平台Ruff/mypy/diff-check通过。
- 独立复验：Windows/WSL六关键节点各 `6 passed`；`n=3/7/11/299`、capped/uncapped、hostile precision/
  rounding均逐字稳定；R1 299-domain最小复现关闭。
- 主 Agent：正确节点 `2 passed in 41.31s`；Ruff PASS，production mypy PASS。第一次使用错误节点名得到
  pytest“not found”，随后按源码实际节点名重跑全绿；该调用错误未触发产品修改。
- 定向diff检查无错误。

## 3. 保留边界

当前WSL为wslfs/DrvFS，不是ext4。完整G5B大fixture的承载超时未记为绿，但formal/development直接依赖、
freshness、receipt、root replacement、whole-bundle与异常脱敏回归均有实现/独立证据。

本结论解锁 G7B formal BacktestPlanArtifact，不关闭正式全work性能、G7B-G9或M3 Gate。
