# M1 HK-CA-P1B：HK 总回报研究价格 Development 发布任务单

日期：2026-08-09  
状态：实现、独立初验与主 Agent 终验 PASS（development contract/receipt）  
性质：来源无关 development 工程合同；不是正式 HK60/M1/ext4 Gate

## 1. 目标与边界

在 P1A 已主验通过的 `VerifiedHkTotalReturnApplicationPlan` 上，以 fresh-verified 未复权 HK 日线 close
构造 close-only gross total-return 研究价格，并发布一个身份不可混淆的 development 四文件产物。

本包不生成或冒充 `VerifiedG1Release`，不写正式 HK60、正式 journal、clean store 或正式发布根；不处理
RIGHTS、CNY FX、税费、withholding、账户 entitlement、可交易股数、OHLCV 复权或成交模拟。

现有 A 股 `TOTAL_RETURN_DIVIDEND` mapper 只有现金分红语义，没有 HK BONUS/SPLIT、PIT/fresh、停牌映射与
发布闭包，禁止调用或复制。新增 adjustment method SSOT 值：

```text
HK_GROSS_TOTAL_RETURN_V1
```

固定 source：`derived_hk_bar_and_ca_v1`。只在 `ResearchPrice1dSchema.adjustment_method` 的现有 `isin`
加入新值，不新增平行枚举，不扩展 ResearchPrice 五列。

## 2. 权威输入与公共接口

新增 `src/quant/data/hk_total_return_research_price.py`，仅公开窄入口：

```python
publish_development_hk_gross_total_return(
    *,
    application_plan: VerifiedHkTotalReturnApplicationPlan,
    context: HkTotalReturnFreshContext,
    development_root: Path,
) -> VerifiedDevelopmentHkGrossTotalReturnPublication

verify_development_hk_gross_total_return(
    *,
    publication_root: Path,
    application_plan: VerifiedHkTotalReturnApplicationPlan,
    context: HkTotalReturnFreshContext,
) -> VerifiedDevelopmentHkGrossTotalReturnPublication
```

两个入口在读取 plan/schedule/bar clone 和生成任何文件前，分别调用
`verify_hk_total_return_application_plan(application_plan, context=context)`；publication verifier 还必须 fresh
重建完整价格和元数据，不得只校验 hash。调用者必须保证从 fresh verification 到输入 clone/materialization
结束期间上游 quiescent；禁止用重复 sweep、mtime 或假锁伪装并发不可变保证。

返回 exact-final、process-local、不可 subclass/pickle/reload 的
`VerifiedDevelopmentHkGrossTotalReturnPublication`，至少暴露：

- cloned `research_prices`；
- `artifact_id`、resolved `publication_root`、`receipt_sha256`、`as_of`；
- exact `classification="development"`。

不得接收 caller 自报 artifact id、classification、source、method、公式版本或 hash。

## 3. 精确数值合同

输出 `(symbol, trade_date)` 域 exact 等于 fresh verified bars，按 `symbol,trade_date` 唯一严格排序。每个 symbol
首个 retained bar：

```text
adjusted_close_0 = raw_close_0
```

以后每个 retained bar `t`：

```text
M_t = 当日唯一 share-changing leg 的 share_multiplier；无则 1
C_t = 当日全部 HKD DIVIDEND 的 cash_per_share_gross_hkd 之和；无则 0
gross_factor_t = (M_t * raw_close_t + C_t) / raw_close_(t-1)
adjusted_close_t = adjusted_close_(t-1) * gross_factor_t
```

- BONUS 使用 P1A 的 `1 + stock_ratio`；SPLIT 使用 canonical `share_multiplier`。
- 同一 ex-date 的现金与 share leg 同时生效，必须是 `M * close + C`；禁止先将现金复投再乘 M。
- 冻结手算：previous close=100、application close=96、2:1 split、每旧股 gross cash=2，分子为194，
  不是196。
- DIVIDEND 在 ex-date 形成理论 gross entitlement，并在 P1A `application_trade_date` 的 close 理论复投；
  `pay_date` 只审计。BONUS/SPLIT 同样在 application bar 进入研究总回报；`stock_list_date` 不代表可卖日。
