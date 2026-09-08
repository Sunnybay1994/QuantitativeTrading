# M2-SHARED-CROSS-SECTIONAL-RANK 公共边界任务书

> 状态：`FROZEN / TASKBOOK_READY`
>
> 当前阶段：`TASKBOOK_ONLY`
>
> exact base：`dfe49df5e8dfd9d929eb8ad196beced1da19715d`
>
> branch：`codex/framework-m2-shared-cross-sectional-rank`
>
> worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\framework-m2-shared-cross-sectional-rank`
>
> 当前资源：`STATIC_ONLY`

## 0. 独立静态审查身份与永久 finding

本任务书首个冻结版本的审查身份永久保留如下，不得在返工后删除或改写为 PASS：

- reviewed path：`docs/framework/tasks/M2_SHARED_CROSS_SECTIONAL_RANK公共边界任务书.md`；
- reviewed identity：`12424 bytes` / SHA-256
  `c55e1269f72262f4ce7b2af0c6630a06fca854635d7ee7312bf2083886558468`；
- verdict：`STATIC_REVIEW_FAIL`，`P0=0 / P1=1 / P2=0`；
- 现象：原第 5 节列出了 error taxonomy，但没有冻结多重违规同时出现时的 stable total precedence，
  也没有要求 compound-invalid 和行置换对抗测试逐字验证同一最高优先级失败；
- 根因：仅冻结了单一错误类别，没有冻结 validation ordering 和公共异常表面；
- 应遵循规则：公共 fail-closed API 必须使用与行顺序、内部遍历和验证实现顺序无关的稳定全序；
- 最小复现：同一 frame 同时包含 null key、duplicate key 和 non-finite value，原合同无法判定
  哪个 code 必须胜出；
- 新增测试与通过条件：见第 5 节 stable total precedence 和第 7.1 节 compound-invalid 反例。

## 1. 目标与价值

为 R14 Alpha101 #004、R15 Alpha101 #011 和 R21 Alpha101 #002 的共同需求冻结一个中立、纯函数、
可独立测试的每日横截面 rank 公共边界，阻止第三套私有实现和模块间交叉 import。

用户可观察结果：给定标准化长表，公共 helper 按每个 `signal_date × component` 独立有效集合，
返回 ascending average-tie normalized rank，且输入行顺序不影响 canonical 输出。

## 2. 明确非目标

- 不改变 R14、R15、R21 的因子公式、组件定义、时序窗口、方向、输出列或经济假设。
- 不实现 time-series rank、correlation、winsorize、z-score、行业中性化、因子合成或选股。
- 不接 runner、label、repository、Parquet/data、evaluator、economic execution、trial、PAPER/LIVE 或网络。
- 不修改 `quant.factors` facade、Schema SSOT、config、README、路线图或任一现有 research worktree。
- 本任务不合流、不迁移 consumer、不产生 RankIC/Sharpe/成本或因子有效性结论。

## 3. 权威上下文与现状审计

适用 `AGENTS.md`、`.ai/README.md`、`.ai/coding_rules.md`、`.ai/workflows/multi_agent_delivery.md`和
`docs/governance/项目多Agent分层协作与资源治理规范.md`。任务书、交付和审查文档是生命周期权威；
session/ACK/status 只是诊断信息。

fresh 只读证据：

- exact base 存在；建立前目标 branch/worktree/taskbook 均不存在，无同名所有权冲突。
- R14 worktree 的 untracked `src/quant/factors/classic_eighth_batch.py` 含私有
  `_with_cross_section_ranks`，实现每 `trade_date` ascending average rank 及 `(rank-1)/(n-1)`。
- R15 worktree 的 untracked `src/quant/factors/classic_ninth_batch.py` 含私有
  `_with_component_rank`，分别处理三个组件的有效集合。
- R21 worktree 目前只有 taskbook；其第 5 节明确禁止第三套私有 rank，命中
  `CONTRACT_STOP / SHARED_RANK_BOUNDARY_REQUIRED`。
- 上述三个 worktree 的当前产物和历史证据全部只读；本任务不得“修复”、复制或重写它们。

## 4. 冻结的公共 API 与数据合同

### 4.1 公共身份

唯一公共身份候选为：

```text
quant.factors.cross_sectional_rank.rank_cross_sectional_components
```

不通过 `quant.factors.__init__` 再导出，不允许别名、fallback、consumer 私有副本或 cross-import。

### 4.2 输入

```python
def rank_cross_sectional_components(frame: pl.DataFrame) -> pl.DataFrame:
    ...
