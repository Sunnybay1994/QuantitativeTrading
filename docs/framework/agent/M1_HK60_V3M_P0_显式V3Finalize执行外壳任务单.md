# M1-HK60-V3M-P0：显式 v3 finalize 执行外壳任务单

日期：2026-08-09  
状态：R3 主 Agent 最终验收通过（fixture-only 工程合同；正式 migration/HK60/M1 Gate 仍开放）  
性质：fixture-only 工程前置；禁止创建/修改正式 HK60 plan、journal、raw 或 clean

## 1. 背景与目标

PRE-B R4 已通过主验，`finalize_hk_history(..., hkex_retained_bundle=...)` 可生成 v3 finalize、availability 与
retained raw/metadata 四文件，`load_verified_hk_bar_bundle` 可 fresh 验真。但正式 CLI 目前只有
`--finalize --hkex-retained-raw`，只能走 legacy v2 raw-only 路径；没有显式 raw+canonical metadata 的 v3
入口，也不能在调用 finalize 前 fresh 构造 exact `VerifiedHKEXDailyQuotationRetainedBundle`。

本包只新增零网络、显式、不可与 legacy 混用的 v3 CLI/执行外壳，并用最小 fixture 冻结失败语义、路径隔离、
no-clobber 与 partial-root 边界。它不 materialize metadata，不猜 `source_observed_at`，不运行正式 migration。

## 2. 前置事实与硬阻断

- 02983 官方 raw bytes/parser evidence 可复用，但尚未证明一份 formal canonical retained metadata 与可信
  aware-UTC `source_observed_at`。mtime、报告日期、当前时间和测试常量均不是来源证据。
- 01065 仍缺 licensed 2026-05-05 完整 issue、同版 File Specification、exact file-set/finality 与
  no-trade/suspended 语义 verifier。
- 因此本包测试只能使用确定 fixture；任何 production CLI 调用必须由用户显式提供已存在的 raw 和 canonical
  metadata 文件。代码不得生成、修补或推断 metadata。

## 3. CLI 合同

修改 `quant.data.backfill_hk_history`：

- 新增 `--finalize-v3` boolean；
- 新增 `--hkex-retained-metadata PATH`；
- v3 必须同时提供 `--hkex-retained-raw PATH` 与 `--hkex-retained-metadata PATH`；缺任一稳定
  `HK_HISTORY_PLAN_CONFLICT`；
- `--finalize-v3` 与 legacy `--finalize`、`--recover-existing-only`、`--confirm-uncertain-retry` 互斥；
- metadata 参数在非 v3 模式一律 conflict；legacy `--finalize --hkex-retained-raw` 行为和 v2 bytes不变；
- v3 路径禁止构造 `TushareConnector`、禁止网络；parser/config 不得触发 connector import-time side effect；
- raw/metadata 各自 read-once，任一 OSError、非普通文件、symlink/reparse、路径替换或 bytes 漂移均在
  `finalize_hk_history` 前稳定拒绝；不得用 `Path.read_bytes()` 的无锚 check-then-read 作为 formal v3入口；
- CLI fresh 调用 `verify_hkex_daily_quotation_retained(raw, metadata,
  source_url=SOURCE_URL, expected_raw_sha256=EXPECTED_RAW_SHA256)`；只把返回的 exact bundle传入
  `finalize_hk_history(..., hkex_retained_bundle=bundle)`，绝不同时传 raw-only参数；
- stdout 成功 JSON 必须显式包含 `finalize_schema_version="hk-history-finalize-v3"`、published rows 与
  retained bundle identity；不能只输出与 v2 不可区分的 payload；stderr 只输出稳定码。

若跨平台 anchored read 需要公共 helper，可在 `hk_history_backfill.py` 新增窄的
`load_verified_hkex_retained_bundle_for_finalize(...)`：它只做两个输入文件的 same-window anchored读取、调用现有
HKEX verifier并返回 exact bundle；不得修改 v3 schema、parser或 availability 业务语义。Windows使用既有项目
reparse/physical identity原语，POSIX使用 no-follow/open fd；返回前路径与打开对象必须仍一致。若无法复用安全
原语且需扩大到 `hkex_daily_quotations.py`，立即停止重冻。