- 这是理论 close-price total return，不是现金账、股数账或可执行成交。

数值实现固定：所有输入用 `Decimal(str(value))`；每个 symbol 的完整递推位于
`localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN))`，中间不逐日量化；输出时量化到
`Decimal("0.000000000001")`（12 位小数，`ROUND_HALF_EVEN`）后转 Float64。逻辑内容 hash 使用量化后
exact 12 位十进制字符串，而不是 parquet 物理 bytes。任一非正、NaN、Inf、overflow 或 Decimal 异常拒绝。

公式版本固定 `HK_GROSS_TOTAL_RETURN_CLOSE_V1`；舍入版本固定
`DECIMAL50_HALF_EVEN_OUTPUT_12DP_V1`，二者进入 request/manifest/receipt/artifact identity。

## 4. 同日、停牌与生命周期

仅聚合 P1A `window_disposition="APPLY_IN_WINDOW"` 行，按 `(symbol, application_trade_date)` 分组，并在任何
dict/set 降维前验证：

- 同组全部行必须具有同一 `ex_date`；
- 允许任意多个 HKD DIVIDEND 求和；
- 允许至多一个 share-changing leg，即一个 BONUS 或一个 SPLIT；
- 允许多股息加一个 BONUS/SPLIT；
- 两个不同 ex-date 因连续停牌映射到同一恢复 bar，拒绝；
- 同一 ex-date 多个 share-changing leg，拒绝。

现有 canonical 数据没有 multiple-leg entitlement basis，禁止猜测相乘、相加或应用顺序。

ex-date 无 bar 时，P1A 已映射到第一个 retained recovery bar；previous close 是此前最后一个 retained bar。
不补系统日历，不生成缺失日期，不从 volume/amount 推断停牌或可执行复投。

`BASELINE_PREWINDOW` 不重复调整，`OUTSIDE_FUTURE_WINDOW` 不应用，但两者完整 schedule identity 仍进入
artifact identity；首 bar 是 listing/window anchor，last bar 后不外推，日期无需连续。

## 5. PIT/as_of

- 整包 knowledge cutoff exact 为 `context.as_of`；P1A fresh verifier 已证明 application bar availability
  `<= as_of`。
- 历史行不得表述为 trade_date 当日已知；下游只能在自身 research/model `as_of >= artifact.as_of` 时消费。
- 不从当前时间、mtime、pay/list date 或文件创建时间推断 availability；代码不得读取系统墙钟。

## 6. Development 发布合同

`development_root` 必须是 caller-created plain directory，resolved leaf name exact `development`，不允许
symlink/junction/reparse。固定布局：

```text
<development_root>/hk_gross_total_return_v1/<artifact_id>/
    request.json
    research_price_1d.parquet
    manifest.json
    receipt.json
```

固定元数据：

```text
classification = "development"
artifact_kind = "hk_gross_total_return_research_price"
gate_claim = "development_contract_only"
adjustment_method = "HK_GROSS_TOTAL_RETURN_V1"
formula_policy = "HK_GROSS_TOTAL_RETURN_CLOSE_V1"
rounding_policy = "DECIMAL50_HALF_EVEN_OUTPUT_12DP_V1"
source = "derived_hk_bar_and_ca_v1"
```

`artifact_id` 是路径无关逻辑身份，至少绑定以上固定元数据、aware UTC `as_of`、P1A plan identity/schedule
content/policy、P0 query/actions/evidence、implementation evidence/projection、bar plan/publication/bars/
availability identities及 canonical ResearchPrice logical content hash。

- `request.json`：完整 input identities、政策、as_of、request hash；
- parquet：exact `ResearchPrice1dSchema` 五列、exact key域与物理排序；
- `manifest.json`：request/parquet selector、SHA256、size、logical content hash、row/symbol/date summary；
- `receipt.json`：SUCCESS、request hash、manifest hash、artifact id、输入/输出摘要；receipt 不自含自身 hash。

物理 parquet SHA/size进入manifest/receipt，但不进入跨平台逻辑 artifact id；Windows与WSL逻辑 identity/行内容
必须一致，不强制 parquet bytes hash一致。

