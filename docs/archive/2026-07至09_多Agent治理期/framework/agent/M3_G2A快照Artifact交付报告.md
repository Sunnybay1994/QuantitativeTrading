# M3 G2A 快照 Artifact：主 Agent 实现与阶段验证报告

日期：2026-07-31
分支：`codex/m3-g2a`
基线：`6b64973`
状态：**temp builder / strict verifier 合同实现已通过双平台定向验证；尚未正式发布 full snapshot，不关闭 G2A/G2/M3 Gate**

## 1. 流程边界

用户当前明确要求省略外部实现与外部独立初验，由主 Agent 自行实现、自行验证；本报告如实记录该临时流程，
不伪造独立初验结论。正式数据运行仍以当前 G1 release 发布并从磁盘验真为前置。

审计发现原任务书存在依赖循环：G2A verifier 必须消费 snapshot receipt，唯一 publisher 却位于晚于 G2B 的
G8B。SSOT 已修订为：G2A 合同实现 → G8A/G8B 最小发布器 → 正式 G2A publish/verify → G2B。

## 2. 实现

- 新增 frozen G2A 值对象：build spec、request record、artifact entry、manifest、build result、verified bundle。
- 新增 `SnapshotSessionCalendarSchema`：精确单列 `Date`、非空、唯一、严格递增。
- production staging 入口只消费重新验真的 `VerifiedG1Release`，G1 manifest 及三个实际读取 Parquet 在读取前再次
  核对物理 SHA-256/size，避免 verifier 后换件。
- 固定 Tushare、CSI300 PIT 历史并集、SH open calendar、history/signal 四日期闭包和 adjustment 公式。
- 固定 calendar/staging Parquet writer 参数与 staging dtype；manifest、request 使用 strict canonical JSON。
- verifier 重建严格目录树、codec、Schema、物理 bytes、逻辑统计、snapshot ID、request mapping 和 receipt 精确
  inputs/outputs 闭包；拒绝 symlink/reparse/hardlink、额外文件和跨身份混配。
- 新增稳定边界异常 `M3SnapshotError`，仅暴露三个冻结 code。
- 移除 G2A parent 源码中的 Qlib import；旧 provider seam 只保留 fail-closed 行为，真实实现留给 G2B/G2C。
- 修复 `run_state` 在 Windows 原生上对目录执行 POSIX fsync 导致 receipt 发布失败的问题：文件 fsync 保持，
  Windows 仅跳过不可靠的 directory-fd fsync；Linux 路径与失败优先级测试不变。

## 3. 对抗覆盖

新增或保留的覆盖包括：错误 request key、非空输出零覆盖、duplicate JSON key、receipt 多输出、全市场 session
缺失、单证券 gap、membership 调入前历史保留、SH/SZ 日历分歧、source 重复、NaN/Inf/zero amount/volume、
codec 往返、manifest/price/vwap/config/G1 identity 漂移、旧 provider fail-closed 和 parent 无 Qlib import。

## 4. 验证

Windows 原生 Miniforge，显式 `PYTHONPATH` 指向隔离 worktree（避免 editable install 错指主线）：

```text
pytest tests/unit/test_m3_snapshot.py tests/unit/test_schemas.py -q
63 passed
ruff（9 个改动源/测试文件）: passed
mypy（6 个源文件）: passed
```

WSL Miniforge `base`：

```text
pytest snapshot + schemas + run_state Linux dir-fsync/round-trip
65 passed
ruff: passed
mypy: passed
```

跨平台固定 writer 探针（Windows/WSL 均为 Python 3.13.13、Polars 1.42.1）：

| 文件 | SHA-256 | 结果 |
|---|---|---|
| `session_calendar.parquet` | `b41439bee822c1cb8409852f4e195501e7a50722cddd2a6e1b6d84e3ce1b9d76` | Windows = Linux |
| `staging/sh600000.parquet` | `0ee4b62d67cf054a7fbe221cae15b5f077c3a50dd6f32628e953309a745c5568` | Windows = Linux |

探针位于 `artifacts/g2a_cross_platform_probe/`；它证明当前受控 runtime 的小 fixture 物理 bytes 一致，不替代
正式 full snapshot 逐文件验真。依赖版本变化后必须重跑。

## 5. 未关闭风险与下一步

1. 正式 G1 REFERENCE/PREPARE/PUBLISH 尚在主工作树后台推进，当前没有可消费的新 `VerifiedG1Release`。
2. G8A/G8B 最小发布器尚未实现；因此还没有合法 final snapshot/request mapping/receipt。
3. full snapshot 的运行时间、磁盘占用和全量跨平台 bytes 尚无证据。
4. 任务书未冻结 receipt alias 字面值；当前 verifier按已验真 artifact root 映射后的精确物理路径比较语义集合。
5. 完成 G8A/G8B 后，必须正式 build/publish、从磁盘 `verify_snapshot_artifact`，再启动 G2B。
