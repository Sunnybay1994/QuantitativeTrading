# M4 B6/B7 R2：完整 replay 闭包交付报告

日期：2026-08-08  
状态：Windows/WSL 对应自验通过；等待独立复验

## 改动

- 新增公开 `SimulationReplayInputs`，保留并 identity-bound 绑定场景计划、市场快照、初始账户和事件仿真配置；
- `VerifiedSimulationResult` 增加 `replay_inputs`，root identity 同时绑定 `replay_input_id`；
- `simulate_order_plans` 在完整输入重验后克隆/re-enter replay closure，再用该闭包执行同一仿真公式；
- `verify_simulation_result_identity` 先重验闭包及所有嵌套公开 identity，再调用同一个
  `simulate_order_plans` 全量重放并逐字段比较；B7 仍只调用 B6 公共 verifier，没有复制规则公式；
- 公共包根安全导出 `SimulationReplayInputs`。

## 修复的不变量

合法 SHA-256 只证明内容自洽，不能证明 decision 是规则公式的真实输出。现在任何 decision、command、event、
transition、checkpoint 的删除/替换/重复/跨场景移植，即使攻击者重算 scenario/root identity，也会与公开
replay closure 的确定性重放结果不一致而 fail closed。replay 中 plan/snapshot/account/config 本体或 identity
漂移同样拒绝。

## 新增反例与验证

- decision 删除、accepted/code/数量/价格/rule version 替换、重复、乱序、跨场景移植并全量重哈希；
- command/event/transition/checkpoint 删除并全量重哈希；
- replay plan、snapshot、account、config 本体与 `replay_input_id` 漂移；
- hostile replay 异常不泄露路径/token，cause/context 均断开；
- B7 对全量重哈希伪造结果在指标计算前稳定拒绝。

Windows 原生（`D:\Miniforge3\python.exe`，`PYTHONPATH=src`）：

- B6/B7 pytest：`31 passed`；
- B1–B8 合流 pytest：`172 passed`；
- Ruff：PASS；
- mypy：PASS。

WSL Miniforge base 在同一 `/mnt/f` worktree 的 B6/B7 对应定向：`31 passed`。该结果验证 Linux
解释器兼容，但路径属于 DrvFS，不等于 ext4 Gate。

当前结果只表示 Windows 开发合同自验通过，不关闭 B6/B7 独立复验、正式数据、P8、Linux/ext4 或 M4 Gate。