最终 artifact 目录 exclusive-create；已有 exact identity 完整目录只允许 fresh verify 后幂等返回，partial、额外
文件、异字节或漂移拒绝。四文件 exact，无嵌套目录；每文件 exclusive-create/no-clobber。进程内普通失败只
清理本次创建且 file identity 仍匹配的路径，不删预存/竞争文件。明确不声称断电崩溃原子、formal immutable
publish或ext4 Gate；不得导入/复制 `quant.research.m3._artifact_publication`、M1 daily/G1专用publisher。

## 7. OHLC/volume与存储禁止项

- 不发布/调整 open/high/low、volume、amount、`Bar1dSchema.adj_factor`；
- 不按 share multiplier 反向调整 volume；
- 不调用 `ResearchPriceUpdatePipeline`、A股 mapper、AKShare/Sina、connector、socket；
- 不写 `CleanResearchPriceStore`、正式 data/artifacts/journal/HK60 root；
- 不读取 `data/legacy`，不改 P0/PRE/PRE-B/P1A、M3/M4、connector/storage/backtest。

## 8. 失败语义

唯一 public error 类型，稳定 code：

```text
HK_TOTAL_RETURN_PRICE_INPUT_INVALID
HK_TOTAL_RETURN_GROUP_UNSUPPORTED
HK_TOTAL_RETURN_PRICE_INVALID
HK_TOTAL_RETURN_PUBLICATION_INVALID
HK_TOTAL_RETURN_IO_FAILED
HK_TOTAL_RETURN_VERIFY_FAILED
```

upstream fresh/type/as_of/domain错误映射INPUT或VERIFY；不同ex-date碰撞/多share leg映射GROUP；数值错误映射
PRICE；root/selector/hash/manifest/receipt漂移映射PUBLICATION；OS写失败映射IO。任何 hostile ValueError/
RuntimeError/递归异常图必须离开 active except 后重建，cause/context为None，repr/traceback不泄露path、raw、
SQL、TOKEN或source payload。失败不得返回 capability。

## 9. 白名单

- `src/quant/domain/schemas.py`
- 新 `src/quant/data/hk_total_return_research_price.py`
- `tests/unit/test_schemas.py`
- 新 `tests/unit/test_hk_total_return_research_price.py`
- 本任务单、唯一交付报告、唯一独立复验报告、主验报告

除非现有包根明确要求，不改 `domain/enums.py`、`domain/__init__.py`、`data/__init__.py`。新增依赖、改 storage、
改 P1A 或活跃 M3 文件均触发停止重冻。

## 10. 必测矩阵

至少覆盖：

1. exact capability、subclass/duck/object/pickle/reload；fresh P1A verifier必调用；
2. first close anchor、无行动递推、cash保持理论价值、BONUS、SPLIT；
3. dividend+split手算194而非196、多股息、shuffle identity；
4. 多share leg、不同ex-date压同一恢复bar拒绝；普通停牌恢复bar通过；
5. prewindow/future数值不变但identity绑定；pay/list不改应用日；
6. exact bar key域、生命周期、不补日期；Float/Decimal极值、NaN/Inf/非正；
7. request/parquet/manifest/receipt任一漂移、合法不同上游closure whole-resign、额外/缺失文件；
8. copied root、root replacement、symlink/junction/reparse、partial root、竞争抢占、rollback身份；
9. same identity replay fresh verify；hostile异常递归图；零network/store/clock；cold import；
10. Windows与WSL base逻辑artifact id及行内容一致。

验证定向 pytest、Ruff、mypy、cold import、diff/whitelist；WSL base路径若为wslfs/DrvFS只算兼容性，不是ext4。

## 11. 停止条件与通过表述

若 P1A fresh接口不足、需要猜multiple share-leg basis、需要RIGHTS/CNY FX/税费/账户、要求adjusted OHLCV、
要求正式root/journal/store、要求导入M3 private publisher或把Windows/DrvFS表述为formal Gate，立即停止回主Agent。

本包通过时只能表述“HK gross-total-return development contract与development receipt通过”。正式02983
metadata、licensed 01065 issue/spec、formal V3 migration、真实HK action source、HK60、M1与ext4 Gate仍开放。
