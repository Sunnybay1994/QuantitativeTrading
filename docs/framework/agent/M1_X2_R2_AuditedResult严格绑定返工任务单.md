# M1-X2-R2 Audited Result 严格绑定返工任务单

日期：2026-07-18  
角色：主 Agent 在 R1 独立复验后补充主验反例；实现与复验必须使用不同全新外部会话  
状态：已授权实施；R1 数值公式保持通过，不关闭 M1 或任何 Gate

## 1. 返工问题闭环

### R2-A — coverage 接受非 canonical symbol

- 现象：`missing_symbols=("not-a-symbol",)` 且其他计数一致时可成功构造 `BarWindowCoverage`。
- 根因：`__post_init__` 只校验 symbol 为 `str`、排序、唯一和 missing/short 不相交，没有使用领域 SSOT 的
  canonical symbol 格式。
- 应遵循规则：初始 X2 任务要求严格 typed result，错误摘要只含 canonical symbols；证券格式 SSOT 是
  `quant.domain.schemas.SYMBOL_PATTERN`，不得复制第二套正则。
- 最小复现：eligible=1、returned=0、missing=`("not-a-symbol",)`、min=max=0。
- 新增测试：missing/short 分别使用空字符串、非 canonical、错误市场后缀；均稳定抛
  `BAR_WINDOW_INPUT_INVALID`。合法 A/H canonical 代码保持通过。
- 通过条件：所有 coverage symbol 字段 canonical；不修改 Schema SSOT。

### R2-B — `AuditedBarWindow` 可绑定互相矛盾的 frame/coverage

- 现象：coverage 声称 eligible=returned=1、requested=min=max=2、full window，但
  `AuditedBarWindow(frame=pl.DataFrame(), coverage=coverage)` 成功。
- 根因：`AuditedBarWindow.__post_init__` 只做对象类型检查，没有验证 frame 的 key/source/as_of/counts/order 与
  coverage 闭合。
- 应遵循规则：初始任务要求 coverage/result 两个值对象都不可变、严格校验，并把 membership/bar payload
  一次性绑定；不能让调用方构造“审计摘要与 payload 分离”的伪证据。
- 最小复现：上述 full coverage + empty frame。
- 通过条件：构造期稳定抛 `BAR_WINDOW_INPUT_INVALID`；库查询的合法 empty/all-missing/short/full 结果保持通过。

## 2. 冻结绑定合同

`AuditedBarWindow.__post_init__` 至少验证：

1. `frame` 必须是 `pl.DataFrame`，`coverage` 必须是精确 `BarWindowCoverage`。
2. 空 frame 只允许 `coverage.returned_symbol_count == 0`、`max_observations == 0`；既支持 eligible=0 真空池，也
   支持 eligible>0/all-missing。
3. 非空 frame 必须含 `symbol`、`trade_date`、`source`，三列无 null，类型分别为 String/Date/String；不得因
   缺列、错误 dtype 或 cast 猜测而继续。
4. frame 每行 `source == coverage.source`，`trade_date <= coverage.as_of`；
   `(symbol, trade_date, source)` 唯一；所有 frame symbol 使用 `SYMBOL_PATTERN`。
5. frame 按 `symbol, trade_date` 已确定排序；手工乱序 payload 拒绝，不在值对象内静默排序。
6. frame unique symbol 数必须等于 `returned_symbol_count`；frame symbols 与 `missing_symbols` 不相交；每证券行数
   在 `[1, requested_observations]`。
7. 从 frame 实际逐证券计数重新推导 short tuple、min/max（missing 存在时 min=0），必须逐字段等于 coverage；
   coverage 已声明 full 的证券必须在 frame 中恰有 requested 行。
8. coverage 不保存完整 eligible symbol 列表，因此本包不能凭空验证未出现在 frame/missing/short 中的 full symbol
   具体身份；但数值守恒、canonical 和 payload counts 必须闭合。不得扩 Schema 或发明名单。

错误仍统一为 `BarWindowQueryError("BAR_WINDOW_INPUT_INVALID")`，不得泄漏 frame、路径或 SQL。

## 3. 文件白名单

- `src/quant/data/query.py`
- `tests/unit/test_query.py`
- `docs/framework/agent/M1_X2_R2_AuditedResult严格绑定返工交付报告.md`

禁止修改 `query_universe.py`、README、其他生产/测试、Schema、配置、`data/**`、`artifacts/**`、`.git` 和既有
任务/交付/复验报告；禁止联网和真实查询。

## 4. 验证与职责分离

实现使用全新 `cursor-grok-4.5-high`；Windows 使用 `D:\Miniforge3\python.exe`，Linux 使用 WSL
`/home/mabw/AI_Coding_win/QuantitativeTrading` Miniforge base。最低命令：

```text
pytest tests/unit/test_query.py tests/unit/test_query_universe.py -q -p no:cacheprovider
ruff check src/quant/data/query.py tests/unit/test_query.py
mypy src/quant/data/query.py
```

实现停止后另一全新外部会话只读复验，唯一允许写：
`docs/framework/agent/M1_X2_R2_AuditedResult严格绑定独立复验报告.md`。

复验须增加实现者未用反例：

- coverage short count 与 frame 实际 count 相同，但 symbol 不同；
- full+short frame 的 coverage min/max 正确但 returned 数伪造；
- frame 含未来行、异源行、重复 key 或乱序行；
- 合法 empty、all-missing、short-only、full+short、full-window 查询结果仍能构造且两平台一致。

## 5. 停止条件

- 需要扩 Schema、保存完整 eligible symbols、改变旧查询语义或 strict CLI 行为；
- 通过静默排序、去重、cast、丢行来“修复”矛盾 payload；
- 触碰白名单外文件、真实数据、网络或凭据。
