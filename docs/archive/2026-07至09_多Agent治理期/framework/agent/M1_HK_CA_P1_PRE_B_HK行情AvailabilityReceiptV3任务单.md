# M1-HK-CA-P1-PRE-B：HK 行情 Availability Receipt v3 任务单

日期：2026-08-09  
状态：R4 已通过实现自测、全新独立复验与主 Agent 最终验收；仅关闭开发态 PRE-B 合同  
性质：开发合同与未来 formal migration 前置；本包不修改当前正式 HK60 数据/journal

## 1. 触发原因

P1-PRE 实现前审计确认，当前 HK history publication 不能 source-verifiably 产生逐 bar `bar_available_at`：

- seed raw metadata 有 `fetched_at` 且 plan 绑定 raw/metadata hash，但 finalize 不投影每个 seed key；
- Tushare request raw metadata有 `fetched_at`，request receipt绑定 raw/metadata hash，但 finalize不投影每个 key
  到 exact request；
- HKEX 02983 supplement 的 verifier/finalize只绑定 evidence id、raw SHA、source record id和内容摘要，
  没有 canonical retained metadata、observed/fetched/published time；
- `finalize.json` 没有 exact key→retained source/availability 的完整映射。

因此 legacy finalize v1/v2 仍可按原合同使用，但不得签发 `VerifiedHkBarBundle`。本包新增 v3，不通过
trade_date、系统时钟、文件 mtime 或调用方自报时间补洞。

## 2. 核心裁定

`bar_available_at` 在本包采用保守 retained-observation 语义：该 bar 对当前 artifact builder 最迟从何时起被
本地 retained source 明确持有。它不声称历史交易日当时的官方最早发布时间，也不替代信号/成交时间规则。

- seed/Tushare request：使用 fresh 验真的 canonical raw metadata `fetched_at`；
- HKEX supplement：使用新增 canonical retained metadata `source_observed_at`；
- `bar_available_at <= artifact as_of` 才可消费；
- 若未来需要“官方最早发布时间”，必须另立 source-specific published-time合同，不能重新解释 v3 字段。

## 3. HKEX retained metadata

在 `hkex_daily_quotations.py` 新增 strict `HKEXDailyQuotationRetainedMetadata`（或等价冻结值对象），exact fields：

- `schema_version = hkex-daily-quotation-retained-metadata-v1`；
- `source = HKEX_DAILY_QUOTATIONS`；
- `source_record_id`；
- `report_trade_date`、market identity；
- aware UTC `source_observed_at`；
- `raw_file_sha256`；
- optional source issue/version identity（只有来源明确提供时）；
- metadata identity。

新增 verifier 必须接收显式 `retained_raw: bytes` 与 `retained_metadata: bytes`，要求 metadata canonical JSON、
fresh raw/metadata hashes、trade date/market/source record与解析结果精确一致，随后生成 content-bound verified
bundle。不得从 mtime、当前时间、路径名、URL或调用方普通 datetime构造正式 metadata。

现有仅 raw bytes API 可保留兼容，但其结果不能进入 availability v3 capability；exact-type隔离。

## 4. Availability evidence Schema

在 `schemas.py` 新增 `HkBarAvailabilityEvidenceSchema`，每个 effective bar key精确一行：

- `symbol`、`trade_date`；
- `source`；
- `availability_source_kind`：`SEED_RAW`、`REQUEST_RAW`、`HKEX_SUPPLEMENT`；
- `bar_available_at`：aware UTC；
- `source_record_id`；
- `request_id` nullable（REQUEST必填，其余为空）；
- `raw_file_sha256`、`raw_metadata_sha256`；
- `request_receipt_sha256` nullable（REQUEST必填）；
- `plan_sha256`；
- `availability_evidence_sha256`。

strict schema、exact unique `(symbol, trade_date)`；kind与nullable字段互斥；时间/摘要均 finite/规范。

## 5. finalize v3

`finalize_hk_history` 增加窄 v3 输入，不破坏 legacy调用：

- v3若包含 HKEX supplement，必须传 verified retained raw+metadata bundle；只有 raw bytes时维持v2行为但不能
  产生availability capability；
- fresh验证seed raw metadata、每个request raw metadata/receipt、HKEX retained bundle；
- 为每个 effective expected key确定唯一来源：seed、某个request或HKEX supplement；
- source exact set必须无重叠/缺失；同key多来源即使值相同也拒绝；
- 输出 canonical availability evidence content与digest；
- `finalize.json schema_version = hk-history-finalize-v3` 绑定 plan、clean content、row count、availability
  content digest、exact source receipt set、HKEX raw+metadata/evidence identity；
