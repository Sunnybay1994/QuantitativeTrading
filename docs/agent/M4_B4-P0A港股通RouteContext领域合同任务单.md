# M4 B4-P0A 港股通 Route Context 领域合同任务单

日期：2026-07-17  
状态：**v2 已关闭独立设计审查 P0；等待当前 M3 source-tree 长测试结束后下发**  
性质：M4-B4 前置的非破坏性 D0/D1 增量；不实现 order planner，不关闭 B4/M4 Gate

修订依据：[`M4_B4-P0A港股通RouteContext领域合同独立设计审查报告.md`](M4_B4-P0A港股通RouteContext领域合同独立设计审查报告.md)。v2 已冻结 D0 envelope/固定向量、不透明 provenance、
`hong_kong_open`、Protocol 返回闭包、route quota SSOT 和遗留字符串集合禁令；实现者不得恢复 v1 留白。

## 1. 唯一目标

建立“某一明确港股通 route 在某 session/as_of 的双日历与买入额度事实”的自证领域对象和窄 repository port，
让后续 B4 不必猜 route，也不必直接读取数据目录。P0A 不把 route 接入 `OrderIntent` / `SymbolMarketState` / B2；
该破坏性迁移留给 P0B，必须在 P0A 主验后串行进行。

## 2. 冻结接口

### 2.1 枚举

在 `quant.domain.enums` 新增并包根导出：

```python
class ConnectRoute(str, Enum):
    SH_CONNECT = "SH_CONNECT"
    SZ_CONNECT = "SZ_CONNECT"
```

不得在新代码复制第二份字符串集合。

### 2.2 自证对象

在 `quant.execution.contracts` 新增并包根导出：

```python
@dataclass(frozen=True, slots=True)
class VerifiedConnectMarketContext:
    context_id: str
    route: ConnectRoute
    session_date: date
    as_of: datetime
    mainland_open: bool
    hong_kong_open: bool
    buy_quota_available: bool
    calendar_identity: str
    quota_identity: str
    source_identity: str

def build_verified_connect_market_context(
    *,
    route: ConnectRoute,
    session_date: date,
    as_of: datetime,
    mainland_open: bool,
    hong_kong_open: bool,
    buy_quota_available: bool,
    calendar_identity: str,
    quota_identity: str,
    source_identity: str,
) -> VerifiedConnectMarketContext: ...

def build_verified_connect_market_context_identity(
    context: VerifiedConnectMarketContext,
) -> str: ...
```

合同：

- `as_of` 必须 timezone-aware UTC，`session_date` 为交易所本地 date；builder 只接受上述九个经济/provenance
  keyword-only 参数，禁止接收调用方自报 `context_id`、字段别名或额外 kwargs；
- 三个 boolean 必须是精确 `bool`，不得接受 0/1；route 必须是精确 `ConnectRoute`；
- `calendar_identity`、`quota_identity`、`source_identity` 必须是 64 位小写 hex，语义均为 repository 已验真
  上游事实的不透明 provenance。P0A 只验证格式并纳入 context identity，不尝试从中还原 payload、不要求等于
  B2 `ConnectCalendarState` digest，也不 import `quant.backtest`/`quant.data`；
- builder 必须复用本模块既有 `_sha256_envelope`：`hash_version="execution-contract-hash-v1"`、
  `type="VerifiedConnectMarketContext"`，payload 键精确为 `route/session_date/as_of/mainland_open/
  hong_kong_open/buy_quota_available/calendar_identity/quota_identity/source_identity`；继续使用既有
  `_json_value`、UTF-8、`ensure_ascii=False`、`sort_keys=True`、`separators=(",", ":")`、`allow_nan=False`；
- dataclass 构造器和 identity builder 都必须从当前 payload 重算并拒绝 forged id；异常稳定、脱敏、无 cause/path；
- route→内地交易所的解释只由枚举语义决定：`SH_CONNECT→SH`、`SZ_CONNECT→SZ`，P0A 不新增可漂移的
  `mainland_market` 字段，也不在本包新增派生 helper；该映射留给 P0B；
- `buy_quota_available` 是 route 级事实，只限制 BUY；P0A 不复制 B2 的交易决策。
- P0A 故意不存 `connect_open`：它是 `mainland_open and hong_kong_open` 的规则层派生值，留给 B2/P0B。

固定锁定向量（测试必须逐字构造同一经济 payload，并断言 hex）：

```text
route=SH_CONNECT
session_date=2026-07-10
as_of=2026-07-10T08:00:00Z
mainland_open=true
hong_kong_open=false
buy_quota_available=true
calendar_identity=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
quota_identity=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
source_identity=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
context_id=de53c71c001da5fa70feb5cc5f2745431d9c9107350e0903052a8bd527e162c1
```

