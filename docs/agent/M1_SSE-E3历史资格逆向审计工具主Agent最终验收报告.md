# M1 SSE-E3 历史资格逆向审计工具主 Agent 最终验收报告

日期：2026-07-17  
结论：**最终验收通过；工具只读，不等于 SH clean 已修复**

## 1. 交付证据

- 实现：[`M1_SSE-E3历史资格逆向审计工具交付报告.md`](M1_SSE-E3历史资格逆向审计工具交付报告.md)
- 独立初验：[`M1_SSE-E3历史资格逆向审计工具独立初验报告.md`](M1_SSE-E3历史资格逆向审计工具独立初验报告.md)

工具通过 `quant.data` 显式 reader 读取精确 route/date 路径，不自动发现 `data/legacy/`；逆向回放严格检查
coverage、同日冲突、状态转移和官方启动规模。成功 JSON 不泄露 symbol 全集或物理路径。

## 2. 主验

```text
eligibility + audit CLI tests       18 passed
storage connect/read tests           9 passed
ruff                                 passed
mypy 3 source files                  passed
```

真实项目 data 只读结果：

```text
SZ_CONNECT  2016-12-05 → 2026-07-10  PASS
             current=644 events=1237 reverse=417 expected=417
SH_CONNECT  2014-11-17 → 2026-07-10  REVERSE_AUDIT_STATE_CONFLICT
```

SH 的失败是正确行为，证明当前旧 mapper 派生 clean 在受控 replace 前不会被误当成可证明历史。

## 3. 下一 Gate

必须先由用户授权单次 SSE 官方事件抓取、不可变 raw 写入和 SH clean route 原子替换；替换后由独立外部 Agent
运行同一 CLI，要求 SH `current=644,event_count=1212,reverse=268,status=PASS`，同时 SZ 仍为 417/PASS。
在此之前不发布更早 baseline/universe。