- canonical receipt独占/no-clobber；失败不留下半 v3 receipt或半 evidence。

legacy v1/v2 finalize bytes不得原地改写。正式02983/未来01065若需要v3，必须在单独授权的migration/finalize
步骤生成新journal/release identity。

## 6. VerifiedHkBarBundle

在 `hk_history_backfill.py`（或经主Agent重冻后的窄新模块）实现：

```python
load_verified_hk_bar_bundle(
    *, plan, journal_root, seed_raw_root, raw_store, clean_root, as_of
) -> VerifiedHkBarBundle

verify_hk_bar_bundle(
    bundle, *, plan, journal_root, seed_raw_root, raw_store, clean_root, as_of
) -> None
```

规则：

1. 只接受 v3 finalize + availability evidence；v1/v2返回稳定 unsupported；
2. fresh重验 plan/journal binding、seed、全部request receipts/raw metadata、HKEX bundle、finalize canonical bytes；
3. 只读取plan exact partitions/keys，不扫描全data/legacy；
4. `Bar1dSchema`、5位`.HK`、`adj_factor == 1.0`、exact effective keys、row count/content digest；
5. availability exact keys与bars一一同序，所有 `bar_available_at <= as_of`；
6. capability绑定resolved journal/seed/raw/clean roots和各物理identity；复制/替换/symlink/reparse/TOCTOU拒绝；
7. process-local content-bound attestation，不可pickle/reload，普通frame/dataclass/摘要不能冒充；
8. public verifier fresh重建全部语义，不信capability缓存。

## 7. 失败语义

- `HK_HISTORY_AVAILABILITY_UNSUPPORTED`
- `HK_HISTORY_AVAILABILITY_INVALID`
- `HK_HISTORY_FINALIZE_V3_INVALID`
- `HK_BAR_PUBLICATION_INVALID`
- `HK_BAR_VERIFY_FAILED`

事务/busy与semantic drift不得混淆。hostile reader/parser/schema异常固定脱敏，cause/context均None，traceback无
路径、raw、TOKEN、SQL或marker。

## 8. 写入白名单

```text
src/quant/domain/schemas.py
src/quant/domain/__init__.py
src/quant/data/hkex_daily_quotations.py
src/quant/data/hk_history_backfill.py
tests/unit/test_schemas.py
tests/unit/test_hkex_daily_quotations.py
tests/unit/test_hk_history_backfill.py
docs/framework/agent/M1_HK_CA_P1_PRE_B_HK行情AvailabilityReceiptV3交付报告.md
```

禁止 connectors/network、HK60/U0C/G1 roots、正式 journal/data迁移、research price/backtest、依赖/enums。

## 9. 必测反例

1. legacy v1/v2尝试签发bar capability；
2. HKEX仅raw无metadata，metadata非canonical、mtime/now自报、observed future；
3. seed/request metadata fetched_at、raw/metadata/receipt任一漂移；
4. effective key缺失、额外、重复、跨两来源重叠；
5. request id/expected dates与bar key错配；
6. HKEX report date/market/source record与bar错配；
7. finalize/evidence/clean整包重签或whole-rehash后复用旧attestation；
8. copied/replaced/symlink roots与验证窗口TOCTOU；
9. `adj_factor != 1`、非HK symbol、future availability；
10. v3第二文件写失败、竞争抢占、rollback失败与no-clobber；
11. hostile异常脱敏；
12. 两证券三日、一个停牌/no-trade effective key、一个HKEX supplement的最小全链fixture。

## 10. 验证与边界

Windows与WSL base定向pytest/Ruff/mypy；WSL当前DrvFS只证明开发合同。不得运行真实网络或修改正式
02983/01065 plan/journal。实现、全新独立初验、主Agent终验通过后，另立正式v3 migration任务。

本包通过只解锁 P1 total-return输入bar capability；不证明真实HK公司行动、01065、HK60、ext4或M1 Gate。

## 11. R2：读取窗口目录锚与异常图脱敏（2026-08-09）

R1 独立初验报告：`M1_HK_CA_P1_PRE_B_HK行情AvailabilityReceiptV3独立初验报告.md`。结论 FAIL；既有
Windows/WSL 定向测试绿色不覆盖以下两个阻断。

### 11.1 失败闭环

1. **验证窗口 root ABA 被接受。** 最小复现在线程内让 loader 完成首次 journal root `lstat` 后，将原目录
   rename、把一份完整 copy 放回同一路径，读取结束前再恢复原目录；首尾 path identity 相同，但窗口中实际
   读取过另一物理目录，现实现仍签发 capability。根因是只比较首尾路径身份，没有用贯穿完整读取窗口的目录
   handle/dir-fd 锚定所有读取。
