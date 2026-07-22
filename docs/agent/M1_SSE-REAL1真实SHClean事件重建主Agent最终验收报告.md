# M1 SSE-REAL1 真实 SH Clean 事件重建 — 主 Agent 最终验收报告

## 结论

- **SSE-REAL1 最终验收通过。**
- 本结论仅覆盖任务书 [`M1_SSE-REAL1真实SHClean事件重建任务单.md`](M1_SSE-REAL1真实SHClean事件重建任务单.md) 的受控真实执行范围，不等于 M1、M3、M4 或任一 Gate 整体完成。
- 可据此放行前置依赖已满足的 **SSE-REAL2 双 Route 历史 Universe 发布**。

## 职责分离证据

1. 外部执行报告：[`M1_SSE-REAL1真实SHClean事件重建执行报告.md`](M1_SSE-REAL1真实SHClean事件重建执行报告.md)
2. 不同全新外部会话的独立验证报告：[`M1_SSE-REAL1真实SHClean事件重建独立验证报告.md`](M1_SSE-REAL1真实SHClean事件重建独立验证报告.md)
3. 主 Agent 于 2026-07-17 复核报告，并重新执行两条零网络 reverse audit。

## 主验结果

| 验收项 | 结果 |
| --- | --- |
| 唯一授权真实命令 | exit 0；`clean_mode=REPLACE_ROUTE`；SH clean 1212 行 |
| SH 事件合同 | 1212 行；ADD=794；REMOVE=418；Schema 与主键检查通过 |
| SH reverse audit | exit 0；current=644；event=1212；reverse=268；PASS |
| SZ reverse audit | exit 0；current=644；event=1237；reverse=417；PASS |
| Route 隔离 | SZ clean 的 hash/mtime 未变化 |
| raw 不可变闭包 | 新 raw metadata/checksum 闭合；旧 raw 未覆盖 |
| 对抗性证据 | 新 raw 经生产 mapper 后与 SH clean 九列全字段相等 |
| 范围控制 | 未运行 universe/snapshot/calendar；未改代码、配置或测试；无重试 |

主 Agent 复核命令：

```bash
python -m quant.data.audit_connect_eligibility \
  --route SH_CONNECT --snapshot-date 2026-07-10 \
  --baseline-date 2014-11-17 --expected-baseline-count 268

python -m quant.data.audit_connect_eligibility \
  --route SZ_CONNECT --snapshot-date 2026-07-10 \
  --baseline-date 2016-12-05 --expected-baseline-count 417
```

两条命令均为 exit 0，结果分别为 `644/1212/268/PASS` 与 `644/1237/417/PASS`。

## 剩余边界

- 工作区没有可用 Git 基线，因此“执行期间代码字节完全未变”只能依赖执行边界、文件时间与产物证据，不能用 Git diff 绝对证明；该限制不影响本次数据合同和 Route 隔离结论。
- SSE-REAL2 尚未执行；当前 universe 文件仍不是本报告的验收对象。
