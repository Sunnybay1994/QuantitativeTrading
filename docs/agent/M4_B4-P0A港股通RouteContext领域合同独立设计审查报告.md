# M4 B4-P0A 港股通 RouteContext 领域合同独立设计审查报告

日期：2026-07-17
审查角色：全新外部代码只读设计审查 Agent（未参与实现；本会话仅写本报告）
模型：`cursor-grok-4.5-high`
状态：**设计审查不通过（存在 P0，须主 Agent 修订任务书后再下发实现）**
边界：未修改生产代码/测试/配置/数据；未运行 pytest；未读取 INDEX 写会话目标文件

## 1. 审查范围与总判

已完整阅读：`AGENTS.md`、`docs/agent/M4_B4港股通Route与日历接口前置裁定.md`、`docs/agent/M4_B4-P0A港股通RouteContext领域合同任务单.md`。

只读核对：`src/quant/domain/enums.py`、`src/quant/execution/contracts.py`、`src/quant/execution/ports.py`，以及 `domain/__init__.py`、`execution/__init__.py`；直接测试基线 `tests/unit/test_execution_contracts.py`、`tests/unit/test_execution_ports.py`；对照消费方 `src/quant/backtest/connect_execution.py` 中 `ConnectCalendarState` / quota 语义。

**代码现状（预期缺口）**：P0A 尚未落地。`ConnectRoute`、`VerifiedConnectMarketContext`、`ConnectMarketContextRepository` 均不存在；两份直接测试中亦无 `connect_market_context` 节点。本审查是对冻结任务书相对现行 SSOT/D0/D1/B2 契约的设计完备性审查，不是实现初验。

**总判**：显式 Route、领域枚举 SSOT、自证 context、窄 Protocol、P0A/P0B 拆分与文件白名单方向正确，且与前置裁定模型 A 一致。但任务书仍有 2 个 P0 会迫使实现者猜测不可逆 identity 算法或错误耦合 B2；另有若干 P1/P2。主 Agent 应先修订任务书，再启动实现 Agent。

## 2. 发现清单（现象—根因—规则—最小复现—通过条件）

### P0-1：context_id envelope 未冻结

- 现象：`hash_version`、`type` 名、payload 键集、builder 形参均为省略号，实现者可自造第二套哈希。
- 根因：任务书只写“strict canonical JSON envelope”，未钉死与 D0 同包算法。
- 应遵循：AGENTS 节2 SSOT；D0 既有 `_HASH_VERSION="execution-contract-hash-v1"` + `type` + `sort_keys` payload；身份一旦发布不可漂。
- 最小复现：实现者若自造 `connect-context-hash-v1` 或 `type="ConnectMarketContext"`，与后续 B4 引用的 `context_id` 永久分叉。
- 修订建议：复用 `execution-contract-hash-v1`；`type="VerifiedConnectMarketContext"`；payload 键精确列出全部经济字段（字段名以命名裁定为准）；builder 仅接受经济字段 kwargs，禁止传入 `context_id`；至少一组固定 fixture 到期望 hex 的锁定向量。

### P0-2：上游三 identity 与内嵌事实 / B2 关系未裁定

- 现象：`calendar_identity` / `quota_identity` / `source_identity` 是否等于 B2 `ConnectCalendarState.calendar_identity`、是否本地重算证明未写清。
- 根因：B2 使用另一套 `connect-rule-hash-v1`（含 `connect_open`、`source_version` 非 hex64），与 P0A 内嵌 bool 并存时易伪闭包。
- 应遵循：P0A 不得让 `execution.contracts` import `quant.backtest`；上游 id 语义须与 `VerifiedMarketSnapshot.calendar_identity` 同为不透明 provenance。
- 最小复现：错误实现 A 在 builder 内 import `build_connect_calendar_state` 本地校验；错误实现 B 要求 calendar_identity 等于 B2 digest 但内嵌开市 bool 与 B2 payload 不一致时静默通过或误拒。
- 修订建议：三者均为不透明 64-hex provenance；P0A 不本地还原/重算其 payload、不与 B2 identity 绑定；内嵌 bool 是 repository 声明的 route 级事实；禁止 P0A 依赖 `quant.backtest` / `quant.data`。