```

`frame` 必须是非空 exact Polars `DataFrame`，且 exact ordered columns/dtypes 为：

1. `signal_date: pl.Date`
2. `component: pl.String`
3. `symbol: pl.String`
4. `value: pl.Float64`

exact key 是 `(signal_date, component, symbol)`，必须唯一且三个 key 列全部非 null。
`component` 是 consumer 冻结的中立组件标识，helper 不解释经济含义。`value` 可为 null；
null 代表当日该组件的局部无效值，保留 key 但不参与排名。任一非 null `value` 若为 NaN/+Inf/-Inf，
整次调用 fail closed，不返回部分结果。禁止隐式 cast、补值、删行或先取各组件共同交集。

### 4.3 exact rank 语义

对每个 `(signal_date, component)` 独立计算：

1. 有效集合是该组中 `value` 非 null 的行，有效数为 `n`。
2. 按原值升序排名，tie 使用 average rank。
3. `n >= 2` 时：`normalized_rank = (average_rank - 1) / (n - 1)`。
4. `n < 2` 时，该日该组件的所有输出 rank 均为 null，不填 `0` 或 `0.5`。
5. `n >= 2` 且有效值全相等时，所有有效行均为 `0.5`。
6. 不得改成 dense/min/max/first/ordinal/descending rank、未归一 1-based rank、percentile bucket
   或先合成再 rank。

### 4.4 输出

输出 exact ordered columns/dtypes 为：

1. `signal_date: pl.Date`
2. `component: pl.String`
3. `symbol: pl.String`
4. `normalized_rank: pl.Float64`

输出与输入 key exact 1:1，不新增、删除或复制 key；按 `signal_date, component, symbol` 升序 canonical
排序。`normalized_rank` 可 null；非 null 值必须 finite 且在 `[0.0, 1.0]`，输出负零规范化为
Float64 `0.0`。输入行置换、tie 行置换和组件交错顺序不得改变输出 bytes-level 值与顺序。

## 5. 失败语义与 error taxonomy

任何全局合同错误在生成可消费输出前拒绝整次调用；不返回 partial frame，不降级，不修补。

| code | exception | 触发条件 |
|---|---|---|
| `CROSS_SECTIONAL_RANK_TYPE_ERROR` | `TypeError` | 输入不是 exact Polars `DataFrame` |
| `CROSS_SECTIONAL_RANK_SCHEMA_ERROR` | `ValueError` | 空 frame，列缺失/多余/乱序，dtype 不 exact，bool/数值宽化或隐式 cast |
| `CROSS_SECTIONAL_RANK_KEY_NULL` | `ValueError` | 任一 key 列为 null |
| `CROSS_SECTIONAL_RANK_DUPLICATE_KEY` | `ValueError` | `(signal_date, component, symbol)` 重复 |
| `CROSS_SECTIONAL_RANK_NON_FINITE_VALUE` | `ValueError` | 任一非 null `value` 为 NaN/Inf |
| `CROSS_SECTIONAL_RANK_INTERNAL_INVARIANT` | `RuntimeError` | 输出 key/schema/order/range/finite 不变量失效 |

局部 null 和 `n < 2` 是可预期结果，不是全局错误。错误消息必须包含上表稳定 code，
但不得泄露整份数据或不受控的 value 内容。

validation 的 stable total precedence exact 为：

```text
CROSS_SECTIONAL_RANK_TYPE_ERROR
  > CROSS_SECTIONAL_RANK_SCHEMA_ERROR
  > CROSS_SECTIONAL_RANK_KEY_NULL
  > CROSS_SECTIONAL_RANK_DUPLICATE_KEY
  > CROSS_SECTIONAL_RANK_NON_FINITE_VALUE
  > compute
  > CROSS_SECTIONAL_RANK_INTERNAL_INVARIANT
