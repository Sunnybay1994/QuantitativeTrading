# M1 HK60：01065 R1 HKEX 官方无交易语义 Verifier 任务单

日期：2026-08-09（Asia/Shanghai）

状态：**边界冻结；来源前置未满足，取得 licensed issue + File Specification 并由主 Agent 裁定前停止生产实现。**

执行方式：用户当前要求由主 Agent 自行实现和验证；本任务书不授权外部网络写入、付费下单或正式数据写入。

## 1. 目标

为 `01065.HK@2026-05-05` 建立 retained-bytes-only、fail-closed 的 HKEX 官方无交易语义 verifier，关闭当前
`HKNoTradeEvidence` 只有字段/摘要闭包、没有从来源原文 fresh 推导 `NO_DAILY_TRADING_V1` 的缺口。

最终只有 verifier 创建的不可伪造 verified capability 才能投影为正式单 key `HKNoTradeEvidence`；调用方、
JSON、DataFrame、已解析对象和自报 digest 均不得直接创建正式 evidence。

本任务不执行 HK60 正式 recover/finalize，不修改旧 R1 plan/journal，不处理 `02983.HK@2026-07-10`、港股复权
链、U0C 或 WSL/ext4 Gate。

## 2. 权威来源与已知边界

现有 evidence 合同冻结 `source=HKEX_DAILY_QUOTATIONS`。与其精确匹配的来源为 HKEX 历史产品
**Main Board Daily Quotations / All Sales Record**：

