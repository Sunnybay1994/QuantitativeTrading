# M3 G7D-F0 R1：正式 A 股八表 MarketFacts 任务单

日期：2026-08-09  
状态：**R4 benchmark 510300 SSOT 实现、全新独立复验与主 Agent 最终验收 PASS；恢复 G7E 设计冻结**  
性质：formal 工程合同；不发布 stage/receipt，不等于真实全 work、Linux/ext4 或 M3 Gate

## 1. 目标、顺序与唯一职责

G7D-F0 是 G7B 与正式 A 股账户回测之间唯一的市场事实入口。它必须把 fresh G1 release 的八张表与
fresh `VerifiedBacktestPlanArtifact` 的窗口绑定为 process-local、不可序列化的
`VerifiedAShareMarketFacts`。本包只读取、验证和签发内存 capability：不写 artifact、不建 receipt、不运行
账户、不实现公司行动 entitlement、不联网。

冻结顺序为：

```text
G7P0 -> G7A -> G7B -> G7D-F0 -> G7C -> G7D remaining -> G7E -> G7F
```

G7C 不得另建三表/五表 corporate-action facts capability；否则会复制 release/window/digest/freshness SSOT。
现有 `VerifiedDevelopmentExampleAShareMarketFacts` 与 development builder 继续独立，不能 cast、复制字段或
重签为 formal。

## 2. Formal 类型与 Fresh Context

在 `a_share_execution.py` 定义 `@final`、不可 pickle、只能由本模块私有 construction seal 建立的 exact
`VerifiedAShareMarketFacts`。公开只读字段仅为 identity 与八个 DataFrame；禁止公开裸八表 formal 构造器，
禁止 `release_kind/example_id/formal_gate_eligible`。

建议新增 portable 值对象：

```python
@dataclass(frozen=True)
class FormalAShareMarketFactsIdentityV1:
    schema_version: Literal["m3-formal-a-share-market-facts-v1"]
    g1_release_id: str
    g1_release_manifest_sha256: str
    backtest_plan_manifest_sha256: str
    backtest_plan_receipt_sha256: str
    window_sha256: str
    artifact_digests: tuple[ArtifactDigest, ...]
    input_market_facts_sha256: str

@dataclass(frozen=True)
class AShareMarketFactsFreshVerificationContext:
    target: VerifiedTargetArtifact
    folds: VerifiedFoldPlanArtifact
    experiment: VerifiedExperimentIdentity
    config: LoadedM3Config
    plan_fresh_context: BacktestPlanFreshVerificationContext
    plan_receipt_path: Path
```

context 的 `__post_init__` 必须 exact type/path；不得 pickle，不进入 portable identity。`artifact_roots` 继续作为
独立参数并使用既有公共 root registry。

唯一 public formal loader：

```python
def load_verified_a_share_market_facts(
    *,
    release: VerifiedG1Release,
    plan: VerifiedBacktestPlanArtifact,
    fresh_context: AShareMarketFactsFreshVerificationContext,
    artifact_roots: Mapping[str, Path],
) -> VerifiedAShareMarketFacts: ...
```

## 3. Fresh 顺序与根实体闭包

入口只做 exact type/path 与 release/plan root实体快照，然后：

1. 精确一次调用 public `verify_g1_release(release=release.release)`；返回值逐字段 exact 等于 outer release。
2. 精确一次调用 public `verify_backtest_plan_artifact`，传 fresh G1、outer plan、context 完整链、receipt 与 roots；
   返回 root、scheduled targets、manifest、manifest hash、receipt hash 必须逐字段 exact。
3. 只有 G7B fresh 成功后才可读取任何八表，保证 G7A/G7B target 构造永远看不到公司行动事实。
4. 从同一已锚定 G1 root stable-read 八表，重建 schema、物理顺序、文件 bytes digest、窗口域和跨表闭包。
5. 签发前重新核对 release root、plan root、八文件实体与内容；same-bytes copy、路径 alias、symlink/reparse、
   调用窗口 whole-root/file replacement 全部拒绝。

本包不得再次直接调用 G7A verifier；G7B 已递归完成该闭包。

## 4. 八表 selector、Schema 与物理顺序

路径只能从 fresh G1 `artifact_paths` 与 manifest files 推导，caller 不得传裸路径：

