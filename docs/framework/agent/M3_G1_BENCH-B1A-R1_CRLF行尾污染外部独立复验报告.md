# M3 G1 BENCH-B1A-R1：CRLF 行尾污染外部独立复验报告

日期：2026-07-22  
角色：外部独立复验 Agent（全新会话；未参与返工实现）  
模型：`cursor-grok-4.5-high`  
任务单：[`M3_G1_BENCH-B1A-R1_CRLF行尾污染返工任务单.md`](M3_G1_BENCH-B1A-R1_CRLF行尾污染返工任务单.md)  
交付报告：[`M3_G1_BENCH-B1A-R1_CRLF行尾污染外部返工交付报告.md`](M3_G1_BENCH-B1A-R1_CRLF行尾污染外部返工交付报告.md)  
状态：**本项独立复验通过**；**不声称 B1A / M3 G1 / 任何 Gate 或主验通过**

## 1. 范围与只读约束

- 生产代码、配置、现有测试、返工交付报告：只读
- 本会话唯一写入：本复验报告
- 未改任何生产/测试文件；未跑网络/Tushare；未做 Gate 终验

## 2. 逐项核对（独立重跑，非复述交付报告）

环境：WSL `/home/mabw/AI_Coding_win/QuantitativeTrading`；pytest/ruff 经 `/home/mabw/miniforge3/bin/conda run -n base`。

| 成功标准 | 复验结果 | 证据摘要 |
|---|---|---|
| raw SHA-256 = `83713a5d7ad392282a7d6db89878d5375c3439c8d799f5e13ea73cdf78291178` | 通过 | 独立 `hashlib.sha256` 精确匹配 |
| LF=2115，CRLF=0，bare CR=0 | 通过 | LF=2115；CRLF=0；bare CR=0；总 `\r`=0 |
| 可见内容未变 | 通过 | 见 §3 反例；归一化后 raw 即可见文本 |
| `git diff --check -- tests/unit/test_m3_backfill_requests.py` | 通过 | 零输出；exit=0 |
| `python -m pytest tests/unit/test_m3_backfill_requests.py -q` | 通过 | `154 passed in 17.73s`；exit=0 |
| `ruff check tests/unit/test_m3_backfill_requests.py` | 通过 | `All checks passed!`；exit=0 |

`file`：`Python script, Unicode text, UTF-8 text executable`（不再报告 CRLF line terminators）。

## 3. 实现者未使用的只读反例

交付报告仅核对修复后 LF 哈希与行尾计数。本复验新增：

**反例：当前 LF 文件机械 `\\n`→`\\r\\n` 后，SHA-256 必须精确等于返工前冻结 CRLF 哈希 `944dced7d51df7feb85fb866d297c60a2968f96e61d1dc36a6857579b33f3c85`。**

- 实测 round-trip SHA = `944dced7d51df7feb85fb866d297c60a2968f96e61d1dc36a6857579b33f3c85`
- 结论：仅行尾从 CRLF→LF；可见字节序列与冻结污染前文本一致

## 4. 范围与交接观察

- 目标文件内容与任务单契约一致；本复验未写入该文件。
- 工作区另有其他未提交改动（配置/源码/文档等）及部分 sibling 测试含 CRLF；**均不在本返工白名单与通过条件内**，不据此否决本项，也不扩展为本会话修复范围。
- 下一步：交回主 Agent 继续 B1A 主验；本报告**不**宣布 Gate 关闭。