### 2.3 Port

在 `quant.execution.ports` 新增并包根导出：

```python
@runtime_checkable
class ConnectMarketContextRepository(Protocol):
    def load_verified_connect_market_context(
        self,
        *,
        route: ConnectRoute,
        session_date: date,
        as_of: datetime,
    ) -> VerifiedConnectMarketContext: ...
```

Protocol 无实现、无 IO、无 `data/` 路径、无 connector SDK。调用者必须显式给 route，禁止 `AUTO`/`ANY`。
所有实现必须满足返回闭包：返回值精确为 `VerifiedConnectMarketContext` 并通过其 identity builder；返回
`route/session_date` 与查询参数全等；返回 `context.as_of` 是事实可知时点且 `<=` 查询 `as_of`。P0A 的
`runtime_checkable Protocol` 只能证明同名方法存在，不能证明 Python 签名、返回类型或上述闭包；adapter 实现
与 P0B 调用边界必须再次显式验证，测试不得把 `isinstance(fake, Protocol)` 当作经济合同证明。

P0A 完成前，现有 `SymbolMarketState.buy_quota_available` 仅作为遗留 symbol 级字段保留；任何新代码不得把它
解释为港股通 route 额度。route 额度的新 SSOT 只能是 `VerifiedConnectMarketContext.buy_quota_available`。
白名单外的 B2 `_CONNECT_ROUTES` 和 schemas `isin` 暂不迁移，但不得扩张；P0A 新代码只能 import
`ConnectRoute`，不得复制字符串集合。

## 3. 文件白名单

实现 Agent 只可修改：

- `src/quant/domain/enums.py`
- `src/quant/domain/__init__.py`
- `src/quant/execution/contracts.py`
- `src/quant/execution/ports.py`
- `src/quant/execution/__init__.py`
- `tests/unit/test_execution_contracts.py`
- `tests/unit/test_execution_ports.py`
- `docs/agent/M4_B4-P0A港股通RouteContext领域合同交付报告.md`

禁止修改 B2、P3、TradingConfig、OrderIntent、SymbolMarketState、任何 repository 实现、数据和历史报告。

## 4. 必测反例

1. SH/SZ route 相同其余 payload 时 context identity 必须不同；顺序无关的 builder 重复调用 identity 稳定；
   上述固定向量必须精确命中冻结 hex。
2. route 传裸 string、`AUTO`、错误 enum；三个 bool 传 0/1；naive/non-UTC as_of；date/datetime 混用均失败。
3. 三个 upstream identity 分别大写、63/65 位、非 hex、同 id 异 payload；forged `context_id` 均失败。
4. `object.__setattr__` 篡改任一经济字段后，identity builder 必须拒绝；不能只返回携带 id。
5. runtime Protocol 的 good fake 通过；缺方法不通过。另用错误签名/错误 route/未来 as_of/错误返回类型 fake
   证明 `runtime_checkable` 本身不构成返回闭包，未来 adapter/调用侧必须 fail closed。
6. import 隔离：domain/contracts/ports 不 import `quant.data`、`quant.backtest`、研究框架或网络 SDK。
7. `mainland_open=True`、`hong_kong_open=False`、quota=True 必须可构造；仅改 quota_identity 或 as_of 微秒时
   context_id 必须改变；伪 Enum（同 value 不同类）拒绝。

## 5. 高效验证

默认只跑新增/直接相关 test node，不跑整份慢 workflow，更不跑全量 pytest：

```bash
python -m pytest \
  tests/unit/test_execution_contracts.py -k 'connect_market_context' \
  tests/unit/test_execution_ports.py -k 'connect_market_context' -q
python -m ruff check \
  src/quant/domain/enums.py src/quant/domain/__init__.py \
  src/quant/execution/contracts.py src/quant/execution/ports.py \
  src/quant/execution/__init__.py \
  tests/unit/test_execution_contracts.py tests/unit/test_execution_ports.py
python -m mypy \
  src/quant/domain/enums.py src/quant/execution/contracts.py src/quant/execution/ports.py
```

只有定向测试暴露公共回归时才扩大到 D0/D1 两个测试文件。报告记录实际命令、耗时和结果，不机械追加全量。

## 6. P0B 明确留白

P0A 主验后，P0B 才冻结并实现：

- route 如何进入 `OrderIntentSpec` / `OrderIntent` identity；
- HK `SymbolMarketState` 如何绑定 route，消除 `buy_quota_available` 的歧义；
- B2 的 `ConnectCalendarState` 如何被本对象替代而不是形成第二事实来源；
- `VerifiedMarketSnapshot` 是否包含 context_id 闭包；
- P3/B4 如何验证同 route、同 session、同 as_of 和同 snapshot identity。

P0A Agent 不得提前猜测或实现这些变化。