### P1-1：香港开市字段命名漂移

- 现象：任务书用 `hk_open`，已验收 B2 为 `hong_kong_open`。
- 根因：缩写未对齐 B2/裁定用语。
- 最小复现：P0B 替换 `ConnectCalendarState` 时漏映射，开市状态被误读。
- 修订建议：改为 `hong_kong_open`（推荐），或冻结唯一公开字段名并测锁定。

### P1-2：Protocol 返回闭包未冻

- 现象：未写返回对象 `route`/`session_date`/`as_of` 与入参关系。
- 根因：只写方法签名。
- 最小复现：fake 返回 SZ 而请求 SH；或 `context.as_of > 请求 as_of`；或 session_date 错日。
- 修订建议：返回 `route`/`session_date` 必须与入参全等；`context.as_of` 为事实可知时点且 `<= 请求 as_of`；identity 使用事实 `as_of`。

### P1-3：双 buy_quota_available 并存禁令不够硬

- 现象：route 级新字段与 `SymbolMarketState.buy_quota_available` 并存，未禁止误读旧字段为 route 额度。
- 最小复现：B4 原型误用无 route 的 symbol 级 quota 与 context 冲突时任选。
- 修订建议：P0B 完成前，新代码不得把 `SymbolMarketState.buy_quota_available` 解释为港股通 route 额度；route 额度 SSOT 仅为 `VerifiedConnectMarketContext.buy_quota_available`。

### P1-4：遗留字符串 route 集未点名

- 现象：schemas isin 与 B2 `_CONNECT_ROUTES` 仍在；任务未写禁止扩张/禁止新代码旁路复制。
- 修订建议：白名单外禁止改 B2/schemas；新代码只 import `ConnectRoute`；遗留集合保持原值至后续迁移。

### P2

- 可选冻结 `connect_route_mainland_market(route) -> Market`，或明确留白到 P0B。
- 写明故意省略 `connect_open`；派生属 B2/P0B 规则层。
- `domain` 包根导出与历史执行枚举不一致可接受；权威 import 路径为 `quant.domain.enums`。

## 3. 逐项证据

### 3.1 领域层级与 SSOT

| 条款 | 证据 | 结论 |
|---|---|---|
| ConnectRoute 落在 domain.enums | 现行 enums.py 无该枚举；route 字符串散落 schemas isin 与 B2 frozenset | 设计正确（补 SSOT）；实现前须处理 P1-4 |
| 值对象落在 execution.contracts | 与 VerifiedMarketSnapshot 同层；contracts 已依赖 domain.enums | 设计正确 |
| Protocol 落在 execution.ports | 现行仅 Market/Account 两 Protocol；无 IO | 设计正确 |
| 不把 route 接入 Intent/B2 | OrderIntent 无 route；B2 仍吃 ConnectCalendarState | 边界正确 |

### 3.2 Identity 闭包

| 条款 | 证据 | 结论 |
|---|---|---|
| 64-hex、拒 forged、拒自报 context_id | D0 已有 _require_hex64 / _reject_forged_identity / builder 模式 | 方向正确；缺 P0-1 envelope 冻结 |
| 顺序无关 canonical JSON | D0 _sha256_envelope 使用 sort_keys=True | 可复用；须点名复用 |
| 上游三 id + 内嵌事实 | VerifiedMarketSnapshot 同样持有不透明 calendar/source identity | 模式可对齐；须显式写不透明（P0-2） |
| setattr 篡改后 identity 拒绝 | D0 测试基线已有同类手法 | 必测条款充分 |

### 3.3 route / session / as_of / 额度

