# M3 G1 BENCH-B1A-R2：Unicode 数字代码越层外部独立复验报告

日期：2026-07-22  
角色：外部独立复验 Agent（全新会话；未参与返工实现）  
模型：`cursor-grok-4.5-high`  
任务单：[`M3_G1_BENCH-B1A-R2_Unicode数字代码越层返工任务单.md`](M3_G1_BENCH-B1A-R2_Unicode数字代码越层返工任务单.md)  
交付报告：[`M3_G1_BENCH-B1A-R2_Unicode数字代码越层外部返工交付报告.md`](M3_G1_BENCH-B1A-R2_Unicode数字代码越层外部返工交付报告.md)  
状态：**本项独立复验通过**；**不声称 B1A / M3 G1 / 任何 Gate 或主验通过**

## 1. 范围与只读约束

- 生产代码、现有测试、交付报告：只读
- 本会话唯一写入：本复验报告
- 未改任何生产/测试文件；未调用真实网络/Tushare；未做 Gate 终验

## 2. 逐项核对（独立重跑，非复述交付报告）

环境：WSL `/home/mabw/AI_Coding_win/QuantitativeTrading`；经 `/home/mabw/miniforge3/bin/conda run -n base`。

| 成功标准 | 复验结果 | 证据摘要 |
|---|---|---|
| `_validate_fund_symbol` 精确接受 ASCII `[0-9]{6}.(SH\|SZ)` | 通过 | `_FUND_SYMBOL = re.compile(r"^[0-9]{6}\.(?:SH\|SZ)$")`；与 backfill `_A_SHARE.pattern` 字符串全等；`isdigit()` 已不在基金路径 |
| 三端点 IO 前失败且 calls=0（实现者全角 / Arabic-Indic） | 通过 | 独立探针：`５１０３００.SH`、`٥١٠٣٠٠.SH` 各 3 次 `ValueError`（含「基金代码」）；`calls=[]` |
| 合法 `510300.SH` / `159919.SZ` 回归、SDK 参数不改写 | 通过 | 独立探针 `legal_ok=True`：三端点 `ts_code`/`start_date`/`end_date`/`fields` 与输入一致 |
| `type(symbol) is str` 合同保留 | 通过 | 源码仍 `type(symbol) is str`；既有 `True` 等非法用例仍在 `test_fund_raw_methods_reject_before_any_sdk_call` |
| 白名单 | 通过 | 本返工相关变更仅见白名单：`tushare.py`、`test_tushare_connector.py`、交付报告；未触碰 backfill/配置/其他校验器生产行为 |
| WSL 定向验证 | 通过 | 见下表 |

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/unit/test_tushare_connector.py -q` | `26 passed`；exit=0（约 1.53s） |
| `ruff check src/quant/data/connectors/tushare.py tests/unit/test_tushare_connector.py` | `All checks passed!`；exit=0 |
| `mypy --no-incremental src/quant/data/connectors/tushare.py` | `Success: no issues found in 1 source file`；exit=0 |
| `git diff --check -- …tushare.py …test_tushare_connector.py` | 零输出；exit=0 |

三端点调用顺序核对（源码只读）：`fetch_fund_daily_raw` / `fetch_fund_adj_raw` / `fetch_fund_div_raw` 均在 `self.client.fund_*` 之前调用 `_validate_fund_symbol`。

## 3. 实现者未使用的第三类 Unicode 数字反例

实现者测试仅覆盖：全角 `５１０３００.SH`、Arabic-Indic `٥١٠٣٠٠.SH`。

本复验新增 **Devanagari 数字**（U+0966..U+096F）`५१०३००.SH`（codepoint：`0x96b,0x967,0x966,0x969,0x966,0x966`）：

- 对照：`"५१०३००".isdigit() is True`（证明旧 `isdigit()` 口径会错误接受）
- `_FUND_SYMBOL.fullmatch` / backfill `_A_SHARE.fullmatch` 均为拒绝
- `fund_daily` / `fund_adj` / `fund_div` 三端点均抛 `ValueError`（消息含「基金代码」）
- fake client **`calls=[]` / `calls_len=0`**（三端点合计零 SDK 调用）

## 4. 范围与交接观察

- 其他非基金路径仍可能使用 `isdigit()`（如 `_validate_a_share_symbol` / `_market`）；按任务单不在本返工范围，不据此否决本项。
- 工作区另有既有未提交改动；本复验未写入、未扩大修复。
- 下一步：交回主 Agent 终验；本报告**不**宣布 Gate 关闭。
