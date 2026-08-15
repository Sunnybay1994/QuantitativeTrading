# M1 HK-HISTORY R1：港股 Close 有界包络返工任务单

日期：2026-08-15  
状态：实现、外部独立初验与主 Agent 验收均 PASS；HK60 完整回填仍在继续  
实现模型：`cursor-grok-4.6-high`

## 1. 现象与证据

retained Tushare `01065.HK@2026-05-15` 为
`open=4.37, high=4.38, low=4.35, close=4.39`，现有 `Bar1dSchema` 因
`close > high` 拒绝。独立公开取证见
[`M1_01065_20260515_OHLC异常Cursor只读取证报告.md`](M1_01065_20260515_OHLC异常Cursor只读取证报告.md)：
Yahoo 与 Webb-site 均确认 `close=4.39`、`low=4.35`、成交量 `1,384,000`；
Webb-site 与 Tushare 均记录 `high=4.38`，Yahoo 则把 high 包络为 `4.39`。
因此本条按供应商 high/low 与收市价口径差异处理，不改写 retained raw。

## 2. 冻结规则

只修改 `TushareBarMapper` 的 HK canonical 投影：

1. A 股和非 HK 市场行为完全不变；`Bar1dSchema.ohlc_valid` 完全不变。
2. raw `open/high/low/close` 字节和值不改；mapper 只产生 canonical frame。
3. 原始 OHLC 均须有限且为正，且 `raw_high >= raw_low`。
4. 既有 HK open-only 包络保持：仅当 close 在原区间内时，允许 high/low 包含 open。
5. 新增 HK close-only 包络仅在以下条件同时成立时允许：
   - open 已在原 `[low, high]`；
   - close 恰在原区间一侧之外；
   - close 到最近边界的相对偏离不超过 5%，分母取该正的最近边界；
   - 结果为 `high=max(raw_high, raw_close)`、`low=min(raw_low, raw_close)`。
6. open 与 close 同时越界、偏离大于 5%、`high < low`、非正/非有限价格继续 fail closed。
7. 不在 data mapper 复制港交所价位表；价位有效期属于市场规则 SSOT。5% 在这里仅是脏数据防护上限，
   不宣称证明某笔 CAS 成交。

## 3. 文件白名单

- `src/quant/data/mappers.py`
- `tests/unit/test_tushare_connector.py`
- 必要时只同步现有直接说明该 mapper 行为的 README 段落
- `docs/agent/M1_HK-HISTORY-R1_港股Close有界包络返工交付报告.md`

不得修改 Schema、连接器、raw/evidence、回填 journal、其他生产模块或既有历史报告。

## 4. 必测反例

- 正向：本例映射后 high=`4.39`，并通过 `Bar1dSchema`；输入 raw high 仍为 `4.38`。
- 正向：close 略低于 raw low、open 仍在区间时有界扩展 low。
- 回归：现有 HK open-only 高于 high 与低于 low 均继续通过。
- 负向：SZ/A 股 close 越界继续拒绝。
- 负向：HK close 相对最近边界偏离大于 5% 继续拒绝。
- 负向：open 与 close 同时越界继续拒绝。
- 负向：`high < low`、零/负/NaN/Infinity 继续拒绝。

## 5. 开发检查

只运行相关 Tushare mapper 与 HK history 定向测试、Ruff、mypy；不得联网，不得重新请求 Tushare，
不得读取或输出 token。实现者只提交交付报告，不宣布 M1/HK60 Gate。