| 表 | manifest identity `key_columns` | 权威物理顺序 |
|---|---|
| instrument | `(symbol)` | `(symbol)` |
| trade_calendar | `(market,date)` | `(market,date)` |
| bar | `(symbol,trade_date,source)` | `(symbol,trade_date,source)` |
| price_limit | `(symbol,trade_date,source)` | `(symbol,trade_date,source)` |
| suspension | `(symbol,trade_date,source)` | `(symbol,trade_date,source)` |
| corporate_action_ledger | `(event_id)` | `(symbol,ex_date,event_id)` |
| corporate_action_reconciliation | `(symbol,previous_factor_date,effective_date)` | `(symbol,previous_factor_date,effective_date)` |
| benchmark | `(benchmark,trade_date,source)` | `(benchmark,trade_date,source)` |

只接受当前 formal `G1ManifestV5` 与权威 Pandera Schema。每个文件须 stable-read raw bytes 两次，size/hash exact
等于 manifest，再用 `BytesIO` 解析。先分别证明 manifest selector/schema/identity `key_columns` exact，以及源帧
严格遵守上表独立的权威物理顺序；再验证 identity key 唯一并用 preserve-order filter 切片。ledger 尤其不得把
`event_id` identity key误当物理排序键。禁止 `.sort()` 修复后接受。

portable identity 的 `artifact_digests` 按 `(root_alias,relative_path)` 排序，内容含 table name、row count 与
content digest；不得加入绝对路径、inode、PID、时间戳。物理 root/file identity 只保存在 process-local 私有状态。

## 5. 精确窗口域

令 `E = plan.window.execution_dates`，`S = scheduled_targets.symbol` 并集。潜在持仓域 `D` 定义为：

- 所有 scheduled `(symbol,execution_date)`；以及
- 对每个曾出现正 `Decimal` weight 的 symbol，从首次正权重 execution 到 terminal 的全部 `E` 日期。

约束：

- instrument exact `S`，且每项为 `STOCK/CNY/SH|SZ`；每个 `D` key 必须落在该证券
  `[list_date,delist_date]` 生命周期内。退市后仍潜在持仓立即 fail closed，不用旧 mark 或 0 价续跑。
- bars/limits/suspensions 选择 `D`。每个 `D` key 必须满足“一条 bar XOR 一条 FULL_DAY suspension”。
  `PARTIAL` 必须有 bar。
- 每个非 FULL_DAY key 必须恰一条 limit，`has_price_limit=true` 且上下限均非空；FULL_DAY 可有 0/1 条 limit，
  但永不开放交易。
- benchmark selector 必须从已验真的 `fresh_context.config.section("data")["benchmark"]` 派生，当前 exact
  `510300.SH`，并要求 `510300.SH x E` 每日一行；禁止旧 `H00300.CSI` 或 caller selector。
- ledger 选择 `S` 且 `(record_date in E OR ex_date in E)`。允许 record 在 E、ex 在 terminal 后的事件留下待处理
  应收，但不能暴露给 target 构造。
- calendar 只取 SH，inclusive 窗口覆盖 first execution/terminal 与所有已选 record/ex；物理 date 严格递增，
  `E` 与所有 selected record/ex 都必须是 SH open session。pay/list 只映射到 `<= terminal` 的首个 SH session，
  超出则保留应收。

## 6. FULL_DAY 公司行动与 reconciliation 双向闭包

reconciliation 选择 `S` 且 `effective_date in E`，保留 `NO_EVENT` 行供审计，但消费者不得拿它调整 mark。
对每个窗内 ledger `(symbol,ex_date)` 事件集合：

- 有 bar 时不得同时存在 FULL_DAY。
- 无 bar 时必须恰一条 FULL_DAY 与恰一条 reconciliation。
- reconciliation `event_count > 0`；`event_ids_json` 必须 canonical、sorted、unique；
  `event_ids_sha256 = hash(["m3-g1-corporate-action-event-set-v1", *event_ids])`；IDs exact 等于 ledger 同
  symbol/ex_date 的 event_id 集合。
- status 必须为允许的 `MATCHED_*`，`actual_factor_ratio > 0`。
- 反向拒绝 event_count>0 但 ledger 集合不 exact 的 reconciliation，以及少、多、换 ID、重复、错 hash、
  `NO_EVENT` 冒充 transition。