| 条款 | 证据 | 结论 |
|---|---|---|
| 显式 ConnectRoute，禁 AUTO/ANY | 对齐裁定模型 A；B2 仅两字符串 | 正确 |
| as_of timezone-aware UTC | D0 _require_utc_datetime | 正确 |
| session_date 拒 datetime 混用 | D0 _require_date 拒 datetime；B2 更松 | 正确；应走 D0 严格路径 |
| 三 bool 精确 bool | D0 _require_bool 拒 0/1 | 正确 |
| buy_quota 只限 BUY、不做决策 | B2 仅 BUY 路径读 quota | 语义对齐；缺 P1-3 |
| 无 mainland_market 字段 | 避免与 Market 漂移 | 正确 |
| hk_open 命名 | B2 为 hong_kong_open | P1-1 |

### 3.4 P0A/P0B 边界

| 条款 | 证据 | 结论 |
|---|---|---|
| 不改 Intent/State/B2/Config | 白名单未含对应文件 | 正确 |
| P0B 留白五项 | 覆盖 Intent、HK state、替代日历、snapshot 闭包、P3/B4 | 充分 |
| 裁定级反例未伪实现 | 缺 route 选边等属 B4/P0B | 正确未越界 |

### 3.5 文件白名单

生产五文件 + 两共享单测 + 唯一交付报告：必要且完整。共享测试文件依赖调度串行（当前 R1C 占 source 写锁）可接受；实现须用 `-k connect_market_context` 追加，禁止无关重构。禁改 B2/P3/config/Intent/repository 实现/数据/历史报告：与非破坏增量一致。

### 3.6 必测反例覆盖度

1. SH/SZ identity 不同、顺序稳定：充分；建议补“仅改 calendar_identity、bool 不变则 context_id 变”。
2. 裸 string/AUTO/错 enum、bool 0/1、naive/non-UTC、date/datetime：充分。
3. 上游 id 格式、同 id 异 payload、forged context_id：充分；须澄清“同 id 异 payload”是构造冲突还是两 context 复用同一 upstream id（建议两者都测）。
4. setattr 篡改：充分。
5. Protocol good/bad fake：充分；建议点名 runtime_checkable 只检方法存在。
6. import 隔离：充分；应显式加入不得 import quant.backtest。

## 4. 未公开对抗性反例

1. mainland_open=True、hong_kong_open=False、buy_quota_available=True 必须成功构建（不得照搬 B2 connect_open 约束）。
2. 三 bool 全同，仅 quota_identity 不同则 context_id 不同。
3. kwargs 使用非公开字段别名应失败。
4. 伪 Enum（同 value 不同类）不得通过 _require_enum。
5. Protocol 同名方法但参数名错误，或返回 SimpleNamespace：isinstance 可能仍 True，调用侧必须失败。
6. 查询闭包（若采纳 P1-2）：请求 SH 返回 SZ 必须 fail closed；归属须在文档声明。
7. 相同日历秒、不同 as_of.microsecond 则不同 context_id。
8. 即使 hex 碰巧等于某 B2 calendar_identity，P0A 内也不得/不能验证双开市与之一致。

## 5. 与现行代码的差距快照（非缺陷）

- enums.py：无 ConnectRoute
- contracts.py：无 VerifiedConnectMarketContext / build_*
- ports.py：无 ConnectMarketContextRepository
- 包根导出与两直接测试：无对应符号/节点

B2 ConnectCalendarState 仍是现行消费合同；P0A 为并行增量，仅在关闭本节 P0 并修订任务书后可实现。

## 6. 给主 Agent 的处置建议

1. 先修订 P0A 任务书，关闭两个 P0，并吸收 hong_kong_open 命名与 Port 返回闭包等 P1。
2. 修订前不下发实现；实现者不得自行宣布 Gate/B4 进度。
3. 待 R1C source-tree 写锁释放后，再串行启动 P0A 实现、独立初验、主验。
4. P0B 起草时必须含 B2 字段映射表、ConnectCalendarState 退役或降级路径、Intent/Snapshot 的 context_id 闭包。

## 7. 审查结论

- 设计方向：通过（显式 Route、领域枚举、自证 context、窄 port、P0A/P0B 拆分）。
- 可下发实现：否（P0 未关闭）。
- 本报告唯一写入路径：`docs/agent/M4_B4-P0A港股通RouteContext领域合同独立设计审查报告.md`。
