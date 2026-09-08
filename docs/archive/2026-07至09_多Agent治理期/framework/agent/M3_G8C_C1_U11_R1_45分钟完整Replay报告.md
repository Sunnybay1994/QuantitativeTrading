# M3 G8C-C1 U11 R1：45 分钟完整 Replay 报告

日期：2026-08-13  
结论：**PASS（Windows honest 300 证券单场景业务回放）**

## 1. Honest producer

- 300 个执行层合法 A 股代码；不缩小业务域。
- G1 public publish/verify `495.414s`。
- G1 → formal backtest plan 全链 `2553.384s`，无异常。

## 2. Actual replay

- 通过 public CLI resolver 和 public F0 facts loader取得 fresh target、plan、facts 与完整 context。
- 调用 actual G7E `_simulate_formal_a_share_scenario`，内部实际使用 G7C/F1/F2；multiplier 精确 `0.5`，initial cash 与 cost periods 来自正式 config/plan。
- 300 scheduled rows、300 target rows、1 execution session。
- replay 在约 `1891s` 内自然结束，stdout 精确为 `U6_PRIVATE_SUCCESS`；没有 private/public exception evidence。
- 这关闭了 U4/U6 最初的 `STAGE_BUILD_FAILED` 业务根因：问题是 public-chain fixture 生成无效 `000xxx.SH`，不是生产订单规则或账户回放缺陷。

本结果证明单场景业务回放成功，不替代 G7F 三场景 artifact、G8 StageRunner 或 C1 public CLI 全路径验证。

## 3. 清理

cleanup token：`c7b6f3ed0dbb4c8f90bfd4cddd7be27c`。

按设备、inode、类型和全树 SHA-256 精确移除 G1 release、stage root、session config；cleanup receipt `residual=[]`。

## 4. 下一步

停止私有 replay 诊断，进入 public `backtest` CLI → formal resolver → G8 StageRunner → G7F 三场景 artifact 的完整 Windows 路径。仍不得把 Windows 结果表述为 Linux/ext4 Gate。