同时冻结给 G7E 的 mark 规则：FULL_DAY 普通日沿用 previous mark；只有上述 exact matching CA transition 才用
`previous_mark / actual_factor_ratio`。PARTIAL 无 bar、无合法 open mark、退市后潜在持仓均 fail closed；禁止
forward-fill、0 价或从 entitlement 反推 mark。

## 7. Formal/development 隔离、错误与零副作用

- exact formal/dev type 混配必须在任何八表读取前失败。
- capability 只能由 loader 在最后一步签发，seal/token 不公开、不序列化、不进入 repr/equality。
- 稳定 public 错误唯一为 `M3_A_SHARE_MARKET_FACTS_INVALID`。
- G1/G7B、Polars/JSON/IO、ValueError/RuntimeError 等 hostile 异常必须离开 active except 后翻译；
  `__cause__`/`__context__` 均为 `None`，repr/traceback 不泄露 path、raw、TOKEN、SQL。
- 禁止 label/account/network callback；禁止读取 data/legacy、正式交易账户或任何凭据；禁止写文件、mkdir、日志、
  receipt 或 artifact。
- package cold import 不加载 Qlib、LightGBM、MLflow。

## 8. 必测反例

1. formal/dev release、plan、facts 四类混配；伪 exact fresh 返回。
2. G1/G7B direct call 各精确一次；G7B fresh 前访问 CA frame 的 sentinel 必须为零调用。
3. 八 selector 逐一错 path/schema/key/少/多/alias；八表 reverse 与 duplicate。
4. weekend 冒充 SH session；signal/execution/window identity 漂移。
5. `D` 域上市前、退市中途、正权重后无计划行、停牌持仓。
6. bar+FULL_DAY、PARTIAL 无 bar、non-full limit 缺失/重复/单侧为空。
7. FULL_DAY ledger event 少/多/换 ID/错 hash/合法重签、`NO_EVENT` reconciliation、extra reconciliation。
8. benchmark 少日、多日、错 benchmark、物理乱序。
9. copied release/plan root + 原 receipt；same-bytes file/root replacement；symlink/junction/reparse。
10. hostile upstream/Polars/IO 的递归异常图；公开异常码和空 cause/context。
11. label/account/network/mkdir/write/log 入口零调用；cold import无重研究依赖。

## 9. 白名单与停止条件

实现白名单：

- `src/quant/backtest/a_share_execution.py`
- `src/quant/backtest/__init__.py`（仅必要安全导出）
- `tests/unit/test_m3_formal_a_share_market_facts.py`（新增）
- 本任务状态与唯一交付报告

只有确需把独立 formal identity/type 放入研究 contracts 时，主 Agent 重新批准后才可追加
`src/quant/research/m3/contracts.py` 与安全导出；不得自行扩张。禁止修改 G1/G7A/G7B/G7C/G7E、development
测试、config、正式 artifacts/journal。

停止并回主 Agent 重冻：

- G7B 独立复验或主验未 PASS；
- 发现当前 G1 manifest/Schema 无法表达上述 exact closure；
- 需要排序修复、forward-fill、账户状态或 entitlement 才能补事实；
- 需要公开 generic signer、裸 formal DataFrame 构造器、写 sidecar/receipt；
- 要改变退市、停牌、公司行动 factor 或 benchmark 业务语义。

## 10. 验证与通过条件

Windows 原生与 WSL Miniforge base 均定向执行：formal facts、G7B、development facts 与 G7E 邻接测试，另跑
白名单 Ruff、mypy、cold import、`git diff --check`。WSL `/mnt/f`/wslfs/DrvFS 只算兼容证据，不是 ext4 Gate。

只有“外部/独立实现自测 -> 未参与实现者独立初验 -> 主 Agent 最终验收”全部 PASS，才可把本任务标为通过并
解锁 G7C formal 返工。初验必须补至少一个实现测试未覆盖的未落盘 root/file replacement 或 FULL_DAY
whole-rehash 反例，不能只复述测试数量。

## 11. R1 失败与 R2 冻结闭环（2026-08-09）

