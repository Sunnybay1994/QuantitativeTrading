# M4 P8 RUN-0B2D：Formal PAPER 账户 Genesis 任务单

日期：2026-08-09  
状态：**四项业务 SSOT 已于 2026-08-12 批准；外部实现 Agent 已交付，待独立初验与主 Agent 终验**  
性质：development 工程前置；只读 account config/descriptor capability，不创建 store/gateway/runtime

## 1. 目标与硬停止条件

在 RUN-0A R3、RUN-0B2B、RUN-0B2C 主验 PASS 后，新增唯一 formal A 股 PAPER account genesis
loader，把版本化、非秘密账户配置 fresh 绑定为 process-local
`VerifiedFormalPaperAccountDescriptor`。本包只读唯一 TOML，不 mkdir、不打开 SQLite、不创建 broker/runtime/evidence/
anchor/log root，不启动 runner/soak。

仓库当前没有正式 PAPER 初始资金 SSOT；M2/M3 研究配置中的 `1,000,000` 不得自动提升为交易账户事实。
以下四项缺任一即停止，不得从 fixture/example 推断：

| 字段 | 待批准建议值 |
|---|---|
| account selector | `formal_paper_a_share_v1` |
| non-secret label | `FORMAL_PAPER_A_SHARE` |
| genesis aware UTC | `2026-08-10T00:00:00Z` |
| initial settled/available CNY | `500000.00` |

冻结的工程不变量：A股 only、base currency CNY、exact 一条 cash；金额 canonical 两位小数且大于零；
settled=available；receivable=payable=`0.00`；positions exact 空；无冻结资产。若要求初始持仓、冻结资产或其他
币种，停止并另立来源/lot/可卖与冻结依据任务。

## 2. 唯一配置与派生路径

批准后新增唯一 formal config：

```text
configs/trading/accounts/{environment.config.account_selector}.toml
```

路径只能从 fresh runtime 的 `project_root` 与 selector 派生，caller 不得传 path/hash/mapping/classification。
建议格式：

```toml
[meta]
schema_version = "formal-paper-account-v1"
account_version = "formal_paper_a_share_v1"
classification = "formal-paper-simulation"
assumption_notice = "FORMAL PAPER SIMULATION ONLY; NOT A LIVE BROKER ACCOUNT"

[account]
account_label = "FORMAL_PAPER_A_SHARE"
base_currency = "CNY"

[initial_state]
as_of = "2026-08-10T00:00:00Z"
settled_cny = "500000.00"
available_cny = "500000.00"
receivable_cny = "0.00"
payable_cny = "0.00"
positions = []
```

上述 selector、label、genesis UTC 与 `500000.00` CNY 已由用户于 2026-08-12 批准并升级为本包 SSOT。formal config 不接收 caller account_id、snapshot_id、
risk scope、source identity、broker identity、token 或 created_at；created_at exact 等于 `initial_state.as_of`。
另可新增明确被 formal loader 拒绝的 example/development 配置。

## 3. Public API 与 exact capability

新增 `quant.execution.paper_account`，`__all__` exact 四项：

```python
FormalPaperAccountError
VerifiedFormalPaperAccountDescriptor
load_verified_formal_paper_account_descriptor
verify_existing_formal_paper_account_descriptor
```

```python
def load_verified_formal_paper_account_descriptor(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    now: datetime,
) -> VerifiedFormalPaperAccountDescriptor: ...
```

existing verifier 使用同一输入并返回传入的同一 exact capability。session 从 binding/policy读取；无 caller
session/classification/id/version 参数。

capability 至少绑定：schema/classification/session_date/selector；source path/file/parent identity与raw hash；
runtime environment、execution policy、broker binding identity；nested exact `PaperAccountDescriptor`；stable
`account_id`、initial snapshot identity、descriptor identity、risk counter scope、verification identity、verified_at
及私有 process-local attestation。不可 pickle；subclass/duck/dict/object.__new__/reload旧token拒绝。

