# M3 G1 P0K-B：600733 股改股份对价与基数归一化主 Agent 最终验收报告

状态：**P0K-B 主验通过；正式 HISTORY 已越过 600733，但仍被下一首败阻塞**

日期：2026-07-31（Asia/Shanghai）

## 1. 范围与身份

- P0K-A-REAL1 正式 raw 闭包基线：`dec16c8`。
- P0K-B 主实现提交：`3ba098d`。
- 本轮主验返工的生产代码仅修改：
  `src/quant/domain/schemas.py`、`src/quant/data/m3_execution_facts.py`；
  正式形状回归位于 `tests/unit/test_m3_execution_facts.py`，reconciliation v8 精确传播断言同步到
  candidate/planning/reference 定向测试。
- 未访问网络，`new_requests_committed=0`；未运行 REFERENCE、PREPARE 或 PUBLISH。

## 2. 正式首轮结果与根因

Windows 原生正式命令：

```powershell
D:\Miniforge3\python.exe -m quant.research.m3.run_g1 `
  --config configs/research/m3_qlib_example.toml status
```

结果：

- exit `6`，耗时 `3701.0s`；
- `outcome=FAILED`；
- `error_operation=INSPECT`；
- `error_code=G1_WORKFLOW_QUALITY_FAILED`；
- `new_requests_committed=0`；
- 顶层 CLI 按脱敏合同未输出内层证券。

随后用同一正式 request plan、既有 verified receipt 和生产
`_build_candidate_body` 做单次零网络内层捕获，首败仍为
`600733.SH@2018-09-27 / G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED`。证据为：

- raw stock ratio `0.5`；
- basis multiplier `3.5`；
- effective stock ratio `0.5/3.5=1/7`；
- actual factor ratio `9.36/8.192=1.142578125`；
- declared ratio `1+1/7=1.1428571428571428`；
- declared relative error `0.000244140625 < 0.001`。

失败不在 P0K-B 的基数证明。复牌日存在 `daily.pre_close=15.05`，旧分支仍用停牌前
`previous_close=52.69` 计算 market ratio `52.69/15.05=3.5009966777408636`，
导致 market relative error `0.6736420424890871`。这两个价格跨越了已经由正式 term
证明的 3.5 倍股本基数变化，不能作为同基数 market reference 比较。

## 3. 最小返工

新增审计状态
`MATCHED_EVENT_BASIS_NORMALIZED_DECLARED_FORMULA`，仅在以下条件同时成立时使用：

1. reconciliation term 中至少一个 `basis_multiplier>1`，且该 term 已通过正式
   dividend/share-change receipt、完整 response、选中 raw row 和 ledger closure；
2. declared formula relative error 不超过配置 `rtol`；
3. daily market reference 存在但 relative error 超过 `rtol`。

该状态仍保留 `pre_close`、market ratio 和 market error，明确记录“存在但跨基数不可比”，
不把证据伪装成缺失。普通分红、配股和没有 normalization term 的事件仍必须通过原 market
合同；既有 fail-closed 分支未放宽。独立 verifier 会重算 declared/market，并强制新状态必须
绑定 `basis_multiplier>1` 的 canonical term。

由于公开 reconciliation 证据状态发生变化，
`G1_CORPORATE_ACTION_RECONCILIATION_VERSION` 从 v7 升为 v8；selection version 仍为 v7。

## 4. 验证

Windows 原生：

- P0E/P0I/P0K-B 相邻合同、candidate/planning/reference 版本传播：
  `43 passed, 329 deselected`；
- Ruff：通过；
- mypy：2 个生产文件通过；
- `git diff --check`：通过。

WSL Miniforge base：

- 同一 P0E/P0I/P0K-B 相邻合同、candidate 版本传播：
  `43 passed, 329 deselected`；
- Ruff：通过；
- mypy：2 个生产文件通过。

此前 P0K-B 主实现还完成：

- WSL Schema/CNINFO connector：`42 passed`；
- WSL execution-facts P0K-B：`6 passed, 133 deselected`；
- WSL candidate P0K-B/版本传播：`11 passed, 50 deselected`。

修复后再次用全部正式 receipt 单次构建候选，耗时 `1623.4s`。600733 已越过，新的首败为：

```text
601016.SH
previous_factor_date=2022-11-25
effective_date=2022-11-28
actual_factor_ratio=1.1272352132049517
event_count=0
G1_CORPORATE_ACTION_FACTOR_UNEXPLAINED
```

这证明 P0K-B 的目标语义已通过正式数据路径；正式 HISTORY 仍因独立的新 no-event 首败失败。

## 5. 裁定与剩余风险

- P0K-B 主验通过。
- `2018-09-19` 只计既有 Tushare `2.5`，`2018-09-27` 只计
  `0.5/3.5`；raw ledger 比例仍为 `0.5`。
- 正式 HISTORY 尚未通过；下一步只诊断 601016，不提前启动 REFERENCE。
- 当前 HEAD 没有有效 `VerifiedG1Release`；旧 Windows release 的 source-tree identity 已失效。
- 本报告不宣称 G1 Gate、Linux Gate 或 G2A 已通过/启动。

下一首败记录：
[`20260731_P0K-B后正式首败_601016无事件因子跳变.md`](20260731_P0K-B后正式首败_601016无事件因子跳变.md)。
