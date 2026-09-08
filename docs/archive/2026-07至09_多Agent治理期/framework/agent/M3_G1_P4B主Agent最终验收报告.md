# M3 G1-P4B 主 Agent 最终验收报告

日期：2026-07-15  
结论：**G1-P4B 子包通过主 Agent 最终验收**  
边界：本结论只关闭 P4B，不表示 P4C、B4、G1、M3 或任何 Gate 通过

## 1. 验收范围

P4B 已形成以下最小闭环：

1. 从已验收 `G1Candidate` 确定性冻结 30×20=600 个样本键；
2. 唯一生成 30 个 BaoStock 单证券 request，并以 strict journal 获取、恢复和验证 raw/receipt；
3. 验证 request/receipt/raw/frame 闭包；
4. 生成并自证 600×5=3000-cell detail、summary、issues 和跨源身份。

生产实现位于 `src/quant/data/m3_reference.py` 与 BaoStock connector 的单请求 raw 接口；自动测试默认全部使用
fake client 和临时 RawStore，未调用真实 BaoStock 网络。

## 2. 外部实现—独立复验闭环

本包没有把实现者自测当成验收：

1. 首轮实现先发现共用 `G1QualityIssue` 缺少两个主契约跨源码，按规则停止；主 Agent 修订合同，只允许外科式
   扩展该枚举；
2. 实现完成后，首轮独立初验以 ADV5/ADV9 证明 bundle 可接受同一 detail 上的撒谎 summary，以及 WARNING
   跨源 issue；结论不通过；
3. 原实现 Agent 返工 F1–F3：引入 shared detail derivation，并关闭 sample/reference receipt/detail 可见闭包；
   全新独立复验通过；
4. 主 Agent 隐藏反例继续发现 H1–H3：缺失行 tolerance 可任意漂移、现存侧可为非法负值、30 requests 可自洽
   压成 29 个 stable response identities；主验不通过并再次退回；
5. 原实现 Agent 最小修复后，全新外部会话重放 H1–H3，并增加缺 PRIMARY、合法 volume=0、BOTH `-0.0`、
   同漂移再排序和非法 dtype 等变体，独立复验通过。

完整历史证据：

- [`M3_G1_P4B跨源证据交付报告.md`](M3_G1_P4B跨源证据交付报告.md)
- [`M3_G1_P4B合同阻塞解除与重开任务单.md`](M3_G1_P4B合同阻塞解除与重开任务单.md)
- [`M3_G1_P4B跨源证据阻塞解除后交付报告.md`](M3_G1_P4B跨源证据阻塞解除后交付报告.md)
- [`M3_G1_P4B跨源证据独立初验报告.md`](M3_G1_P4B跨源证据独立初验报告.md)
- [`M3_G1_P4B独立初验返工任务单.md`](M3_G1_P4B独立初验返工任务单.md)
- [`M3_G1_P4B独立初验一次返工独立复验报告.md`](M3_G1_P4B独立初验一次返工独立复验报告.md)
- [`M3_G1_P4B主验一次返工任务单.md`](M3_G1_P4B主验一次返工任务单.md)
- [`M3_G1_P4B主验一次返工独立复验报告.md`](M3_G1_P4B主验一次返工独立复验报告.md)

## 3. 主 Agent 最终验证

全部命令由 Windows 终端调用 WSL，在 `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant` 使用
`/home/mabw/miniforge3/bin/conda run -n base`；未使用 Windows Python/conda。

| 验证 | 结果 |
|---|---|
| H1/H2/H3 + ADV5/ADV9/F3 定向 | **23 passed** |
| 全量 `python -m pytest -q` | **769 passed** |
| `python -m ruff check src tests` | **All checks passed** |
| `python -m mypy src` | **78 source files，0 issues** |

主 Agent 三个临时隐藏测试在返工前均复现“应拒未拒”，返工后由仓库回归测试和全新独立复验重放为必拒；临时
文件均已删除。大量 Pandera/Polars deprecation warnings 是既有噪声，不改变本次通过结论。

## 4. 非阻塞限制

- 未做真实 BaoStock 网络 smoke；默认自动测试严格零网络。真实 smoke 需单独授权并只保留非敏感聚合证据。
- `missing_primary` 在现行 planner 只从 bars 取样时实际不可达，保留为防御性语义；不影响 P4B 输出。
- raw symlink 的稳定失败码仍可进一步细分，但当前已 fail-closed，不影响证据闭包。
- `primary_receipt_digests` 相对原始 candidate receipts 的来源证明必须由 `reconcile_cross_source` 和 P4C 原输入
  重执行关闭；bundle 没有夸大自包含能力。

## 5. 下一步

下一包只能是 P4C：从原始输入重建 P4A/P4B，生成严格 reader/manifest，并以 WSL/Linux no-clobber 目录原语发布
immutable release。P4C 主验前不得关闭 B4/G1/M3/Gate，也不得提前启动 G2A。
