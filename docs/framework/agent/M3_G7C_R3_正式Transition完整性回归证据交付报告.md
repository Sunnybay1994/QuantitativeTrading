# M3 G7C R3 正式 Transition 完整性回归证据交付报告

日期：2026-08-09

角色：R3 tests-only 返工实现 Agent

结论：**R3 强制持久化回归与双平台组合自测完成；等待全新独立复验，不宣称主验或 M3 Gate 通过**

## 1. 返工范围

R3 严格保持生产实现只读，仅在
`tests/unit/test_m3_formal_corporate_actions.py` 增补一个最小 mixed-event 聚合对抗节点，并同步任务状态与本报告。
没有新增 capability、signer、测试专用生产旁路或宽松 helper；没有修改 R1/R2 报告、G7D-F0/G7E/M4、配置、
正式 artifact/journal。未联网、未 add/commit。

## 2. 持久化反例

新增 `test_r3_transition_attestation_rejects_every_ordered_output_and_input_drift`，使用同一份现金加送股 mixed
event 逐项冻结以下证据：

- 从四条合法有序 posting 中只删除一条、增加额外 posting、交换两条合法 posting；
- 分别漂移 `cash_delta` 与 `settled_stock`；
- 将合法 ADVANCE transition 改作 CAPTURE operation；
- 将旧 transition 改绑另一份 exact facts identity，并把旧 state 交给另一份 exact facts 的公开 advance；
- 将合法 CAPTURE transition 的 canonical quantity 输入从 100 漂移为 99；
- 所有字段变体均在 property 与 `repr` fail closed，facts identity 混用还在后续公开消费边界 fail closed；每轮攻击
  前先验证原对象可消费，全部攻击后重新签发 clean CAPTURE 与 ADVANCE 原对象并验证仍可消费。

## 3. 生产文件零变化证据

R3 开始前与完成后 SHA256 相同：

- `src/quant/backtest/corporate_actions.py`：
  `415D8E428E6D2019B92120E10A4B76C65CCEBEE42A5A4262D9E982A937BEE05E`
- `src/quant/backtest/__init__.py`：
  `BA1BD0CB2AA55B264C47D33D0C7044C3ECCBE31343BEBDA625876BB64E7665D8`

R3 前后两文件的既有 worktree diff numstat 也分别保持 `891 2` 与 `30 0`；这些是 R1/R2 已有未提交改动，R3
未增加任何生产 diff。

## 4. 验证证据

所有命令均显式使用本 worktree `src`。

Windows `D:\Miniforge3\python.exe`：

- 新增 R3 节点：`1 passed`；
- formal + development：`28 passed`；
- G7D-F0 + G7E simulator + M4 ledger：`46 passed`，合计 74 项；
- Ruff：PASS；mypy：`Success: no issues found in 1 source file`；
- cold import/public surface：`WINDOWS_R3_COLD_SURFACE_PASS`。

首次把 74 项放入单个 124 秒执行窗口时被工具超时终止，未产生断言失败输出；随后按互不遗漏的 28/46 两组
完成同一矩阵，未再机械重复整套 Windows 长测。

WSL Miniforge `base`，绝对 worktree `PYTHONPATH`：

- formal + development + G7D-F0 + G7E simulator + M4 ledger：`74 passed`；
- Ruff：PASS；mypy：`Success: no issues found in 1 source file`；
- cold import/public surface：`WSL_R3_COLD_SURFACE_PASS`。

最终 scoped `git diff --check`：PASS。当前 WSL worktree 映射到 `/mnt/f` DrvFS，不是 ext4；以上只算 Windows
与 WSL base 工程兼容证据，不等于 Linux/ext4、真实 full-work、完整账户回测或 M3 Gate 关闭。

## 5. 后续

必须由未参与 R3 的全新独立上下文复验本轮正式持久化反例、生产文件零变化和双平台证据。独立复验明确 PASS
后才进入主 Agent 最终验收。
