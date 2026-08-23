# M3 G1-R1B 可恢复工作流服务骨架外部闭环任务单

日期：2026-07-15  
状态：**设计冻结；R0、R1A、R1L 前置主验已通过，等待启动**  
执行模型：非 fast `cursor-grok-4.5-high`  
环境：WSL Miniforge `base`

## 1. 目标和排除项

R1B 组合已经主验通过的 B2A、P2、P3、P4A–P4C 组件，提供可由 CLI 调用的五段工作流服务：

```text
INDEX → HISTORY → REFERENCE → PREPARE → PUBLISH
```

每段必须能从不可变 raw + strict journal 恢复，不能依赖上一进程中的 DataFrame。R1B 实现服务 API 和 fake
集成测试，但不实现 argparse CLI、不执行完整 2016–2026 真实回补、不修改配置、不改变既有 data 合同。

R1B 通过只表示工作流骨架可恢复；真实全量运行和 Gate 由后续 R1C 完成。

## 2. 前置与权威来源

- R0 主验：真实 token、七端点、BaoStock、SH/SZ 日历和内核探针证据。
- R1A 主验：`G1RuntimeIdentityV1/G1StaticPlanV1/G1DerivedHistoryPlanV1`。
- G1-R1L 主验：B2A/P4B crash-safe writer lock；R1B 不再兼容旧空文件 `O_EXCL` 锁。
- 配置：`src/quant/research/m3/config.py`。
- raw/journal：`src/quant/data/m3_backfill.py`、`src/quant/data/m3_reference.py`。
- candidate/release：`src/quant/data/m3_g1_candidate.py`、`src/quant/data/m3_release.py`。
- 行为和环境：[`../AGENTS.md`](../../../AGENTS.md)。

## 3. 文件白名单

```text
src/quant/research/m3/g1_workflow.py
src/quant/research/m3/__init__.py
tests/unit/test_m3_g1_workflow.py
docs/M3_G1_R1B可恢复工作流服务骨架交付报告.md
docs/M3_G1_R1B可恢复工作流服务骨架独立初验报告.md  # 初验 Agent 专属
```

不得修改 connector、RawStore、B2A/P2/P3/P4 算法、R1A、C0、配置、路线图或 data/artifacts。默认自动测试
不得访问网络；真实 connector 只通过显式注入进入执行函数。

## 4. 固定目录布局

R1B 接受 `project_root: Path`，只允许以下受控相对路径，不接受调用方传入第二套 raw/journal/release 路径：

```text
data/clean/trade_calendar/market=SH/data.parquet
data/clean/trade_calendar/market=SZ/data.parquet
data/clean/instrument/market=SH/data.parquet
data/clean/instrument/market=SZ/data.parquet
data/raw/m3_g1/                              # RawStore root
data/run_state/m3_g1/tushare/               # B2A journal root
data/run_state/m3_g1/baostock/              # P4B journal root
data/clean/m3_g1/releases/                  # P4C output root
```

这些物理路径不进入 candidate/release identity，不持久化到摘要，不出现在公开异常。`project_root`、各祖先和
目标路径拒绝 symlink；root 必须为绝对真实目录且入口/退出物理 identity 不变。测试用临时项目根也采用完全
相同的相对布局。

## 5. 冻结公共接口

