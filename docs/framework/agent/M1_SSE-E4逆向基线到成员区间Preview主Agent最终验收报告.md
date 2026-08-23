# M1 SSE-E4 逆向基线到成员区间 Preview 主 Agent 最终验收报告

日期：2026-07-17  
结论：**最终验收通过；仅 preview，未写 universe**

## 1. 证据

- 实现：[`M1_SSE-E4逆向基线到成员区间Preview交付报告.md`](M1_SSE-E4逆向基线到成员区间Preview交付报告.md)
- 独立初验：[`M1_SSE-E4逆向基线到成员区间Preview独立初验报告.md`](M1_SSE-E4逆向基线到成员区间Preview独立初验报告.md)

实现会用 audit 的 route/baseline/count 重新验证原 snapshot/events，逐字段绑定 audit，然后正向回放并要求
最终 active symbol 集合与 current snapshot 精确相等。相同 count 但换 symbol、伪造 baseline_symbols、事件
±1 行等反例均以稳定 `REVERSE_MEMBERSHIP_AUDIT_MISMATCH` 拒绝。

## 2. 主验

```text
pytest eligibility + audit CLI   30 passed
ruff                              passed
mypy 2 source files               passed
```

真实 SZ 只读 preview：

```json
{"route":"SZ_CONNECT","reverse_count":417,"membership_rows":1149,
 "membership_symbols":1014,"coverage_start":"2016-12-05","open_intervals":644,"status":"PASS"}
```

运行未写 `clean/universe_membership`。SH 仍须先执行 SSE-REAL1 clean replace。

## 3. 下一步

发布前还需把现有 `rebuild_connect_universe` 改为显式安全 reader + verified reverse audit 输入，并使 universe
单 route 写入具备与 E2 相同的 symlink/非普通文件防护。该代码闭环完成后，真实发布仍需独立授权。