2. **hostile reader 的 marker 沿异常图泄露。** `pl.read_parquet` 抛含 TOKEN/path marker 的
   `RuntimeError` 时，顶层虽是 `HK_BAR_VERIFY_FAILED`，但 `__context__` 仍形成
   `HK_BAR_VERIFY_FAILED → REFERENCE_INVALID → RuntimeError(marker)`。根因是在 active `except` 中重抛或
   包装稳定错误，没有在离开异常处理上下文后统一重建公开异常。

被破坏的不变量分别是 §6.6 的全窗口 physical-root freshness，以及 §7 的公开异常
`cause/context is None`、完整 traceback/异常图无敏感 marker。

### 11.2 最小返工规则

- formal loader/verifier 进入任何 retained/clean 读取前，必须为 journal、seed、raw-store 和 clean 四类权威
  root 建立平台安全的目录锚，并保持到全部 source rebuild、schema/identity 比对和 capability 签发完成：
  POSIX 使用 `O_DIRECTORY|O_NOFOLLOW` dir-fd 及相对 open/stat；Windows 使用禁止 share-delete 的目录 handle
  与 handle file identity。root rename/replacement、handle/fd 漂移或任一读取逃离锚定目录均 fail closed。
- raw-store/clean 下实际读取的 exact plan partitions 必须相对于已锚 root 打开；不得仅在窗口首尾重新
  `lstat(path)`。现有 exact-key、禁止扫描和 symlink/reparse 规则保持。
- development fixture 也走相同锚定读取核心；Windows 与 POSIX 实现可按平台分支，但不能弱化任一平台的
  root identity 语义。
- public loader/verifier、HKEX retained verifier 及其调用链只在内部记录稳定错误码；捕获任意已知/未知异常
  后必须先离开 active `except`，再以 `raise ... from None` 构造唯一公开稳定错误。最终公开异常对象的
  `__cause__`、`__context__` 均为 `None`，递归遍历异常图与格式化 traceback 不含原 marker。
- 不改变 v3 schema、availability 时间语义、四文件发布合同或 legacy v1/v2 行为；不触碰正式 journal/data。

### 11.3 新增测试与通过条件

- 在一次 public load 和一次 public verify 的完整窗口内分别执行 `original → copied replacement → original`
  ABA；替换发生在首次 root preflight 后、至少一个 retained/clean read 前，必须稳定拒绝且不签 capability。
- 对 journal、seed、raw-store、clean 四类 root 分别覆盖 rename/replacement；POSIX 验证 dir-fd/open-at，Windows
  验证持有 handle 时 rename/replacement失败或调用 fail closed。symlink/reparse既有反例继续通过。
- `pl.read_parquet`、JSON/raw reader、HKEX verifier 分别抛 ValueError 与 RuntimeError marker；load/verify 两个
  public 边界均只返回冻结稳定码，cause/context 为 None，递归异常图和 traceback 无 marker。
- R1 全组、事务/no-clobber、whole-rehash、legacy 隔离全部回归绿色；Windows 与 WSL base/DrvFS 定向
  pytest/Ruff/mypy 通过。DrvFS 仍不是 ext4 Gate。
- R2 返工由实现上下文交付后，必须由未参与 R2 的全新独立上下文复验；PASS 后才进入主 Agent 终验。

## 12. R3：原始目录锚存活性闭包（2026-08-09）

R2 独立复验报告：`M1_HK_CA_P1_PRE_B_R2_目录锚与异常图脱敏独立复验报告.md`。R1 的窗口内 root
ABA 与异常图泄露已关闭，但 R2 仍 FAIL。

### 12.1 失败闭环

独立最小复现在所有 retained/clean 读取完成后、`_capability_attestation` 前强制调用 `anchors.close()`；
Windows 与 WSL 均继续签发 `VerifiedHkBarBundle`。根因是 `assert_namespace()` 在原 fd/handle 已被置空或关闭后，
退化为按 path 重开/重取 identity，只证明“当前路径又指向相同对象”，没有证明贯穿读取窗口的**原始锚**仍
存活。这违反 §11.2“锚保持到 capability 签发完成，handle/fd 漂移 fail closed”。

### 12.2 最小返工规则

- `_ReadAnchors` 必须持有不可替换的每个原始 root/后代/file handle 或 fd 记录及创建时 identity；显式
  `close()` 后进入 terminal closed 状态，任何 `assert_namespace`、read、stat 或 capability attestation 都稳定
  拒绝，禁止重开路径作为原锚替代品。