## 4. 路径与运行隔离

- v3 CLI 不创建新的 plan；只消费 caller 显式 `--plan`。
- resolved journal、raw、clean 三个实际读写 root 必须 pairwise disjoint、互不为 ancestor/descendant、无
  symlink/reparse 或 physical alias；plan 文件不得位于任一可写 journal/raw/clean root 内。`data-root` 作为
  raw/clean 的共同配置父目录是既有合法布局，不得误拒绝，但 CLI 必须从它派生 exact `raw` 与
  `clean/bar_1d` 子角色后再做隔离检查。不得因默认路径把 fixture写进正式 root。
- 测试使用系统临时目录或独立 fixture root，不扫描 `data/`、`data/legacy/` 或正式 artifacts。
- 旧 `hk60_2026-07-10` plan/journal 永久只读；本包不得包含它们的路径、SHA 或复制字节作为正向 fixture。
- 正式未来 run 的路径/manifest合同另立 V3M-P1；本包不写 execution manifest。

## 5. no-clobber、partial 与 clean 边界

复用 PRE-B 已验收的 v3 四文件事务：同 bytes exact retry幂等、异 bytes/partial exact set fail closed、竞争
抢占不覆盖、不删除竞争文件。本包必须从公开 CLI 覆盖这些行为，但不得改变其实现来伪造全局原子性。

`CleanBarStore.upsert` 发生在四文件前，跨分区 clean发布不是全局 rollback：

- 进程内四文件写失败，只承诺清理本调用拥有的四文件；不能声称回滚 clean；
- clean同键异值必须在 preflight 停止；同键同值可幂等；
- 断电留下 partial四文件时，本 CLI稳定 fail closed，不原地删除/补写；未来正式执行应隔离整个新 run root；
- 不新增自动 quarantine/delete/move，因本包没有正式外部副作用授权。

## 6. 稳定失败语义

- 参数/模式冲突：`HK_HISTORY_PLAN_CONFLICT`；
- retained路径/读取/identity/metadata/raw/parser/fresh bundle失败：沿用窄且稳定的
  `HK_HISTORY_REFERENCE_INVALID` 或 HKEX public invalid映射；对外不得泄露 path/raw/metadata/TOKEN；
- plan/journal/availability/clean冲突继续沿用所属层既有码；
- 所有未知异常退出 active `except` 后重建公开错误，`__cause__`/`__context__` 均为 `None`；
- verify失败时 `finalize_hk_history` 调用数必须为0，connector/network调用数为0，journal/clean零新增。

## 7. 写入白名单

- `src/quant/data/backfill_hk_history.py`
- `src/quant/data/hk_history_backfill.py`：仅确需 anchored dual-file loader/preflight时最小修改
- `tests/unit/test_backfill_hk_history.py`
- `tests/unit/test_hk_history_backfill.py`：仅公共loader/partial/no-clobber直接回归
- 本任务单状态/R2追加、唯一实现交付报告、唯一独立复验报告、主验报告

禁止修改 `hkex_daily_quotations.py`、schemas/domain、connectors、storage、HK60/U0C/G1、正式 data/artifacts、
配置、依赖、research/backtest/execution。

## 8. 必测反例

1. v3 raw-only、metadata-only、两者皆缺；metadata用于legacy/normal/recover；v3与legacy/recover/retry混用；
2. raw/metadata未知/缺/重复字段、非canonical JSON、future/naive observed、source/date/record/hash/identity漂移；
3. legacy raw-only成功仍只走v2且不能生成v3 capability；legacy v1/v2 receipt传loader稳定unsupported；
4. raw/metadata symlink/reparse、same file、hardlink/physical alias、读取窗口replacement/返回时可观测内容漂移、
   open handle/fd漂移；真 ABA 边界以 §11 为准；
5. hostile read/HKEX verifier/finalize ValueError与RuntimeError：固定码、cause/context None、traceback/repr无marker；
6. v3 verify失败：finalize=0、connector=0、network=0、journal/clean零新增；
7. v3成功只传exact bundle，stdout明确v3与bundle id；调用参数逐项断言；
8. 四文件第二/第三/第四写失败、竞争抢占、partial预存、异bytes exact retry、rollback失败；不删除竞争/未知；
9. clean同键异值前置拒绝；同键同值可重放；四文件失败报告诚实保留clean非全局rollback边界；
10. Windows与WSL base对应定向；冷启动import零网络。DrvFS不等于ext4 Gate。

