# M4 P8 RUN-0B2C：Formal Broker Policy Binding 任务单

日期：2026-08-09
状态：实现、独立初验与主 Agent 终验 PASS（development 工程前置）
性质：development 工程前置；只读 capability binding，不创建 store/gateway/runtime

## 1. 目标

把 RUN-0A R3 的 formal runtime environment 与 RUN-0B2B 的 formal A股 PAPER execution policy fresh绑定为
唯一 `VerifiedFormalPaperBrokerPolicyBinding`，供后续 formal account/store/gateway 装配使用。

当前 B1 `PaperBrokerPolicyDescriptor` 与其 public builder严格限定 `classification="development"`；本包不得把它
放宽为字符串联合，也不得让development descriptor冒充formal。新增独立、exact、process-local formal binding，
保留B1全部development行为不变。

本包不创建/打开root、SQLite、journal或gateway，不实现fill/fault/clock算法，不接M3 target/calendar/account，
不注册scheduler、不启动soak。

## 2. 权威输入与不变量

- environment exact为`VerifiedPaperRuntimeEnvironment`，必须fresh通过
  `verify_existing_paper_runtime_preflight`；
- policy exact为`VerifiedPaperExecutionPolicy`，必须fresh通过
  `verify_existing_paper_execution_policy`；
- `policy.session_date`、runtime config/environment identity、B2B policy/cost identity以及adapter/fill/fault/
  finality/clock版本全部由fresh对象读取，caller无单独参数入口；
- classification exact固定`formal-paper-simulation`，不能由caller提供；FX exact为None，supported markets exact
  SH/SZ由B2B verifier证明；
- `now` aware UTC，不能早于environment/policy verified_at；fresh返回值必须exact等于传入值。

## 3. 公共接口

新增`src/quant/execution/paper_broker_binding.py`：

```python
@dataclass(frozen=True, slots=True)
class VerifiedFormalPaperBrokerPolicyBinding:
    schema_version: str
    classification: Literal["formal-paper-simulation"]
    session_date: date
    runtime_environment_identity: str
    runtime_config_identity: str
    execution_policy_identity: str
    adapter_policy_version: str
    fill_policy_version: str
    fault_policy_version: str
    finality_policy_version: str
    clock_policy_version: str
    cost_schedule_identity: str
    fx_snapshot_identity: None
    binding_identity: str
    verified_at: datetime
    # private process-local attestation，repr/compare排除

def bind_verified_formal_paper_broker_policy(
    *,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    now: datetime,
) -> VerifiedFormalPaperBrokerPolicyBinding: ...

def verify_existing_formal_paper_broker_policy_binding(
    *,
    binding: VerifiedFormalPaperBrokerPolicyBinding,
    environment: VerifiedPaperRuntimeEnvironment,
    policy: VerifiedPaperExecutionPolicy,
    now: datetime,
) -> VerifiedFormalPaperBrokerPolicyBinding: ...
```

formal mint只能位于模块私有closure，创建函数随后删除；模块不得暴露generic signer/key/builder/factory。
`__all__` exact只含错误、binding type、bind、verify四项。capability不可pickle；subclass/duck/dict/
`object.__new__`伪对象均不能通过existing。

## 4. Fresh与identity闭包

bind顺序：exact输入/UTC → fresh runtime verifier → fresh policy verifier → 从fresh值构造canonical payload → mint。
RUN-0A 的 `verify_existing_paper_runtime_preflight` 是成功返回 `None` 的验证命令，因此以“调用成功且原 exact
environment 继续作为唯一输入”为契约，不虚构 capability 返回值；RUN-0B2B policy verifier 返回 capability，
必须 exact type 且 exact-equal 于传入 policy。签发前不得读取caller自报identity/version；任一 fresh verifier
失败则零result。

binding identity至少绑定：schema/classification、session_date、runtime verification identity、runtime config
identity、policy identity、cost identity、adapter/fill/fault/finality/clock版本、FX None与verified_at。attestation
绑定同一完整payload，使用process-local私有key。

existing先验证exact type与attestation，再fresh调用同一两个public verifier，重建binding并exact compare；不得只
验token或普通64hex。跨environment/policy/session、旧policy文件/旧runtime token、nested drift均拒绝。

## 5. 失败语义与零副作用

唯一公开错误`FormalPaperBrokerPolicyBindingError`，稳定码：

- `PAPER_BROKER_BINDING_ENVIRONMENT_INVALID`
- `PAPER_BROKER_BINDING_POLICY_INVALID`
- `PAPER_BROKER_BINDING_STALE`
- `PAPER_BROKER_BINDING_INVALID`

所有公开失败cause/context为None，repr/traceback不含path、raw、SQL、TOKEN或hostile marker。模块不得open文件、
连接SQLite/socket、读取墙钟或写log/cache/root；`now`只能由caller显式传入。

## 6. 白名单

- 新`src/quant/execution/paper_broker_binding.py`
- 新`tests/unit/test_paper_broker_binding.py`
- 本任务单、唯一交付报告、唯一独立复验报告、主验报告

禁止修改`paper_runtime.py`、`paper_policy.py`、`paper_broker_store.py`、`paper_durable.py`、gateway/service/CLI、
store/migration、soak、package root、配置或正式artifacts/journal。

## 7. 必测正例与反例

正例：同一fresh formal environment+policy在2026 session绑定；existing fresh exact通过；canonical identity跨平台
一致（attestation本身不要求跨进程）。

反例至少覆盖：

1. development runtime/policy/`PaperBrokerPolicyDescriptor`即使版本与cost相同也拒绝；
2. binding subclass/clone/duck/dict/object.__new__/pickle/reload旧token；
3. environment、policy、session任一交叉拼接或nested字段漂移；
4. policy文件whole-rehash/同bytes换inode/旧attestation由B2B fresh verifier拒绝；
5. caller无法传classification、64hex identity或adapter/fill/fault/finality/clock值；
6. hostile runtime/policy verifier ValueError、RuntimeError与递归cause/context图：固定码、空异常链、零result；
7. monkeypatch open/socket/sqlite/log/clock证明零I/O；
8. cold import不加载broker DB、soak、Qlib/LightGBM/MLflow；from-star exact四项，无generic mint/key。

Windows原生与WSL base运行定向pytest/Ruff/mypy/cold import/diff；DrvFS只算开发兼容。实现与独立初验必须不同
上下文，初验补至少一个未用的cross-capability或hostile异常图。

## 8. 停止条件与后续顺序

若需要创建/open broker root/DB、修改B1 development descriptor、构造具体fill/fault/gateway、引入formal account
初始资金/持仓、TargetLoader/calendar/ServiceFactory或runner，则停止回主Agent。

B2C通过后顺序：formal PAPER account config/descriptor loader → formal store initializer/opener + durable gateway
factory/snapshot port → LedgerContext/Service装配。不得跳过account SSOT直接建store。