```

`>` 表示更高优先级。除 type 检查外，每个输入 validation 阶段必须在进入下一阶段前完整得出该类是否
违规；不得通过遇到的第一个行、Polars 当前输入顺序或内部遍历顺序决定外部错误。同一 frame
同时命中多类违规时，只能返回上述全序中最高优先级的单一错误；行置换、tie 置换或同类违规位置变化
不得改变该错误。只有所有输入 validation 通过后才允许 compute；只有 compute 后的公共输出不变量失效才命中
`CROSS_SECTIONAL_RANK_INTERNAL_INVARIANT`。任何失败都不得返回 partial 或 empty placeholder output。

每个公共失败表面冻结为：`exc.args == (CODE,)`且 `str(exc) == CODE`；不附加行号、symbol、component、
value、cwd、绝对/相对路径或 Polars 内部文本。实现必须阻断已验证输入上的未受控 compute/library 异常
穿透公共边界，并以 `CROSS_SECTIONAL_RANK_INTERNAL_INVARIANT` 失败；不得捕获 `BaseException`。

## 6. exact 路径、所有权与禁止集

### 6.1 当前 TASKBOOK_ONLY 阶段

唯一可写路径（actual exact1）：

1. `docs/framework/tasks/M2_SHARED_CROSS_SECTIONAL_RANK公共边界任务书.md`

除 Git 创建已批准 branch/worktree 的必要元数据外，其他路径全部只读。禁止 Python/pytest/Ruff/mypy、
data、label、runner、economic I/O、trial、network、root artifacts、stage、commit、实现派发或审查派发。

### 6.2 未来实现/审查候选 exact5

1. production：`src/quant/factors/cross_sectional_rank.py`
2. unit：`tests/unit/test_cross_sectional_rank.py`
3. integration：`tests/integration/test_shared_cross_sectional_rank_consumers.py`
4. delivery：`docs/framework/deliveries/M2_SHARED_CROSS_SECTIONAL_RANK公共边界交付报告.md`
5. review：`docs/framework/reviews/M2_SHARED_CROSS_SECTIONAL_RANK公共边界独立初验报告.md`

实现 Worker 未来只能写 1–4；未参与实现的独立 reviewer 只能写 5。taskbook 届时只读。
`__init__.py`、三个 consumer 模块/测试/任务书/报告、config、runner、Schema、data、artifacts 及其他一切路径
均禁止写入。不允许临时仓库目录、cache 或第六个业务路径；如必须扩围，立即
`CONTRACT_STOP / WRITE_SCOPE_EXPANSION_REQUIRED`。

提交策略：本 TASKBOOK_ONLY 阶段禁止 stage/commit。未来实现是否提交由统筹另行授权；Worker/reviewer
不得自行 merge/rebase。

## 7. 对抗测试与验收标准

### 7.1 unit 必须覆盖

1. `n=2` 且值不同：精确输出 `0.0, 1.0`。
2. 部分 tie：证明 average rank 与 `(rank-1)/(n-1)`的精确值，并拒绝 dense/min/max/first 等价替代。
3. 全相等 `n>=2`：全部为 `0.5`；`n=0/1` 的整组均为 null。
4. null 行保留 key 但不进入分母；同日不同 component 使用不同有效集合和 `n`。
5. 构造“先取组件交集”会改变某组件 rank 的 fixture，必须证明公共 helper 不做交集预过滤。
6. NaN/+Inf/-Inf 任一出现都全局 fail closed；不返回其他合法组的 partial result。
7. 重复 key、null key、空 frame、非 DataFrame、错 dtype、bool 冒充数值、缺/多/乱序列均命中冻结 code。
8. 多日、多 component、多 symbol 相互隔离；input/tie 行置换后 canonical 输出完全相同。
9. exact 输出列/顺序/dtypes/key 1:1/range/finite/null 与负零规范化。
10. compound-invalid：至少覆盖 schema+key-null+duplicate+non-finite、key-null+duplicate+non-finite、
    duplicate+non-finite 三种组合，分别精确命中 `CROSS_SECTIONAL_RANK_SCHEMA_ERROR`、
    `CROSS_SECTIONAL_RANK_KEY_NULL`、`CROSS_SECTIONAL_RANK_DUPLICATE_KEY`。
11. 对每个 compound-invalid frame 作多种 row permutation 和违规位置置换；每次都必须逐字断言相同的
    highest-priority `CODE`、exact `exc.args == (CODE,)`、exact `str(exc) == CODE`、不含任何路径片段，
    并证明调用没有产生可消费输出或 partial frame。

### 7.2 integration 必须覆盖

- 只通过冻结的 fully-qualified public identity import，不从 facade 或 consumer 私有 helper import。
- 分别用 R14 单组件、R15 三组件异构有效集合、R21 两组件的中立长表 fixture 验证同一 API；
  不 import 未合流 consumer 模块，不复制它们的因子公式。
- 验证组件命名不改变数学语义，且 helper 不读 sessions、universe、future return 或任何外部状态。

独立 reviewer 必须补充至少一个实现者未使用的对抗反例，优先挑战组件交集泄漏、tie 分母、
非有限值 partial return、duplicate key 或行置换稳定性。审查问题按“现象—根因—应遵循规则—
最小复现—新增测试—通过条件”报告。

## 8. 未来验证阶段（本轮不执行）

仅在统筹后续明确派发并授权 Windows 开发反馈环后，按首失败停止：

1. fresh identity/scope：HEAD exact base/branch/worktree、候选 exact5、无额外路径、cached0。
2. focused unit：`D:\Miniforge3\python.exe -m pytest tests/unit/test_cross_sectional_rank.py -q -p no:cacheprovider`。
3. focused integration：`D:\Miniforge3\python.exe -m pytest tests/integration/test_shared_cross_sectional_rank_consumers.py -q -p no:cacheprovider`。
4. Ruff：只检查 production/unit/integration 三路径。
5. mypy：只检查 `src/quant/factors/cross_sectional_rank.py`，cache 必须指向统筹批准的 worktree-contained temp。
6. cold import/public identity：只 import 冻结 module/function，禁止 data/repository/runner/label/economic/trial/network 调用。
7. final scope/text hygiene：重算 bytes/SHA，验证 UTF-8 no BOM、LF-only、CR0、NUL0、trailing whitespace 0、
   single EOF LF，并记录 actual exact5/cached0/针对 untracked 文件不空洞的 whitespace 检查。

实现交付完成后必须由未参与实现的独立上下文初验。独立 review PASS 与 Windows 开发验证
都是申请合流的必要条件，但都不是 Linux/WSL Gate，不得写成因子有效、项目 Gate 或跨平台
终验已通过。Linux/WSL Miniforge `base` 的平台终验只能由统筹在合流候选上另行授权。

## 9. consumer 迁移与合流顺序

公共 helper 不从三个 research worktree 复制代码，也不在本 branch 修改 consumer。顺序必须串行：

1. 公共 helper 实现、定向自测、独立 review、Windows 开发验证均完成。
2. 统筹基于 fresh integration 执行 merge-tree/no-ff 与必要回归，得到唯一 merged public SHA。
3. R14 另建独立迁移任务，基于该 merged public SHA；仅用公共 identity 替代私有
   `_with_cross_section_ranks`，保留 R14 因子公式、时序 rank 和所有因子特有测试。独立审查后再合流。
4. R15 另建独立迁移任务，基于当时 latest integration 中同一 public identity；仅替换私有
   `_with_component_rank`，必须保持三组件独立有效集合和最终公式不变。独立审查后再合流。
5. R21 最后由投研经理基于已合流 public identity 重新冻结实现准入；不得重用旧 taskbook 中的
   private-helper 分支，也不得从 R14/R15 worktree import/copy。

任一 consumer 迁移都必须在自己的 branch/worktree/taskbook 内完成，要求迁移前后金标 fixture 结果等价、
无私有副本、无 fallback，且只绑定已合流的 public SHA。不得让 consumer 指向本 worktree 的 unmerged bytes。

## 10. STOP 条件与交付要求

遇到以下任一情况立即 STOP：base/branch/worktree/所有权漂移；候选路径已被其他 writer 占用；
需要改公共输入/输出合同；需要新依赖、Schema/facade/config/runner/data/artifacts；发现三个 consumer 数学语义
并不等价；或验证意外命中真实 I/O/网络/trial/economic path。

未来交付报告必须记录：修改文件及目的；标准—证据映射；每条验证命令的实际 exit/result；
输入、非有限值、duplicate key、tie、`n<2`、全相等、组件独立集合和 deterministic order 证据；
bytes/SHA/text hygiene/actual exact scope/cached0/diff-check；未验证风险；以及 Windows 开发验证不等于
Linux Gate 的证据边界。

本任务书完成只表示公共合同已冻结且可供统筹后续派发；不表示实现、review、runtime validation、
merge 或任何 consumer 迁移已完成。
