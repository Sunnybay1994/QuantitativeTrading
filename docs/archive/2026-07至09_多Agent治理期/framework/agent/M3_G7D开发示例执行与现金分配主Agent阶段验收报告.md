# M3 G7D 开发示例执行与现金分配主 Agent 阶段验收报告

日期：2026-08-02

## 结论

G7D 的开发示例合同通过。后续 G7E 可经公开 verified development 接口消费同一 G1-shaped 数据包，
但本结论不等同于正式数据回测验收、正式 G1 Linux/ext4 Gate 或 M3 发布通过。

## 已实现

- `AShareMarketFactsIdentityV1` 精确绑定开发 G1 manifest、G7B window 和八个实际源文件的 size/hash；
  builder 只接受 verified release + verified plan，不接受调用方自报裸 DataFrame 或 release ID。
- `VerifiedDevelopmentExampleAShareMarketFacts` 保留 `development_example` / `formal_gate_eligible=False`
  身份，和正式 `VerifiedG1Release` 类型隔离。
- `OpenExecutionStateSchema` 固定 12 列；open-state 仅读取 open，不读取未来 high/low/close/volume。
- FULL_DAY、PARTIAL 精确 `" | "` 分隔、09:30 半开区间命中、未知 detail、缺 open/limit 均 fail-closed；
  bar 不覆盖 suspension 证据。
- 分板块申报数量、T+1 residual、公司行动零股 residual、涨跌停、Decimal 滑点/tick/limit 夹取及费用
  分项均可审计；拒绝数量与成交数量守恒。
- 买单通过精确 `Fraction` breakpoint 找到可支付的最大共同比例，再按余量比例和 symbol 升序分配；每一步
  以真实执行价和完整费用重算，最终现金非负且输入顺序不影响结果。
- 全部路径为内存纯函数或只读 release consumer；无网络、无 Qlib import、无正式 G1/journal/候选写入。

## 验证

Windows 原生 Miniforge：

```text
pytest tests/unit/test_m3_a_share_execution.py
       tests/unit/test_m3_a_share_allocation.py
       tests/unit/test_m3_a_share_market_facts.py
81 passed in 27.13s
ruff check <G7D changed files>
All checks passed!
mypy <G7D source files>
Success: no issues found in 5 source files
```

WSL Miniforge base（源码在 `/mnt/f`，不是 ext4 Gate）：

```text
pytest <same G7D tests>
81 passed in 15.91s
ruff check <same G7D files>
All checks passed!
mypy <same G7D source files>
Success: no issues found in 5 source files
```

Pandera 在验证开发 fixture 时产生已知 deprecation warnings；Windows pytest cache 另有工作树 ACL warning，
均未改变测试结果。

## 剩余风险与下一步

- G7E 仍须把 G7C entitlement 与本包 execution primitives 接入逐 session 账户循环，并用七表守恒 golden 验证。
- development market-facts 当前只接受明确的 development verified 类型；正式 G7 折叠时须增加正式
  `VerifiedG1Release` consumer 并重跑真实 release 闭包，不得通过类型替换混用。
- 正式 G2C 已在独立分支完成；正式 G3A 的发布仍依赖 G8 ExperimentIdentity 到位。