```python
Stage = Literal["INDEX", "HISTORY", "REFERENCE", "PREPARE", "PUBLISH"]
Operation = Literal["INSPECT", "INDEX", "HISTORY", "REFERENCE", "PREPARE", "PUBLISH"]
CauseCategory = Literal[
    "INPUT", "PATH", "SOURCE_SCHEMA", "JOURNAL", "NETWORK",
    "MEMBERSHIP", "CANDIDATE", "REFERENCE", "RELEASE", "UNSUPPORTED",
]

@dataclass(frozen=True)
class G1WorkflowCountsV1:
    index_requests: int
    history_requests: int
    reference_requests: int
    history_symbols: int

@dataclass(frozen=True)
class VerifiedG1WorkflowStateV1:
    schema_version: Literal["m3-g1-workflow-state-v1"]
    static_plan: G1StaticPlanV1
    derived_plan: G1DerivedHistoryPlanV1 | None
    index_responses: tuple[VerifiedRawResponse, ...]
    history_responses: tuple[VerifiedRawResponse, ...]
    reference_responses: tuple[VerifiedReferenceResponse, ...]
    candidate: G1Candidate | None
    prepared: G1PreparedRelease | None
    published: VerifiedG1Release | None
    completed_stages: tuple[Stage, ...]
    counts: G1WorkflowCountsV1

class M3G1WorkflowError(ValueError):
    code: Literal[
        "G1_WORKFLOW_INPUT_INVALID",
        "G1_WORKFLOW_PROJECT_ROOT_INVALID",
        "G1_WORKFLOW_SOURCE_CONTEXT_INVALID",
        "G1_WORKFLOW_INDEX_INCOMPLETE",
        "G1_WORKFLOW_HISTORY_INCOMPLETE",
        "G1_WORKFLOW_REFERENCE_INCOMPLETE",
        "G1_WORKFLOW_JOURNAL_INVALID",
        "G1_WORKFLOW_EXECUTION_FAILED",
        "G1_WORKFLOW_QUALITY_FAILED",
        "G1_WORKFLOW_PUBLISH_UNSUPPORTED",
        "G1_WORKFLOW_PUBLISH_FAILED",
        "G1_WORKFLOW_IDENTITY_MISMATCH",
    ]
    operation: Operation
    cause_category: CauseCategory

def inspect_g1_workflow(
    *, project_root: Path, config: LoadedM3Config,
) -> VerifiedG1WorkflowStateV1: ...

def run_g1_index_stage(
    *, project_root: Path, config: LoadedM3Config,
    connector: TushareConnector,
    classify_error: Callable[[BaseException], str],
) -> VerifiedG1WorkflowStateV1: ...

def run_g1_history_stage(
    *, project_root: Path, config: LoadedM3Config,
    connector: TushareConnector,
    classify_error: Callable[[BaseException], str],
) -> VerifiedG1WorkflowStateV1: ...

def run_g1_reference_stage(
    *, project_root: Path, config: LoadedM3Config,
    connector: BaostockConnector,
) -> VerifiedG1WorkflowStateV1: ...

def prepare_g1_workflow(
    *, project_root: Path, config: LoadedM3Config,
) -> VerifiedG1WorkflowStateV1: ...

def publish_g1_workflow(
    *, project_root: Path, config: LoadedM3Config,
) -> VerifiedG1WorkflowStateV1: ...
```

执行函数只接受具体项目 connector 薄适配器，测试用其公开注入 client；不接受任意 duck-typed SDK。全部
dataclass exact-type、自证、冻结；frames 由上游 verified 值对象重建。异常 `str` 固定为
`"<stage>:<code>"`，`repr/cause/traceback` 不含绝对路径、SDK repr、token 或底层异常文本；边界统一
`from None`。`cause_code` 只允许既有稳定项目 error code allowlist，不能存异常 message。

## 6. 权威 source context

每次公开调用都从磁盘重新读取，不接受调用者传裸 calendar/instrument：

1. SH/SZ calendar 文件必须是普通非 symlink Parquet，分别经 `TradeCalendarSchema` 验证；同一自然日无
   缺口，至少覆盖 R1A 所需 warmup/tail；market 分别只能为 SH/SZ，且两者日期域和 `is_open` 逐日完全
   一致。session 规划只使用 SH 行，但 G1 audit/identity 同时消费两市场权威行。
2. SH/SZ instrument 两文件分别验真后 vertical concat，经 `InstrumentSchema` 验证；symbol 唯一，market 与
   后缀一致。
3. R1A 先用完整 context 派生 history；正式 `G1BuildInputs` 只传：
   - calendar：`history.start..history.end` 的完整 SH+SZ 两市场自然日切片；
   - instruments：`history_symbols` 的精确一行/证券切片。
4. 两市场切片不得缺自然日、开市日、证券或生命周期字段，日期域/开闭市必须继续一致；不得把全市场未来
   日历/无关证券塞进 release identity。
5. 读取前后重新检查文件 bytes SHA-256 和 inode/size/mtime；任一变化 fail-closed。

## 7. inspect：只能恢复，不得联网或写入

`inspect_g1_workflow` 是每段的唯一入口前置：

1. 重新调用 R1A `build_g1_static_plan`；
2. 对 static index batch 的每个 request 检查固定 journal receipt：
   - 全部存在：逐个调用 `verify_tushare_receipt`，形成严格排序 tuple；
   - 全部缺失：INDEX 未完成，返回空 responses；
   - 部分存在、intent/candidate/raw 孤儿：不得猜测为完成；INDEX 未完成但保留给 executor 的合法恢复状态；
   - 已提交 receipt 损坏、额外目录、symlink、未知文件：`G1_WORKFLOW_JOURNAL_INVALID`。
