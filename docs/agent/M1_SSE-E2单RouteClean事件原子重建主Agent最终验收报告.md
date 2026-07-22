# M1 SSE-E2 单 Route Clean 事件原子重建主 Agent 最终验收报告

日期：2026-07-17  
结论：**代码能力最终验收通过；真实 SH clean replace 尚未授权执行**

## 1. 交付

- 实现：[`M1_SSE-E2单RouteClean事件原子重建交付报告.md`](M1_SSE-E2单RouteClean事件原子重建交付报告.md)
- 独立初验：[`M1_SSE-E2单RouteClean事件原子重建独立初验报告.md`](M1_SSE-E2单RouteClean事件原子重建独立初验报告.md)

新增 `CleanConnectEventStore.replace_route`、`ConnectMarketPipeline.update_events(replace_clean=...)` 和 CLI
`--replace-clean`。默认仍为 UPSERT；显式 replace 只替换单 route clean event，raw 先不可变留存，另一 route
和其他 clean 表不变。

## 2. 安全合同

- 空/multi-route/非法 Schema、非严格 bool 和非法 CLI 组合在目标变化前拒绝；
- root/祖先/route 目录 symlink、目标 symlink、FIFO、目录、临时文件 symlink 均 fail-closed；
- mapper 失败时允许 raw 证据留存，但旧 clean 字节不变；
- replace 不 concat，写后重新读取并验证 Schema、行数和业务键集合；
- 独立初验 `/tmp` 路径攻击 8/8 通过，外部目标字节未改变。

## 3. 主验

```text
storage connect/event/replace tests     7 passed
connect_market + update_connect tests  26 passed
ruff                                    passed
mypy 3 source files                     passed
```

## 4. Gate

本结论只关闭 E2 代码能力。现有 SH clean 仍含旧 mapper 生成的错误 action；在用户明确授权前，不运行：

```bash
python -m quant.data.update_connect --route SH_CONNECT --table events --replace-clean
```

真实执行后还必须由另一外部 Agent 只读验证：raw 新快照存在、SH clean 1212 行及 ADD=794/REMOVE=418、SZ
文件字节不变、reverse state conflict=0、逆推规模=268；随后才能重建更早 universe interval。
