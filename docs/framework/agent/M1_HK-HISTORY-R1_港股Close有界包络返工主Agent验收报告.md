# M1 HK-HISTORY R1：港股 Close 有界包络返工主 Agent 验收报告

日期：2026-08-15（Asia/Shanghai）  
结论：**PASS（仅关闭 mapper 返工，不宣布 HK60 或 M1 Gate）**

## 验收范围

- 冻结任务：[`M1_HK-HISTORY-R1_港股Close有界包络返工任务单.md`](M1_HK-HISTORY-R1_港股Close有界包络返工任务单.md)
- 实现交付：[`M1_HK-HISTORY-R1_港股Close有界包络返工交付报告.md`](M1_HK-HISTORY-R1_港股Close有界包络返工交付报告.md)
- 外部独立初验：[`M1_HK-HISTORY-R1_港股Close有界包络返工独立初验报告.md`](M1_HK-HISTORY-R1_港股Close有界包络返工独立初验报告.md)
- 真实异常取证：[`M1_01065_20260515_OHLC异常Cursor只读取证报告.md`](M1_01065_20260515_OHLC异常Cursor只读取证报告.md)

实现只改变 HK 日线 canonical 投影：raw OHLC 有限为正、原区间自洽、open 已在原区间、close 仅一侧越界且
相对最近边界偏离不超过 5% 时扩展 high/low 包络。A 股、open 与 close 同时越界、超过阈值以及非法价格仍
fail closed；Schema、连接器、raw、journal 均未修改。

## 主验结果

Windows 开发反馈环：

- `D:\Miniforge3\python.exe -m pytest tests/unit/test_tushare_connector.py -q`：`35 passed`；
- `ruff check src/quant/data/mappers.py tests/unit/test_tushare_connector.py`：PASS；
- `mypy src/quant/data/mappers.py`：PASS；
- scoped `git diff --check`：PASS（仅既有 LF/CRLF 提示）。

真实 retained v2 回填又提供了直接合流证据：

1. 使用错误的 journal 父目录会稳定返回 `HK_HISTORY_PLAN_CONFLICT`；改用计划 SHA 对应的叶子 journal 后，
   binding 与前两份 receipt fresh 验真通过，准确返回 `HK_HISTORY_INCOMPLETE`；
2. 随后执行一次授权的 Tushare one-step 请求，零覆盖恢复一个已有 COMPLETE raw，并新取一批，返回
   `completed_requests=4/8`、`network_requests=1`；
3. 剩余四批由同一叶子 journal、冻结的一小时冷却和单请求串行助手继续推进，不并发、不绕过冷却。

## 剩余边界

- 本报告不关闭 HK60 数据完整性、正式 clean 发布、公司行动或 M1 总 Gate；
- WSL/Linux Gate 不在本轮范围；
- 独立初验记录的既有 Schema 对某些 `high=+inf` 组合的边界不由本任务处理，未被本改动扩大。
