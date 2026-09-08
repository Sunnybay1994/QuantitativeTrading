# M3 G1 BENCH-B1A-R2：Unicode 数字基金代码越层返工任务单

## 1. 现象

B1A 完整外部初验通过后，主 Agent 未公开反例发现：connector 的 `_validate_fund_symbol` 使用
`str.isdigit()`，因此六个全角 Unicode 数字组成的 `５１０３００.SH` 被接受并调用 fake SDK；同一输入在
backfill `_A_SHARE = ^[0-9]{6}\.(SH|SZ)$` 会被拒绝。

## 2. 根因与被破坏规则

根因是 connector 与 request/backfill 层使用了不同字符集合的代码校验。`isdigit()` 接受多种 Unicode
数字，而冻结合同“六位 `.SH/.SZ` 可交易基金代码”在现有 SSOT 和 backfill 中指六位 ASCII `0-9`。

被破坏的不变量：同一外部标识在 connector、request 和 planner 各层必须具有相同接受集合；非法标识必须
在任何 SDK/IO 前 fail closed。不得让 connector 接受后续 receipt 合同必然拒绝的代码。

## 3. 最小复现

构造带 `fund_daily(**kwargs)` 计数的 fake client，调用：

```python
connector.fetch_fund_daily_raw(
    symbol="５１０３００.SH",
    start=date(2026, 1, 1),
    end=date(2026, 1, 2),
    fields="x",
)
```

返工前函数正常返回且 fake client 记录一次调用；正确行为是抛出稳定 `ValueError` 且 calls 为空。

## 4. 最小实现与白名单

外部返工实现 Agent 只允许修改：

- `src/quant/data/connectors/tushare.py`
- `tests/unit/test_tushare_connector.py`
- `docs/framework/agent/M3_G1_BENCH-B1A-R2_Unicode数字代码越层外部返工交付报告.md`

实现要求：

- `_validate_fund_symbol` 精确接受六个 ASCII `[0-9]` 加 `.SH/.SZ`；可以复用模块内已有明确正则或增加私有
  ASCII 正则，不得放宽其他证券/市场校验；
- 保持 `type(symbol) is str`，`bool` 和字符串子类合同不变；
- 不改变合法 `510300.SH/159919.SZ` 的 SDK 参数；
- 不修改 backfill、配置、其他 connector 验证器或生产行为。

## 5. 新增测试与通过条件

新增参数化测试至少覆盖全角数字 `５１０３００.SH` 与另一类非 ASCII 数字（例如 Arabic-Indic），并证明
`fund_daily/fund_adj/fund_div` 三个方法均在 SDK 前抛 `ValueError`、fake client calls 为零。合法 SH/SZ
回归继续通过。

通过条件：

```bash
python -m pytest tests/unit/test_tushare_connector.py -q
ruff check src/quant/data/connectors/tushare.py tests/unit/test_tushare_connector.py
mypy --no-incremental src/quant/data/connectors/tushare.py
git diff --check
```

返工后必须由未参与实现的全新外部 Cursor 会话只读复验并写
`docs/framework/agent/M3_G1_BENCH-B1A-R2_Unicode数字代码越层外部独立复验报告.md`。复验至少增加一个实现者未用的
Unicode 数字类别，并核对三条 endpoint calls=0；之后才回到主 Agent 终验。