## 4. Fresh、身份与业务语义

load 顺序：exact input/UTC -> fresh B2C existing verifier（递归重验 runtime+policy）-> selector exact且非example ->
no-follow anchored只读唯一 config -> strict canonical keys/types/两位小数 -> build exact `AccountSnapshot` -> fresh
snapshot identity -> build B1 `PaperAccountDescriptor` -> 再 fresh B2C、file object/parent/raw -> private mint。

- stable account_id 只绑定 schema/label/genesis UTC/CNY/initial snapshot，跨 Windows/Linux语义相同。
- physical source identity、runtime/B2C与capability verification identity另行绑定，不把 inode 放入 stable account_id。
- `risk_counter_scope = "paper-" + account_id`，长度须满足现有 service contract；caller不能传。
- stable account_id 必须与每日变化的 `AccountSnapshot.snapshot_id` 区分；后者不得冒充跨 28 日账户身份。
- config source identity只证明 genesis；后续 broker snapshot `source_identity` 必须来自 durable broker store/journal。

existing 先 exact type/attestation，再 fresh B2C、重开同一 config、重建 snapshot/descriptor/risk scope并全字段 exact
比较；`now` 不早于各 verified_at。

## 5. 失败语义与零副作用

稳定错误码：

- `PAPER_ACCOUNT_ENVIRONMENT_INVALID`
- `PAPER_ACCOUNT_POLICY_BINDING_INVALID`
- `PAPER_ACCOUNT_SELECTOR_UNSUPPORTED`
- `PAPER_ACCOUNT_SOURCE_INVALID`
- `PAPER_ACCOUNT_SEMANTICS_INVALID`
- `PAPER_ACCOUNT_STALE`
- `PAPER_ACCOUNT_INVALID`

所有 public 失败必须在 active except 外重建，cause/context None，repr/traceback 不泄露 path、raw、金额、SQL、
TOKEN 或 hostile marker。仅允许读唯一 account TOML；禁止 wall-clock（只用 caller now）、network/socket、SQLite、
mkdir、写文件、cache、log、正式 root/journal。

## 6. 必测反例

1. development/example selector或 capability；cross environment/policy/binding/session。
2. 同 bytes 换 inode、parent/file replacement、symlink/junction/reparse、copied root、persistent drift。
3. whole-file rehash、未知/缺/多 key、非canonical bytes、caller 64hex/source/snapshot/account/risk ID。
4. 非CNY、多cash、0/负/指数/非2dp、available!=settled、非零receivable/payable、任一position。
5. stable account_id 与 daily snapshot id 的差异断言；跨平台 stable IDs一致而physical identity不宣称一致。
6. capability subclass/duck/dict/object.__new__/pickle/reload旧token。
7. hostile runtime/policy/binding/file parser递归异常图，固定码、空cause/context、零result。
8. monkeypatch mkdir/open非唯一文件/sqlite/socket/log/time证明零副作用；cold import/from-star exact四项，无mint/key。

## 7. 白名单、验证与后续

批准四值后实现白名单：

- 新 `src/quant/execution/paper_account.py`
- 新 `configs/trading/accounts/formal_paper_a_share_v1.toml`
- 可选、明确 formal 拒绝的新 example config
- 新 `tests/unit/test_paper_account.py`
- 本任务状态与唯一交付/独立复验/主验报告

禁止修改 runtime/policy/binding/B1 store/gateway/service/CLI/soak/package root、正式 roots/journal。Windows 与 WSL
base执行 focused+runtime/policy/binding/account合流pytest、Ruff、mypy、cold import、diff-check；DrvFS只算兼容，
不是 ext4 Gate。

B2D 主验 PASS 后才允许冻结 formal store initializer/opener + durable gateway factory/snapshot port；其必须 fresh
消费 runtime+B2C+B2D，持久化 stable account identity 与 genesis source identity，不能放宽 B1 development policy。
