# M3 G1 BENCH-B1A-R2：Unicode 数字代码越层外部返工交付报告

日期：2026-07-22
角色：外部返工实现 Agent（全新会话；只实现，不兼任独立复验或主验）
模型：`cursor-grok-4.5-high`
任务单：[`M3_G1_BENCH-B1A-R2_Unicode数字代码越层返工任务单.md`](M3_G1_BENCH-B1A-R2_Unicode数字代码越层返工任务单.md)
状态：**返工已交付待独立复验**；**不声称初验 / 主验 / B1A / M3 G1 / 任何 Gate 通过**

## 1. 结果

- 状态：已交付
- 修改文件及目的：

| 文件 | 目的 |
|---|---|
| `src/quant/data/connectors/tushare.py` | `_validate_fund_symbol` 改为 ASCII `^[0-9]{6}\.(?:SH\|SZ)$` 私有正则；拒绝 Unicode 数字且仍 `type(symbol) is str` |
| `tests/unit/test_tushare_connector.py` | 参数化覆盖全角 / Arabic-Indic；三基金端点 SDK 前 `ValueError` 且 `calls==[]`；合法 `510300.SH`/`159919.SZ` 回归 |
| 本报告 | 唯一返工交付证据 |

- 明确未修改：backfill、配置、其他校验器、其他测试/文档/路线图；未真实网络/Tushare；未宣布 Gate。

## 2. 设计与合同证据

| 成功标准 | 证据 |
|---|---|
| `_validate_fund_symbol` 精确接受 ASCII 六位 + `.SH/.SZ` | 新增 `_FUND_SYMBOL = re.compile(r"^[0-9]{6}\.(?:SH\|SZ)$")`，与 backfill `_A_SHARE` 同口径；`isdigit()` 路径已移除 |
| `type(symbol) is str` / bool / 字符串子类合同不变 | 仍用 `type(symbol) is str`；既有 `True` 等非法用例保留 |
| 全角 `５１０３００.SH` 与 Arabic-Indic `٥١٠٣٠٠.SH` 在三端点 SDK 前失败且 calls=0 | `test_fund_raw_methods_reject_unicode_digit_symbols_before_sdk` |
| 合法 `510300.SH` / `159919.SZ` SDK 参数不被改写 | `test_fund_raw_methods_accept_ascii_sh_sz_symbols` |
| 不放宽其他证券/市场校验 | 仅改 `_validate_fund_symbol`；`_validate_a_share_symbol` / `_market` 等未动 |

现象—根因—规则—复现—测试—通过条件映射见任务单 §1–§5；本交付按该合同最小修复。

## 3. 验证

权威环境：WSL `/home/mabw/AI_Coding_win/QuantitativeTrading`，`/home/mabw/miniforge3/bin/conda run -n base`。
Windows `D:\Miniforge3\python.exe` 仅作反馈环（pytest/ruff/mypy 同绿），**不代替** WSL 定向验证表述。

| 命令或检查 | 结果 | 证据摘要 |
|---|---|---|
| `python -m pytest tests/unit/test_tushare_connector.py -q` | 通过 | `26 passed`；exit=0（约 1.66s） |
| `ruff check src/quant/data/connectors/tushare.py tests/unit/test_tushare_connector.py` | 通过 | `All checks passed!`；exit=0 |
| `mypy --no-incremental src/quant/data/connectors/tushare.py` | 通过 | `Success: no issues found in 1 source file`；exit=0（同会话首次偶发 mypy INTERNAL ERROR，立即重跑同命令通过；报告以重跑结果为准） |
| `git diff --check` | 通过 | 零输出；exit=0 |

## 4. 清理与范围审查

- 临时代码 / 冗余：无
- 文档 / 示例 / 配置同步：仅本报告；不更新路线图或 Gate 勾选
- 范围外改动：无。本会话只写入白名单三文件；工作区另有既有未提交改动（backfill/planning/配置/其他文档等），均未触碰、未纳入本返工

## 5. 风险与交接

- 已知限制：本会话未兼任独立复验；未跑全量 pytest / 全量 Ruff/mypy；未做 Gate 终验；其他仍用 `isdigit()` 的非基金校验不在本任务范围
- 安全：无网络、无凭据、无外部状态修改
- 下一步：由**未参与本返工**的全新外部 Cursor 会话只读复验，并写 `docs/framework/agent/M3_G1_BENCH-B1A-R2_Unicode数字代码越层外部独立复验报告.md`；复验须另增实现者未用的 Unicode 数字类别，并核对三条 endpoint calls=0；通过后才回主 Agent 终验