- [HKEX 产品说明](https://www.hkex.com.hk/eng/ods/historicalDataProfile.aspx?ProductID=Voc2mzqRTLcOkLV5QD6S7d4cwJlTih%2FplEeBfKIyoSKkQBfMDbHLiwj9xdBPkILv&SchemeID=T6LrwO0wH3aVWVwxhC6XHj7vLSwo3XSaaL%2BVu96h2WQ%3D)
  说明它是当日收市报告集，包含 Quotation Sheet、Sales Records for All Stocks 等，主报告通常约 19:00
  发布，Daily Quotation Supplement 通常约 20:00 发布。
- [HKEX 历史产品目录](https://www.hkex.com.hk/eng/ods/historicalData.aspx) 将该产品列为按日发行、按月订阅、
  在线下载。
- [HKEX Daily Quotations 旧版格式样例](https://www.hkex.com.hk/eng/market/partcir/sehk/Documents/CTMO05610E1.pdf)
  公开展示 `QUOTATIONS`、`SALES RECORDS FOR ALL STOCKS`、`AMENDMENT RECORDS FOR TRADES`
  等章节，并展示 quotation 可出现 `TRADING SUSPENDED`。
- [HKEX 2023 年章节清单](https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2023/CT15723E1.pdf)
  再次确认 Daily Quotations 包含 quotation、全量 sales、trade amendments 等章节。
- [HKEX Data Marketplace User Guide v3.0](https://www.hkex.com.hk/Services/Market-Data-Services/Historical-Data-Services/-/media/08660B4BD3874369BAFF9CE983ED98FD.ashx)
  说明 licensed data 的注册、购买和下载流程。

### 2.1 本轮未找到的官方资料

截至任务冻结时，没有在 HKEX 官方公开页面中取得下列资料：

1. 当前 Main Board Daily Quotations / All Sales Record 的完整 File Specification；
2. 与 2026-05-05 licensed issue 同版的官方 sample/schema；
3. 主报告、supplement、late amendment/correction 的完整文件命名、record code、字段位置和强制集合规则；
4. 目标 issue 的编码声明、archive/member 结构、EOF/trailer/count/checksum 规则；
5. `TRADING SUSPENDED` 对全日/盘中状态的精确定义，以及零 shares/turnover、空 sale block 的官方语义。

[HKEX 历史数据 General FAQ](https://www.hkex.com.hk/Global/Exchange/FAQ/Market-Data/Getting-Market-Data/Historical-Data/General?sc_lang=en)
表示多数产品的 User Guide/File Specification 和 sample 会在产品信息页提供，但旧平台已退役且公开产品页未
呈现本产品的这些链接。不得把旧版格式样例当作 2026 licensed issue 的完整规范。

### 2.2 强制停止条件

在以下资料全部取得并由主 Agent 写入本任务书的“来源冻结补充”前，生产代码和生产测试不得开始：

- 许可允许留存/内部验证的 2026-05-05 完整官方 issue；
- 当次投递的 product/technical details、File Specification、sample/readme/manifest（实际提供的全部）；
- HKEX 对该 issue 是否存在 supplement/correction，以及何时可视为最终文件集合的权威说明；
- 每个 retained file 的官方文件名、role、byte size、SHA-256 和真实 encoding；
- 主 Agent 对 target quotation、sale、amendment、suspension/no-trade 语义的逐项裁定。

以下值全部留空，届时只能由真实 bytes/spec 填写：文件名、member 名、固定 digest/size、encoding、字段列宽、
record code、flag 集合、section anchor、trailer/count 规则、supplement 缺省规则、`source_record_id`。实现 Agent
不得从 `d260505e.htm` 命名模式、2026-07-10 的 02983 parser 或旧版 PDF 猜测这些值。

## 3. 冻结外部合同

### 3.1 新模块与 public capability

新增专用来源模块，避免放宽已验收的 02983 正成交 parser：

```text
src/quant/data/hkex_no_trade_evidence.py
```

冻结概念接口；具体参数名可在来源补充时按真实文件集合做最小调整：

```python
verify_hkex_01065_no_daily_trading(
    *, retained_bundle_manifest: bytes, retained_files: dict[str, bytes]
) -> VerifiedHKEXNoDailyTrading
```

- input 只接受 exact built-in bytes 和按官方文件名索引的 exact built-in `dict[str, bytes]`；入口先形成不可变
  snapshot，再做任何解析。不接受路径、任意 Mapping、DataFrame、parsed/finding/evidence 对象。
- `VerifiedHKEXNoDailyTrading` 为 final capability：公共构造失败、禁止 subclass、禁止 mutation/pickle 旁路；仅
  verifier 的私有 factory 在所有 fresh 校验后创建。
- capability 绑定 bundle identity、每个文件 identity、parser/spec version、source/product/issue、
  `01065.HK@2026-05-05`、no-trade finding、独立 suspension finding 及 semantic evidence ID。
- `hk_history_backfill` 的正式 projection 只接受 exact capability，并在投影前 fresh rebuild/validate capability；
  禁止接受 capability 子类、SimpleNamespace、mapping 或调用方自报 hash。

现有 `hkex_daily_quotations.py` / `VerifiedHKEXDailyQuotation` 的 02983 行情合同保持不变，不为本任务做通用化重构。

### 3.2 retained raw bundle

现有 `HKNoTradeEvidence` 只有一个 `raw_selector/raw_file_sha256`。为保持 evidence schema v1 和 plan v2 wire 兼容，
本任务冻结一个 canonical bundle-manifest 文件作为该 selector 指向的 retained source envelope：

```text
schema_version = hkex-no-trade-retained-bundle-v1
source = HKEX_DAILY_QUOTATIONS
product_identity = <source-freeze value>
issue_date = 2026-05-05
files = sorted exact entries[
  official_name, role, selector, byte_size, sha256
]
bundle_sha256 = canonical identity of all preceding fields
```

- manifest 必须为 UTF-8 canonical JSON（唯一 key、sort key、紧凑分隔符、尾部无额外字节）；entries 按
  `(role, official_name)` 严格排序且 selector 唯一。
- evidence 的 `raw_selector` 指向该 manifest；`raw_file_sha256` 是 manifest bytes SHA-256；现有严格 metadata
  sidecar 继续绑定 manifest selector/hash/source/source record/as-of。
- manifest 中每个 selector 必须是 raw root 下无 `..`、无绝对路径、无 symlink/reparse escape 的 POSIX 相对路径；
  每次 load 必须 fresh read 并核对每个文件 size + SHA-256，不能只相信 manifest。
- 若 HKEX 投递原始 archive，同时保留 archive bytes；若 verifier 需要解析 member，manifest 同时绑定 archive 和
  实际参与语义验证的原始 member bytes。不得通过重编码 HTML、复制目标片段或自行重打包来替代官方原件。
- exact file set 必须包括 main report、Daily Quotation Supplement 以及 correction/amendment/readme/manifest 中
  对该 issue 语义有影响的全部文件。若官方明确该日“未发行 supplement/correction”，必须由官方投递 manifest、
  technical details 或留存书面答复绑定这一事实；调用方少传文件不等于官方未发行。
- 额外、缺失、重复、role 冲突、case-fold 文件名碰撞、重复 archive member、加密/损坏 archive、路径穿越、
  selector escape、文件 digest/size 漂移全部 fail closed。

### 3.3 fresh 来源与结构验证

verifier 每次调用必须按顺序：

1. fresh digest 完整 manifest 与全部 retained files；验证 exact file set 后才 decode/parse；
2. 使用来源冻结补充中的唯一 encoding，严格 decode；未知/替换字符、BOM 漂移、混合换行若不在规范内即失败；
3. 精确验证 product/report title、Main Board market、issue/trade date `2026-05-05`、文件 role 和最终性标记；
4. 精确验证所有 required section/record/trailer/count，确保文件未在 target、sales、amendment 或 EOF 前截断；
5. 对 target code `01065` 做全文件扫描；所有命中必须落在规范允许的已解析 record 中。目标重复、落在未知
   record、未知 flag/status 或任何未消费文本中的命中均失败；
6. 解析 target quotation、全部 target sales、amendment/correction/supplement；不同文件的结论必须一致且
   freshness 闭合；
7. 完成 no-trade 与 suspension 的独立裁定后才创建 capability。

解析器无需为本任务解释所有其他证券的业务字段，但必须用官方 section/count/trailer 证明全文件完整，并拒绝
target code 出现在任何未识别位置。任何 unknown target-related record/status/flag 必须 fail closed；不得“忽略后
继续”。

## 4. no-trade 与 suspended 必须分离

冻结两个正交 finding：

```text
no_daily_trading: VERIFIED_TRUE | REJECT
suspension_status: <source-freeze enum, never used as no-trade shortcut>
```

- `NO_DAILY_TRADING_V1` 表示该证券当日没有任何可形成日线的交易；它不是“接口没返回”、零成交量 bar、
  quotation 缺行或 generic suspension 的同义词。
- `TRADING SUSPENDED` 只是一条 quotation 状态。若 sales/amendment/supplement 中存在任一有效成交，哪怕显示
  suspended，也必须拒绝 no-trade evidence；这覆盖盘中停牌/复牌或更正交易。
- 没有 suspension 标记也不自动表示有交易。只有官方 spec 明确 quotation 零值/空 sales 的语义，且 main +
  supplement/correction 的完整交易记录均为零，才可裁定 no-trade。
- target quotation 缺失、只在 suspension list 出现、只在 sales 中缺席、shares/turnover 使用未知占位符或状态
  语义不明，统一 REJECT；不得降级为猜测。
- 正式 evidence 仍只投影 `reason=NO_DAILY_TRADING_V1`；suspension finding 只进入 capability identity/
  source audit，不增加或替换现有 reason 枚举。

## 5. evidence projection 与 load 集成

`load_hk_no_trade_evidence()` / `_verify_evidence_projection()` 对
`source=HKEX_DAILY_QUOTATIONS` 的真实 `01065.HK@2026-05-05` 必须：

1. fresh 读取 evidence 指向的 bundle manifest 和全部 raw files；
2. 调用 public retained-bytes verifier，重新取得 exact capability；
3. 从 capability 内部投影 expected evidence 字段并与 on-disk evidence 逐字段相等比较；
4. 重新计算 `evidence_sha256`、metadata SHA 和 evidence-set identity；
5. 任一不等、verifier 异常或 capability 非 exact type 返回 `HK_HISTORY_REFERENCE_INVALID`，并从空异常链抛出。

正式 evidence JSON 不再由调用方传入 semantic fields 后直接接受。建议新增一个窄的 write-once materializer，输入
exact capability + frozen selector/as-of，只能生成 canonical metadata/evidence/evidence-set bytes；目标存在异值
时 no-clobber 失败，重复同字节幂等。

来源 verifier 自身稳定失败码冻结为 `HKEX_NO_TRADE_EVIDENCE_INVALID`；进入 HK history 公共边界时统一映射为
`HK_HISTORY_REFERENCE_INVALID`。错误不得包含原始行、绝对路径、订单信息、账户或许可内容。

## 6. 文件白名单

来源前置补充完成后，实施只允许修改：

生产代码：

- `src/quant/data/hkex_no_trade_evidence.py`（新增）
- `src/quant/data/hk_history_backfill.py`（capability projection + fresh load 集成）

测试：

- `tests/unit/test_hkex_no_trade_evidence.py`（新增）
- `tests/unit/test_hk_history_backfill.py`

文档：

- 本任务书的来源冻结补充
- `docs/agent/M1_HK60_01065_R1_HKEX官方无交易语义Verifier交付报告.md`

若真实 File Specification 证明现有 `HKNoTradeEvidence` / metadata schema 无法表达官方 bundle，必须停止，由主
Agent 先裁定是否修改 `src/quant/domain/schemas.py` 及迁移/兼容范围；不得自行扩大白名单或静默改变 plan v2。

## 7. 强制最小反例

来源补充后，用最小 synthetic fixture 覆盖且明确标记为非官方：

1. exact main + supplement/correction、target 无任何成交：capability 创建并投影单 key evidence。
2. main 显示 `TRADING SUSPENDED`，sales 中有一笔 target trade：拒绝。
3. main 无成交，supplement 或 amendment 新增/更正一笔 target trade：拒绝。
4. 缺 supplement；或调用方声称“当日无 supplement”但没有官方 file-set 事实：拒绝。
5. manifest/任一 raw 一字节、size、文件名、role、selector、case、顺序漂移：拒绝。
6. archive 有重复 member、路径穿越、加密 member、额外未冻结 target-related file：拒绝。
7. 日期为相邻交易日、GEM 报告、其他证券 code/name、target quotation 重复：拒绝。
8. sales/amendment 章节前截断、EOF/trailer/count 不闭合：拒绝。
9. target 出现在未知 record/flag/status 或未消费文本：拒绝。
10. quotation 缺 target，但 sales 也没有 target；只有 supplier 0 行；只有 suspension 公告：均拒绝。
11. 解析结果、mapping、DataFrame、SimpleNamespace、伪造/子类/recomputed identity capability：拒绝。
12. 合法 raw/evidence 生成后替换 raw 并同步改 on-disk hash/metadata/evidence identity：fresh verifier 仍拒绝。
13. 同一 capability 重复 materialize：字节相同；目标已有任一异值：no-clobber 拒绝。
14. stable error 的 `__cause__` / `__context__` 为空，错误中无路径、原始行和订单信息。

实现者还必须基于真实 File Specification 增加至少一个任务书未列出的 target-related record/format 对抗反例。

## 8. 禁止项

- 禁止真实网络请求、Tushare/BaoStock/HKEX 调用或测试时读取 licensed/formal raw。
- 禁止把公开页面 404、搜索缓存、targeted 0 行、相邻日有行情或公告缺失当成 no-trade evidence。
- 禁止修改/复用旧 R1 journal、原地更新旧 plan、补造 OHLC/零成交量 bar或把别的官方产品标成
  `HKEX_DAILY_QUOTATIONS`。
- 禁止扫描 `data/legacy/`、正式 G1 候选/发布根或其他正式数据目录。
- 禁止为减少文件数量省略 supplement/correction 闭包；禁止用 Windows 绿测表述 Linux Gate 通过。
- 禁止在来源冻结补充完成前实现任何 production parser 或用 02983 的硬编码格式外推 01065。

## 9. 验证边界

来源补充和实现完成后至少执行：

Windows 原生 Miniforge：

```text
$env:PYTHONPATH='src'
D:\Miniforge3\python.exe -m pytest tests/unit/test_hkex_no_trade_evidence.py tests/unit/test_hk_history_backfill.py -q -p no:cacheprovider --basetemp .pytest-hkex-no-trade-r1-win
D:\Miniforge3\python.exe -m ruff check src/quant/data/hkex_no_trade_evidence.py src/quant/data/hk_history_backfill.py tests/unit/test_hkex_no_trade_evidence.py tests/unit/test_hk_history_backfill.py
D:\Miniforge3\python.exe -m mypy src/quant/data/hkex_no_trade_evidence.py src/quant/data/hk_history_backfill.py
```

WSL Miniforge `base` 对同一文件集运行定向 pytest、Ruff、mypy，使用唯一 basetemp。Windows 与 WSL/DrvFS
结果只证明双平台开发合同；Linux 平台特有发布终验仍需 WSL base + ext4，Windows 或 WSL1/DrvFS 绿色不得
关闭该 Gate。

正式 licensed bytes 不进入普通 pytest fixture、不提交 Git、不输出到日志/报告。实现通过后另做一次有界、显式、
零网络 retained-byte probe；只报告 digest/identity/稳定状态码，不回显原文或许可内容。

## 10. 通过条件与后续顺序

本任务只有同时满足以下条件才可标记工程 PASS：

1. 来源冻结补充由主 Agent 基于 licensed bytes/spec 完成，没有猜测字段；
2. exact raw bundle 每个文件 fresh digest + exact file-set + semantic parse 闭合；
3. no-trade 与 suspended 分离，target 所有 sale/amendment/supplement 路径为零；
4. only-verifier capability 和 evidence projection 防伪反例通过；
5. Windows 与 WSL base 定向 pytest/Ruff/mypy 通过；
6. diff 只含白名单，`git diff --check` 通过。

工程 PASS 后仍须由主 Agent使用 licensed retained bytes 生成真实 evidence，建立全新 v2 plan/journal，零网络恢复
已有 raw，再按冻结节奏完成剩余请求与正式 finalize。只有双 Route HK60 和对应平台 Gate 实际通过后，才可关闭
HK60/M1 子项。
