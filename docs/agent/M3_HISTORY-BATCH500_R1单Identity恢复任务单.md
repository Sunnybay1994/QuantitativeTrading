# M3 HISTORY-BATCH500-R1 单 Identity 恢复任务单

日期：2026-07-18  
状态：**已获持续 API 授权，按最小恢复预算执行**

## 冻结目标

仅恢复 intent-only identity：

```text
31aac841cebc9bc2e3197b1aa0d49664407a92a1fd9a8577c7b32faa7d32bb13
adj_factor / 600884.SH / 20151009..20260710
```

前置：`572 verified / 2613 missing / partial=1 / [INDEX]`；partial 目录只有 canonical intent，raw ABSENT。

唯一命令：

```text
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml \
  history --max-new-requests 1
```

最多 1 个 committed identity、最多 5 attempts。已有 receipts 全部复用；不得继续执行原 BATCH500 的剩余 426 个额度。

成功预期：`new=1 / verified=573 / missing=2613 / partial=0 / [INDEX] / INCOMPLETE`。失败则再次停止，不在同任务重复命令；用生产 status/verifier 留存证据后再决定是否为外部端点阻塞。

不改代码、测试、配置或 policy，不手工调用 endpoint，不输出底层 cause/token。用户 24 小时流程简化期间由主 Agent 直接执行验证。