3. INDEX responses 完整后调用 R1A `derive_g1_history_plan`；再按同样规则恢复 history responses。
4. history 完整后从原始 context + 全部 verified responses 构造 `G1BuildInputs`，调用
   `build_g1_candidate`、`verify_g1_candidate`、`audit_g1_candidate`；audit 非 PASS 立即 quality failed。
5. 由 candidate 确定 sample/reference plan，再恢复 BaoStock receipts；完整时调用
   `reconcile_cross_source`。
6. reference 完整且 PASS 时可以在函数内部临时构造 `G1ReleaseInputs` 并调用纯函数
   `prepare_g1_release`，但普通 inspect 在目标 release 不存在时必须丢弃该 transient 对象：返回
   `prepared=None`，completed 严格停在 REFERENCE。
7. 只按临时 prepared 的唯一 `release_id` 检查目标 release；不存在时不得把 PREPARE 标记为已完成。存在时
   调 `verify_g1_release` 并逐字段证明与 prepared 完全一致，此时返回 prepared+published 且 completed 一次
   性闭包到 PUBLISH。不得扫描并选择“最近 release”。

`completed_stages` 必须是前缀且固定顺序。PREPARE 是 `prepare_g1_workflow` 返回值中的瞬时完成态，不是磁盘
marker；普通 inspect 在尚未发布时不声称 PREPARE 完成。已发布 release 本身证明其 PREPARE 前置，故 inspect
可闭包返回 PREPARE+PUBLISH。PUBLISH 只有真实 verified release 才完成。

## 8. 各执行段

### 8.1 INDEX

- 入口 inspect；若 INDEX 已完成，零网络、零写入复用并返回。
- 否则只把 static `index_weight_batch` 传给 `execute_tushare_batch`，参数逐项来自 static plan；raw/journal
  使用固定布局。
- executor 返回后不信任 receipt tuple，重新 inspect；INDEX 不完整即失败。
- 不得继续执行 HISTORY。

### 8.2 HISTORY

- 入口 inspect；INDEX 未完成则 `G1_WORKFLOW_INDEX_INCOMPLETE`，不得联网。
- HISTORY 已完成则零网络复用。
- 只执行 derived `request_plan.history_batch`；完成后重新 inspect，停在 HISTORY。
- 不得调用 BaoStock、prepare 或 publish。

### 8.3 REFERENCE

- 入口 inspect；HISTORY 未完成不得登录 BaoStock。
- REFERENCE 已完成则零网络复用。
- sample plan/request plan 只由 verified candidate 派生；只调用
  `execute_baostock_reference_plan`，完成后重新 inspect。
- 跨源 mismatch 超阈值是 quality failed，不得发布。

### 8.4 PREPARE

- 严格零网络、零文件写入；REFERENCE 不完整则 fail。
- 只返回每次从 raw 重新构建的 `G1PreparedRelease`，并在该返回 state 中把 PREPARE 加入 completed；不得
  接受或缓存调用者自报 candidate/audit/quality。随后单独调用普通 inspect 仍只显示磁盘可证明的前缀。

### 8.5 PUBLISH

- 入口先 prepare；调用 `platform_supports_renameat2_noreplace()`。false 时稳定
  `G1_WORKFLOW_PUBLISH_UNSUPPORTED`，不创建 staging/release。
- true 时只调用 `publish_g1_release`，再重新 inspect 并要求 PUBLISH 完成。
- 同 identity 已存在时必须验真复用；冲突/损坏不覆盖。

## 9. 重试分类

R1B 不自行识别 SDK message。`classify_error` 必须返回精确：

```text
NETWORK | RATE_LIMIT | TRANSIENT_SERVER | PERMANENT
```

非法返回统一执行失败。Tushare executor 的次数/退避仍由 static plan控制。BaoStock P4B 当前没有 retry，R1B
不得暗中增加；失败后依赖原 journal recovery 重跑整个 stage。

### 9.1 上游异常归类

公开异常不保存任意上游 code/message，只保存固定 `CauseCategory`：

