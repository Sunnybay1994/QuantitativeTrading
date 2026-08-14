# M3 G8 R1 正式 Backtest StageRunner 闭环主 Agent 最终验收报告

日期：2026-08-10
结论：**PASS。仅完成 G8 R1 formal backtest StageRunner 工程合同；不宣称 G8、M3、Linux ext4 或真实数据 Gate PASS。**

## 1. 验收范围

主 Agent 复核了任务书 §9–§11、实现交付报告、全新外部 `cursor-grok-4.5-high` 独立初验报告、白名单 production/tests 与最终源码哈希。实现、初验和主验职责分离成立；外部初验唯一持久写入为指定报告。

受验生产源码 SHA256 与实现/初验一致：

- `a_share_reporting.py`: `d9ef9b59ddcfc32a6fbe2bba89c30e5fcd405f5a284cd3189b4bf53f6335f0c8`
- `backtest_stage.py`: `825fcd81df372b9165060414c8cb1d7919dc6ec9af6171c4ebaba904547b5307`
- `orchestration.py`: `93ba5ff5ad537998ae1565f5089b4ca2262094684532608d6b16590a8f81623c`
- `backtest/__init__.py`: `af741250ab639df909372797447ce16142c6cd690db9f8368b2e83babd14761b`
- `research/m3/__init__.py`: `be2434ec62e085129ed12d2f81192c26a76b21a7c537588d68011fd9d7e05a30`

## 2. 最终契约判断

1. formal `make_work_run_plan` 的首 wave 精确止于 `backtest_plan`；development 链仍保留 development backtest/tracking。
2. backtest wave 是单个 WORK 节点，输入只来自公开 21-input SSOT，输出只来自公开 29-output SSOT；不接受 caller hash、裸 frame 或自报 result。
3. pre-receipt 与 final verifier 共用同一 G7F fresh/tree 闭包。首次、completed resume、`resume=False` 与完整 orphan 均按 StageRunner 实际路径逐次 fresh，不缓存 `_FormalBundle`。
4. build/pre/final hostile 异常分别稳定映射，公开异常 `cause/context` 为空；失败路径不遗留 receipt/temp。
5. §10 删除了从未执行 verifier 的八项源码文本内省；orchestration 测试回归到 plan 拓扑职责，未修改 verifier production 迎合测试形状。
6. 未加入普通 rename、覆盖发布或先检查后 rename fallback。Windows exclusive commit capability 为 true 且 actual golden 完整执行；本机 WSL1 capability 为 false，golden 在进入 builder 前窄 skip，其余邻接全绿。

外部初验新增并通过：同字节不同 inode receipt、hostile Mapping、case-alias/nested roots、递归异常图、fresh nonce、缺 leaf resume、orphan extra directory、pre→final 字节篡改、双 writer 锁及 hostile Decimal context。未发现新的产品阻断。

## 3. 验证证据

- 实现者最终 Windows §7：`92 passed`；Windows actual golden：`1 passed`，capability=true。
- 实现者最终 WSL base：`91 passed, 1 skipped`，capability=false，DrvFS/WSL1。
- 全新外部独立初验：Windows `92 passed`；WSL `91 passed, 1 skipped`；双平台 Ruff/mypy/cold import PASS。
- 主 Agent 聚焦 Windows：`5 passed`；Ruff PASS；mypy 3 source files PASS。
- 主 Agent 聚焦 WSL base：`5 passed`；Ruff PASS；mypy 3 source files PASS。
- 主 Agent 核对源码/测试 SHA 与交付、初验一致；scoped whitespace 检查无错误。`git diff --no-index` 因文件存在差异返回 1 属预期，未出现 whitespace 诊断。

## 4. 剩余边界与下一步

- Linux ext4 actual `RENAME_NOREPLACE` 仍未验证；必须在 capability=true 的 ext4 环境完整运行 golden，禁止用当前 skip 关闭平台 Gate。
- G8 R1 只闭合 formal backtest StageRunner wave；public CLI、tracking/MLflow、fresh-process reproducibility、fake full DAG 与 G9 均未完成。
- 下一包继续遵循任务书冻结 → 外部 Cursor 实现 → 另一全新外部 Cursor 独立初验 → 主 Agent 终验，优先减少内部 subagent。

因此，**M3 G8 R1 主验 PASS，允许冻结并推进下一 G8 分包；G8/M3 Gate 保持开放。**