现象：R1 将 `_FORMAL_FACTS_SEAL` 放在模块全局，同时公开了接收八个裸 DataFrame、identity、seal 与任意
provenance 的 `VerifiedAShareMarketFacts(...)` 构造器。caller 可 import 该 seal 后直接 mint exact formal type；
也可 `object.__new__` 新实例、复制 slots 后漂移 identity。下游若只做 exact type/属性读取，会绕过 G1/G7B fresh
来源证明。

根因：underscore 命名不是 capability 边界；R1 只在构造瞬间比较一个可导入 sentinel，既没有内容绑定
attestation，也没有对“由唯一 loader 签发的实例”做持续证明。

R2 必须保持八表选择、窗口与 root/file 闭包语义不变，仅替换 formal capability 签发边界：

1. 模块运行时不得存在 `_FORMAL_FACTS_SEAL`、任何 32-byte key、generic signer/mint/factory 名称或可调用对象。
2. 用单一模块初始化 closure 同时产生 public exact type与public loader；随机 process-local HMAC key、mint、
   verify、issued-instance registry只存在 closure 内。初始化 factory 随后删除，不留 module attribute。
3. public constructor 必须稳定拒绝。loader 在所有 fresh/root/file/数学校验完成后用 closure 内部原语创建实例；
   formal 类型 slots 包含不可见 attestation/nonce并允许 weak reference。issued registry使用实例身份而非caller字段；
   未由 loader 加入 registry 的 `object.__new__`/constructor/clone恒失败。
4. attestation payload exact 绑定 formal identity、八帧各自 table/schema/物理有序全内容 hash、portable
   whole-hash与process-local provenance root/file identity。每个 public property、`identity`、repr及后续formal
   consumer在返回任何数据前都先调用同一closure verifier；verifier fresh重算payload并constant-time验证。
5. `object.__setattr__` 漂移 identity、任一frame、provenance、nonce或attestation后，下一次任一public消费必须
   fail closed。合法 capability 的 property 仍返回clone，不能泄露内部可变frame。
6. 异常继续统一为 `M3_A_SHARE_MARKET_FACTS_INVALID` 且cause/context None；attestation、key、nonce、registry、
   root provenance不得进入repr/equality/portable identity/pickle。

R2新增测试至少覆盖：直接import旧seal失败；模块无key/mint/factory surface；public constructor拒绝；
`object.__new__`空对象、完整slots clone、clone后identity/frame/provenance drift；合法实例原地各slot drift；伪
portable whole-hash与八frame完整重签；每个public property/repr在返回前拒绝；reload旧capability拒绝；合法
loader实例正常且pickle拒绝。R1已有Windows/WSL、same-bytes replacement、FULL_DAY/窗口/物理顺序回归全部保留。

## 12. R2 失败与 R3 冻结闭环（2026-08-09）

R2 已关闭模块级 seal、普通构造、未登记 clone、字段漂移与属性消费前校验，但 public
`load_verified_a_share_market_facts.__closure__` 直接保留了可调用
`mint(identity, selected, provenance)`。caller 读取 closure cell 后可用八裸frame和任意provenance签发已登记、
attestation正确的 exact formal对象，仍未经过 G1/G7B fresh。另一个独立失败是实现测试在当前pytest进程内
`reload`模块后没有完整恢复模块及消费者的类身份，导致后续development邻接节点被测试顺序污染。

R3最小返工：

1. public loader、formal class methods/properties及其可达closure中，不得出现任何接受
   `(identity, frames/selected, provenance)` 或其他prepared facts的callable。
2. public loader可达的唯一签发callable必须只接受与public loader相同的完整参数：release、plan、fresh context、
   artifact roots；每次调用都先执行 `_prepare_verified_a_share_market_facts` 的G1/G7B/八表完整fresh闭包。
   即使caller枚举并调用所有callable closure cells，也只能得到与public loader等价的fresh行为。
3. raw instance allocation/slot赋值只能作为上述fresh callable一次调用栈内的局部步骤，不得返回、缓存、放入
   module attribute或任何导出/可达closure cell。issued registry只能在完整prepare成功后登记。
4. 保留R2内容HMAC、whole-hash、issued identity与property前重验；R3不降低这些合同。任意直接调用准备函数本身
   只返回普通值，不能让对象进入issued registry。