独立初验必须新增实现者未用的 dual-file TOCTOU/返回时可观测内容漂移或 hostile exception graph 对抗；真
ABA 边界以 §11 为准；生产/实现测试只读。

## 9. 验证

Windows `D:\Miniforge3\python.exe` 与 WSL Miniforge base `/mnt/f`：

- 定向 pytest 两个白名单测试；
- Ruff 白名单生产/测试；
- mypy 白名单生产；
- `git diff --check` 与白名单审查。

不得运行真实 plan/recovery/network/finalize，不读取正式 raw/journal/clean，不以 fixture结果关闭M1/HK60。

## 10. 停止条件与通过条件

以下任一情况立即停止：需要生成/猜 metadata或 observed_at；需要读取/写正式 plan/journal/data；需要实现01065
parser但 licensed issue/spec不齐；需要修改 HKEX schema/parser、clean schema/storage或 legacy receipt；需要承诺
clean+四文件全局rollback；需要创建正式 migration manifest/root。

实现自测、全新独立初验和主 Agent验收均PASS后，只解锁：

1. 02983 provenance readiness（取得可信 observed_at并write-once materialize canonical metadata）；
2. 01065 licensed source-freeze/verifier；
3. 二者通过后另立 formal V3M-P1 新plan/recovery/余批网络/v3 finalize/双Route Gate。

本包通过仍不代表正式 migration、02983/01065、HK60、HK复权、ext4或M1 Gate通过。

## 11. R2：held open-instance 内容稳定性返工（2026-08-09）

### 11.1 R1 失败闭环

现象：独立初验在 `verify_hkex_daily_quotation_retained` 执行期间，通过原路径对 raw 或 metadata 普通文件做
同 inode/file-id 的原地改写，loader 仍返回 verified bundle。Windows 的 raw drift、metadata drift、raw ABA、
metadata ABA 四例和 WSL/wslfs 代表用例均逃逸。

根因：R1 在 verifier 后只重验目录 namespace、file physical identity 与 original/private descriptor/handle 的
open-instance continuity，没有从仍持有的同一 file open instance 复核内容。原地写入不改变 inode/file-id；
独立报告还把“verifier 返回前已恢复原 bytes 的真 ABA”列为阻断，但 §11 冻结时进一步做了最小 Windows
held-handle 实证：复读 SHA/length 与初值相同、offset 可精确恢复、file identity/open instance 也未改变，观测集合
没有区分信息。要求只靠这些观测拒绝真 ABA 是不可满足合同，不能让实现者用 mtime、path reopen 或伪锁填洞。

被破坏规则：§3 已冻结 raw/metadata bytes 漂移必须在 `finalize_hk_history` 前拒绝。same-window anchored read
必须同时证明对象身份和**返回时内容**与传给 verifier 的 bytes 相同，不能只证明路径仍指向同一物理文件。
下游只消费由 initial cached bytes 生成的 exact verified bundle；若临时改写在 verifier 返回前已恢复为完全相同
bytes，则既未改变 verifier 输入，也未改变返回时 retained 内容或 finalize 输入。本包把该真 ABA 明确列为当前
无外部事件日志/排他写约束下的不可观测信任边界，不再作为 R2 失败条件。

### 11.2 最小实现

只修改 R1 原白名单 `hk_history_backfill.py` 与对应两个测试文件；CLI 仅在确有测试适配需要时改动，不改
HKEX parser/schema、finalize 业务、正式 plan/raw/journal/clean。

1. raw 与 metadata 首次从 anchored file open instance 读取时，分别冻结 exact payload length 与 SHA-256；
2. verifier 返回后、result 逃逸前，先证明 directory/file original+private duplicate 全部仍 live 且为创建时同一
   open instance；随后必须从**同一个仍持有的 file descriptor/handle**把内容从 offset 0 复读到 EOF，比较
   length 与 SHA-256；不得通过 path reopen、`Path.read_bytes()`、新 fd/handle 或仅 `stat(size)` 代替；