- 每次 namespace assertion 先证明整组预期 handle/fd exact set仍存在且未标记关闭，再对**原 descriptor/handle**
  执行 `fstat`/Windows handle identity；descriptor 已被外部关闭、复用、缺失、identity 漂移或 API 失败均
  fail closed。之后才允许比较当前 path namespace，不能反转顺序。
- capability token/type 的唯一签发点必须在最后一次 live-anchor assertion 之后、`finally: anchors.close()` 之前；
  close 失败也不得让已构造 capability 逃逸。load 与 public verify 的 fresh rebuild均遵循同一顺序。
- 不改变四 root/后代 anchored read、v3 schema、availability、四文件发布、legacy 或异常稳定码。

### 12.3 新增测试与通过条件

- load 与 verify 分别在“全部读取后、签发前”关闭 journal/seed/raw-store/clean 每个单锚及整组 anchors；所有
  组合稳定拒绝、零 capability。
- 除正常 `anchors.close()`，还要覆盖 POSIX 外部 `os.close(fd)`、Windows 外部 `CloseHandle` 或等价 invalid
  handle，以及 descriptor number/handle 被复用到另一对象；live assertion 必须拒绝。
- 补后代目录和单文件 handle 在最后签发断言前被关闭/替换；禁止退化成普通 path read。
- R2 ABA、异常图、whole-rehash、legacy/no-clobber全组与双平台 pytest/Ruff/mypy继续通过。DrvFS仍非ext4。
- R3 返工后由未参与 R3 的全新独立上下文复验；PASS 后才进入主 Agent 终验。

## 13. R4：descriptor open-instance continuity（2026-08-09）

R3 独立复验报告：`M1_HK_CA_P1_PRE_B_R3_原始目录锚存活性闭包独立复验报告.md`。显式close、不同对象
descriptor复用、后代/file close与close-failure已关闭，但R3仍FAIL。

### 13.1 失败闭环

在签发前外部关闭原 raw-root fd/handle，立即对**同一物理目录**重开并复用同一整数编号；Windows
load/verify分别复现 `944→944`、`1236→1236`，WSL load/verify均`8→8`，四条路径继续签发capability。
根因是R3 `assert_live`只比较“当前编号指向对象”的inode/file-id；same-file reopen恰好得到相同编号与物理
identity，却已是新的kernel open instance。编号、path identity与`fstat`都不足以证明创建时open instance连续存活。

### 13.2 最小返工规则

- 每个root、后代目录与文件锚在创建时必须保留原descriptor/handle及一个不暴露给普通读取路径的private
  duplicate，两者必须由同一次duplicate primitive产生。签发前每次live assertion除identity外，还必须证明当前
  原descriptor与private duplicate仍属于同一kernel open instance/open file description。
- POSIX/Linux使用`dup`/`F_DUPFD_CLOEXEC`建立private duplicate，并通过共享open-file-description状态证明连续性：
  在不改变文件内容/offset的前提下暂时切换安全的file status flag（优先`O_NONBLOCK`），必须在duplicate可见且
  精确恢复；任何`fcntl`不支持、flag不同步、restore失败均fail closed。禁止只比较两个`fstat`。
- Windows使用`DuplicateHandle`建立private duplicate，并通过`CompareObjectHandles`或等价内核对象比较证明两者
  是同一open instance；API不可用、handle无效、返回false均fail closed。禁止用同file-id替代open-instance比较。
- 正常close必须精确关闭原件与所有private duplicates；部分close失败仍不得返回capability。duplicate不得出现在
  public capability、repr、异常或receipt中。
- 不改变R2 anchored read、R3 terminal/live顺序、v3业务语义、四文件/legacy/异常码。若目标平台无法提供可靠
  open-instance proof，按unsupported fail closed，不得降级。

### 13.3 新增测试与通过条件

- load/verify双边界，对root、后代目录、file三层分别执行close→same object reopen→same integer number；Windows与
  WSL均必须拒绝。保留different-object reuse对照。
- POSIX独立证明replacement descriptor与private dup不共享status flag；原descriptor与dup共享且restore后flag与
  内容/offset不漂移。Windows独立证明reopen same-file handle与private duplicate的`CompareObjectHandles=false`。
- 外部关闭private duplicate并以same/different object复用其编号同样拒绝；正常路径与finally cleanup无fd/handle泄漏。
- R1–R3 ABA、异常图、close/close-failure、whole-rehash、legacy/no-clobber与双平台pytest/Ruff/mypy继续通过。
- R4由原实现上下文返工，再由未参与R4的全新独立上下文复验；PASS后才进入主Agent终验。