| 来源 | workflow code | category |
|---|---|---|
| config/value object/type | `G1_WORKFLOW_INPUT_INVALID` | `INPUT` |
| project root/祖先/containment | `G1_WORKFLOW_PROJECT_ROOT_INVALID` | `PATH` |
| calendar/instrument read 或 Schema | `G1_WORKFLOW_SOURCE_CONTEXT_INVALID` | `SOURCE_SCHEMA` |
| receipt/raw/journal/lock/identity 文件闭包 | `G1_WORKFLOW_JOURNAL_INVALID` | `JOURNAL` |
| Tushare executor 永久失败/耗尽 | `G1_WORKFLOW_EXECUTION_FAILED` | `NETWORK` |
| PIT normalize/build/verify | `G1_WORKFLOW_IDENTITY_MISMATCH` | `MEMBERSHIP` |
| candidate build/verify/audit | `G1_WORKFLOW_QUALITY_FAILED` | `CANDIDATE` |
| BaoStock/reconciliation | `G1_WORKFLOW_EXECUTION_FAILED` 或 `G1_WORKFLOW_QUALITY_FAILED` | `REFERENCE` |
| prepare/release verify/publish | quality 或 publish 对应 code | `RELEASE` |
| kernel probe false | `G1_WORKFLOW_PUBLISH_UNSUPPORTED` | `UNSUPPORTED` |

同一上游异常若发生在不同 operation，`operation` 必须反映公开函数当前动作；inspect 前置失败使用
`INSPECT`，不得伪报 INDEX。

### 9.2 counts 生命周期

counts 全部表示**当前 verified plan 的计划总数**，不表示已完成数：

| 最后 verified 阶段 | index_requests | history_symbols/history_requests | reference_requests |
|---|---:|---:|---:|
| 尚无 INDEX | static batch 总数 | 0 / 0 | 0 |
| INDEX 及以后 | static batch 总数 | derived plan 总数 | candidate 派生 plan 总数（candidate 未形成前为 0） |

完成进度只看 `completed_stages`；不得用 receipt 文件数量填入这些字段。candidate 在 HISTORY 完成并全量重建
后必须出现；prepared 只在显式 PREPARE 返回态或已发布态出现；published 只在 PUBLISH 出现。

## 10. 测试矩阵

使用 fake Tushare/BaoStock client 和临时固定布局做完整五段状态机，至少覆盖：

1. fresh inspect 零网络零写；五段逐段运行，每段严格停止；最终 fake-supported publish 后 inspect 全完成；
2. 每段第二次调用网络计数为零，所有 identity/receipt 相同；
3. INDEX/HISTORY 中断在 intent、raw data、raw metadata、candidate、receipt 前后，重跑只走既有 B2A 合法
   recovery；已提交损坏失败；
4. reference 同类 P4B recovery、30 requests 不多不少；
5. 额外 journal 目录/文件、symlink、hardlink、receipt 指向另一 raw root、整体自洽替换；
6. clean SH/SZ calendar/instrument 在 inspect 中途同大小替换，或加入 history window 外未来数据；前者
   失败，后者不改变 canonical build inputs/release identity；另构造沪深某日 `is_open` 不一致并失败；
7. 早期调出证券必须保留在 history symbols/instrument slice；缺它失败；
8. inspect 不扫描其他 release；准备的 release ID 与磁盘另一个合法 release 并存时只验唯一目标；
9. WSL1 unsupported 分支零 staging；模拟支持分支验证 no-clobber/复用/冲突；禁止生产路径出现
   `os.replace`；
10. 任一 underlying error 的 message/cause 含 token 和绝对路径，公开异常仍稳定脱敏；
11. import 隔离：`quant.research.m3.g1_workflow` 不 import Qlib/MLflow/LightGBM，不把 SDK import 移出
    connector；
12. 全量 pytest、Ruff、mypy。

## 11. 独立初验

全新 Grok High 会话只读生产代码/实现者测试，只写初验报告。必须新增：

- 在 INDEX 完成后整体替换为另一份合法但 G1 hash 不同的 config：若 request specs 完全相同，证明
  Tushare raw/journal 可按 request identity 复用，但 static/candidate/release identity 必须改变；若 request
  specs 改变，则旧 receipt 不能冒充新 request；
- 在 REFERENCE 完成后替换一份 primary raw，同时同步伪造其局部 receipt，证明 P4A/P4C 全闭包仍失败；
- 在 publish 目录 rename 前替换项目根祖先，证明路径边界不退化；
- 构造两个合法 release 并让非目标者字典序更靠前，证明 inspect 不“任选一个”。

不通过即按项目标准格式返回原实现 Agent，直到独立初验明确通过后进入主 Agent 终验。
