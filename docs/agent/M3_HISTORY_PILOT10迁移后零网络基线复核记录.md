# M3 HISTORY-PILOT10 迁移后零网络基线复核记录

日期：2026-07-18  
性质：主 Agent 只读复核；不执行 HISTORY、不联网、不构成 PILOT10/G1/M3 Gate 通过

## 1. 环境与命令

WSL 项目路径：`/home/mabw/AI_Coding_win/QuantitativeTrading`；解释器：WSL Miniforge `base`。

先运行公开只读命令：

```text
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml status
```

再通过 workflow 的同一配置校验、计划派生和 `verify_tushare_receipt`，逐条验证 HISTORY 计划中当前存在的
receipt/raw/identity/policy 闭包，只输出计数。两条命令均 exit 0；未实例化 connector、未联网、未写
raw/journal/receipt/release。

## 2. 当前权威基线

```text
completed_stages = [INDEX]
history_symbols = 637
history_requests = 3186
verified reusable HISTORY receipts = 114
missing HISTORY requests = 3072
outcome = INCOMPLETE
```

`VerifiedG1WorkflowStateV1.history_responses` 在 HISTORY 全批未完成时按合同保持空 tuple，不能直接用其长度
作为 partial receipt 数；本次 114 是对每个实际存在 receipt 调用 `verify_tushare_receipt` 后的计数，不是目录
文件数或意图推断。

## 3. PILOT10 前后不变量

- 执行前必须再次得到 `3186 / 114 / 3072 / [INDEX]`；任何不一致立即停止。
- 唯一授权网络命令仍为 `history --max-new-requests 10`，最多 10 个新 committed request identity、最多 50 次
  含重试 API attempt；不得重复命令或扩大预算。
- 若十个新 request 全部提交，预期 verified reusable/missing 为 `124 / 3062`，阶段仍仅 `[INDEX]`，CLI
  outcome 仍为 `INCOMPLETE`。
- XP0-R1 未完成前不得启动 PILOT10；当前 JournalLock 在 Python 3.13 锁专项已通过，但 Python 3.10 能力探测、
  reference fixture 与跨平台测试闭环仍在返工边界内。