3. POSIX 复读必须保存并在 finally 精确恢复原 file offset，使用 held fd 或其同 OFD duplicate；Windows 使用 held
   handle 的等价 seek/read，并恢复原 file pointer。seek/read/restore 任一步失败均 fail closed；不得让内容校验
   改变后续 open-instance 探针状态；
4. 两个文件的 live/open-instance、内容摘要、namespace/path identity 必须都在 verifier 后完成。任何检查或 close
   失败覆盖待返回 result；public 只抛 `HK_HISTORY_REFERENCE_INVALID from None`，异常图与 traceback 不保留
   path/TOKEN/hostile marker；
5. 正常路径仍只进行一次 initial payload read 交给 HKEX verifier；新增的一次 held-instance re-read 只用于
   verifier 后内容稳定性证明，不再次调用 parser/verifier，不产生网络或写入；
6. 不将 payload、digest、descriptor/handle、offset 或私有 duplicate 放入 public capability、receipt、repr 或
   stdout。

R2 不新增写入世代、USN/inotify/fanotify、mtime/ctime 推断、文件锁或签名体系。若未来要求证明“窗口内从未发生
任何写入”，必须另立跨 Windows/Linux 的 retained-input exclusivity/event-journal 合同；不得把最终 bytes 相等
表述成已证明无瞬时写入。

若平台无法从 held handle/fd 无副作用复读并恢复 offset，停止并回主 Agent；不得降级为 path reopen 或仅
mtime/size/file-id 检查。

### 11.3 新增反例

必须新增 Windows 与 POSIX 均实际执行的：

1. verifier 内 raw 原地 drift，保留新 bytes；
2. verifier 内 metadata 原地 drift，保留新 bytes；
3. 对照：verifier 内 raw/metadata 原地改写后恢复 exact original bytes 的真 ABA，允许成功；必须证明 verifier
   输入、held re-read、返回 bundle raw/metadata 与最终路径 bytes 全部 exact 相同，且没有把此结果表述成
   “证明窗口内无写入”；
4. held file seek/read/offset-restore 分别抛 ValueError/RuntimeError：固定码、cause/context None、零 finalize；
5. normal success 前后 held descriptor/handle offset 完全一致；POSIX original/duplicate 仍为同 OFD，Windows
   `CompareObjectHandles` 仍为同 kernel object；
6. 保留 R1 original/private same-number reopen、path replacement、symlink/reparse/hardlink、hostile verifier、
   partial/no-clobber、legacy v2 与冷导入零网络全回归。

对抗不得只修改 cached Python bytes；必须真实原地写同一物理文件。测试清理必须兼容 Windows 与 POSIX，且先
断言产品拒绝，再执行 cleanup，避免清理异常遮蔽产品结果。

### 11.4 验收与状态

Windows 两个白名单测试文件定向 pytest、Ruff、mypy、cold-import no-network；WSL base 对应验证，并明确
`/mnt/f`/wslfs 非 ext4 Gate。`git diff --check` 与白名单检查必须通过。

R2 交付后必须由未参与 R2 实现的全新上下文独立复验，并至少补一个实现者未使用的 held-handle 内容变化或
offset/异常图反例。复验不得再次把已恢复 exact original bytes 的不可观测真 ABA 判为失败；应核对它未改变
任何语义输入/输出，并如实记录信任边界。R2 通过前不解锁 02983 provenance materialize、01065 source-freeze/verifier 或 formal
V3M-P1。

## 12. R3：dual-file quiescence 信任边界重冻（2026-08-09）

### 12.1 R2 失败闭环与不可满足表述

R2 已正确关闭每个单文件在其最终 held-instance 观测点之前的可观察内容漂移，但独立复验在 raw 最终复读完成
后、metadata 最终复读期间原地改写 raw 并保留，loader 仍返回基于旧 raw 的 exact bundle。该反例在 R2 原合同
“返回时两个路径内容均与 verifier 输入一致”的强表述下成立。