5. reload旧capability反例必须在fresh subprocess或可证明完整恢复的隔离模块上下文中执行；不得污染同进程后续
   formal/development类型身份。新增固定顺序 `reload-test -> development facts/G7B/G7E` 回归必须全绿。

R3必须新增未落盘探针：递归枚举public loader/class properties/repr的一层及传递callable closure cells，断言不存在
prepared-facts mint签名；对发现的每个callable以伪raw facts尝试时均不能签发，且G1/G7B verifier调用计数符合
public fresh合同。保留R1/R2所有双平台回归，随后由全新独立上下文复验。

## 13. R3 主验后 benchmark SSOT 冲突与 R4 冻结闭环（2026-08-09）

G7E 设计审计发现：项目权威 [`../M3实施与Agent交接.md`](../M3实施与Agent交接.md) 与
`configs/research/m3_qlib_example.toml` 已明确 M3 v1 正式 benchmark 只能是用户批准的可交易 ETF
`510300.SH`，禁止混用旧 `H00300.CSI`。但本任务 R1 第 5 节、当前生产 selector 与 formal fixture 均仍硬编码
`H00300.CSI`。这会使同一 `input_market_facts_sha256` 无法同时满足 G7E facts 与后续 G7F benchmark metric/receipt，
G7E 禁止通过改名、映射或复制 frame 调和。

R4 只关闭 benchmark selector SSOT，不改变 R3 capability、八表、窗口或 publication-free 边界：

1. F0 必须在 G1 与 G7B fresh 返回且逐字段 exact 后，从
   `fresh_context.config.section("data")["benchmark"]` 读取唯一 selector；字段必须 exact `str` 且当前 exact
   `510300.SH`。禁止新参数、caller path/selector、模块平行常量或读取裸 TOML。
2. selected benchmark 必须 exact `510300.SH x execution_dates` 每日一行，物理顺序、Schema、source与原八表
   合同不变；旧 `H00300.CSI`、少日、多日、重复或乱序继续 fail closed。
3. formal identity、八表 portable digest、whole hash与process-local attestation必须自然绑定更正后的 selected
   frame及原始 G1 artifact bytes；不得复用旧 `H00300.CSI` capability/token/hash，也不得修改 G1 release。
4. 修改限于 `a_share_execution.py` 的 formal F0 selector，以及同文件 F1 date guard 中遗留的旧 benchmark
   常量：F1 只验证已验真 exact F0 capability 的 benchmark frame 对请求 date 恰有一行，不再重复判断代码；
   benchmark selector 的唯一权威仍是 F0 + fresh config。除此之外禁止改变 F1/F2 生产语义。
   同一 formal F0 测试fixture/断言和本任务状态可改；`backtest/__init__.py` 若无需接口变化保持零修改。禁止改
   config、G1/G7B/G7C、development tests、正式 artifact/journal。
5. 新增反例至少覆盖：合法 `510300.SH` 正向；只有旧 `H00300.CSI` 拒绝；同一表含旧/新代码时只选已验真
   config selector且identity绑定；config benchmark whole-rehash/低层漂移由G7B fresh先拒；旧R3 capability在
   reload/新代码边界 fail closed；hostile config section异常仍统一脱敏。
6. Windows 与 WSL base 必须重跑 F0 formal 全文件，并回归 G7C、F1、F2 formal 邻接及 fixed-order/cold-import；
   Ruff/mypy/diff均通过。WSL `/mnt/f` 仍只算DrvFS兼容。

F1 date guard 的安全前提是：public F1 已在任何 frame property 前拒绝非 exact F0 capability，而 exact capability
的每次 property 访问会重验R3来源与八表内容；因此删除 consumer 内旧代码常量不是接受裸frame。新增回归必须
证明合法 `510300.SH` F0 可被F1/F2消费，fake/development仍在frame访问前拒绝，旧 `H00300.CSI` 无法由F0签发。

R4 交付报告固定为 `M3_G7D_F0_R4_benchmark510300SSOT返工交付报告.md`，全新独立复验报告固定为
`M3_G7D_F0_R4_benchmark510300SSOT独立复验报告.md`。只有实现、自测、全新独立复验与主 Agent 最终验收均
PASS 后，才恢复 G7E 任务冻结；此前 G7E formal 保持暂停。
