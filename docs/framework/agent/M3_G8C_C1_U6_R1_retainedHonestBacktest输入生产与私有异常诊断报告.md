# M3 G8C-C1 U6 R1：retained honest backtest 输入生产与私有异常诊断报告

日期：2026-08-13  
角色：主 Agent（外部 Agent 暂停模式；串行诊断）  
结论：**INSUFFICIENT_INTERNAL_EVIDENCE；未修改产品；retained 输入已全部清理**

## 1. 已证明事实

唯一 honest public producer 在 Windows `m3chain312` 成功完成：

- G1：`797.541s`
- G1 → target → backtest-plan 总链：`3316.134s`
- retained session：`a3bae5ffa7d0`
- cleanup token：`ee5563b6f1014690a5bef75b198760d3`

public resolver、formal market facts loader 和 G7E private scenario 入口均使用原位置 retained 根，没有 copy、rebase、fake capability、`object.__new__` 或 seal/registry 绕过。

## 2. 有效诊断结果

0.5x 场景在 `1534.5s` 后抛出：

```text
quant.backtest.a_share_execution.AShareExecutionError
a_share_simulator.py:_simulate_formal_a_share_scenario:580
a_share_execution.py:execute_formal_a_share_session:4045
```

该错误随后由 G7E public 边界映射为 `M3_A_SHARE_SIMULATION_INVALID`。输入非秘密 shape：

```text
execution_sessions=1
scheduled_rows=300
target_rows=300
instruments/bars/limits/reconciliation=300/300/300/300
calendar/benchmark=1/1
suspensions/ledger=0/0
```

第一次 probe 实际异常后的证据组装使用了错误属性名，被二次 `AttributeError` 覆盖；修正 exact capability 属性后重跑，得到上述有效 F2 public 异常。该首次脚本失败不计为产品证据。

## 3. 为什么仍不足

`execute_formal_a_share_session` 自身捕获全部内部异常并 `from None` 抛稳定 `AShareExecutionError`。为观察其内部 exception event，诊断脚本增加只读 trace，不改输入、返回或控制流；但该 probe 在 `1804.1s` 达到任务冻结的 30 分钟上限并被终止，未写出可计证据。

因此当前只证明失败位于 F2 public session execution 边界，未证明具体是 target、open state、lot/cash、transition integrity 或其他内部不变量。没有原始异常就不能诚实冻结产品修复。

## 4. 精确清理

cleanup 在删除前重新核对三根 path/kind/dev/inode/tree SHA，随后删除：

- `data/clean/m3_g1/releases/58a53a3be42ef34c3aa0984ca5571d976542aab7991ad074e5a760b975db222f`
- `artifacts/research/m3/_f0r2_a3bae5ffa7d0`
- `configs/research/_m3_f0r2_chain_session.toml`

cleanup receipt：`C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u6-r1\cleanup-receipt.json`。结果 `residual=[]`；事后 `_f0r*` 数量 0、config absent、G1 release children 0。

## 5. 后续边界

本轮不修改 G7E/F2。若将来继续诊断，应先冻结一个低开销、只在测试进程显式启用的内部异常观察接口，或获得 retained input 的更长诊断预算；不得再次用全局 trace 消耗完整 30 分钟，也不得根据稳定错误码猜修业务语义。