根因不是少一次 hash，而是无锁、无可信写入世代、无外部事件日志时，任意有限次双文件顺序读取都不存在共同
的最后观测瞬间；最后复核 A 后可写 A，最后复核 B 后可写 B。继续增加固定 sweep、交换顺序、看 mtime 或重新
打开 path 都不能把该事实变成跨进程不可变证明。

因此 R3 修正权威合同：本 loader 的 formal 前提是 raw 与 metadata 已由上游 write-once/no-clobber retained
materializer 发布，且调用者保证从 loader 开始到下游 finalize 消费 exact returned bundle 完成期间不存在任何
并发 writer。loader 证明的是：

1. verifier 输入是从两个 anchored open instance 首读得到的 exact bytes；
2. 每个文件在其最终 held-instance 观测点仍与首读 length/SHA 相同，descriptor/handle、namespace 与物理身份
   未漂移；
3. 唯一下游输入是 verifier 返回的 exact bundle，不再次按 path 读取；
4. loader 不独立证明两个外部路径在同一瞬间不可变，也不抵抗拥有 retained root 写权限且违反 quiescence 前提
   的并发 writer。

R2 独立反例必须作为公开信任边界保留在任务、实现报告、接口 docstring 与未来 V3M-P1 execution manifest
设计中，不能删除、改判成“已技术阻止”或以更多扫描掩盖。V3M-P0 仍是 fixture-only 外壳；正式 V3M-P1 在
materializer/manifest 未绑定 write-once 来源与执行期 quiescence 前不得运行。

### 12.2 R3 最小返工

只允许修改 R2 原白名单：

- 调整 loader/CLI docstring 与错误说明，精确描述上述保证和非保证；
- 删除任务、实现报告或测试名中任何“返回瞬间双路径一致”“跨进程不可篡改”的过强表述；
- 新增一个明确的 cross-file interleave 边界测试：证明违反 quiescence 时返回 bundle 仍是 verifier 首读的 exact
  内容且 finalize 只收到该 bundle，同时最终 path 可不同；测试名称与注释必须明确这是受信前提之外的诚实边界，
  不得把 accepted 写成安全成功或 Gate 通过；
- 保留 R2 单文件 persistent drift、held reread、offset、open-instance、hostile exception、legacy/no-clobber
  全部回归；不得删除失败反例来换取绿测；
- 不新增锁、轮询、固定多轮 sweep、mtime/ctime、watcher、签名或 caller 自报 boolean/capability。若未来需要
  抵抗违反 quiescence 的 writer，必须另立 retained materializer/OS policy/独立信任锚合同。

R3 独立复验应核对保证没有被重新写强，并运行单文件 observable drift 拒绝、真 ABA语义对照、cross-file
interleave 信任边界、异常脱敏和双平台定向回归。通过仅表示 fixture-only v3 CLI 在冻结信任模型下可进入主验；
不解锁缺失 provenance/licensed source，也不关闭 HK60/M1/ext4 Gate。

## 13. R3 实现交付状态（2026-08-09）

R3 已按 §12 完成最小返工并通过实现者双平台自测。R2 的 held-instance 复读、persistent drift 拒绝、offset
恢复、open-instance、异常脱敏及 legacy/no-clobber 回归全部保留；生产行为未增加锁、轮询、多轮 sweep、
mtime/ctime、watcher、签名或 caller boolean。

公共 loader 与 CLI 文档现已明确 write-once/no-clobber retained input 和 caller quiescence 是受信前提；loader
只证明每个文件各自在其最终 held-instance 观测点与首读一致，并返回由首读 bytes 验真的 exact cached bundle，
不证明两个外部路径在共同瞬间不可变。新增 cross-file interleave 测试保留了违反前提的 writer 反例，并与公开
CLI 下游只消费 returned bundle 的测试组成闭包；该反例的接受不表示并发 writer 已被阻止或任何 Gate 已通过。

Windows 两个白名单测试文件 `132 passed, 2 skipped`；WSL base `/mnt/f` 同组 `134 passed`；两平台 Ruff、
mypy、cold-import no-network 与 `git diff --check` 均通过。WSL 文件系统为 `wslfs`，不构成 ext4 Gate 证据。
详细证据见唯一 R3 交付报告；当前仍待未参与实现的全新上下文独立复验与主 Agent 最终验收。
