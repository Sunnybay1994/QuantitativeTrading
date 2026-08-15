# M2-FWD-R1：标准前向目标 Research Run 任务单

日期：2026-08-16（Asia/Shanghai）

状态：设计、实现与正常开发检查完成；7 路径唯一安全提交已形成；待 integration 吸收；真实 2026-08-31 发布仍未授权

Owner：框架开发 session（主 Agent）

执行模式：外部 Agent 暂停；不另设独立初验

## 1. 目标与非目标

### 1.1 目标

把现有自定义 `m2-forward-target-observation-v1` 发布路径收束为一个标准、不可覆盖、可 fresh 验证的
`LightweightResearchRunV1`：

1. fresh 验证 canonical M2-SOURCE-R10 run；
2. 将 verified source run、其 source config、末折选择参数和当前 forward config 精确绑定；
3. 只通过 `quant.data` 的窄只读 repository 获取前向价格和 SH/SZ 日历；
4. repository 自行生成 canonical source receipt 原始字节，runner 不接受 caller 注入的 frame、receipt、
   config mapping 或 loader；
5. 生成 `target_weights.parquet`、`scheduled_targets.parquet`、`source_binding.json` 和
   `source_data_receipt.json`；
6. 唯一复用现有 `publish_lightweight_research_run` 发布，结论最高为 `RESEARCH_ONLY`。

### 1.2 明确非目标

- 不生成或升级 `PAPER_CANDIDATE`，不启动 PAPER、OMS、账户、Gateway 或订单。
- 不实现新的撮合、收益模拟、准入引擎或第二套 artifact publisher。
- 不修改 source R10、历史 run、`lightweight_run.py`、任何 `__init__.py`、路线图、README 或共享 SSOT。
- 不把 source run 的历史经济指标冒充本次前向观察的已实现收益、Sharpe 或回撤。
- 不运行真实 2026-08-31 发布；本任务先完成实现与正常开发检查，真实发布仍需单独授权。
- PIT first-run prerequisite 只是 CPU 8–11 的调度优先项，不是 FWD-R1 的业务或数据前置；
  FWD-R1 不依赖 financial snapshot 或 PIT READY。统筹明确释放前，本工作树仅允许
  7 路径内的静态编辑，不得提前检查或发布。

## 2. 权威基线与 source identity

- exact base：`121b672e99a905c38d993b7f6d07687e3371597c`
- branch：`codex/m2-forward-r1`
- worktree：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-forward-r1`
- canonical source run id：
  `e43da184f942286ae7e8b79aa25bc540f692cb467821003ce193c9d35fb7a96f`
- source run config：`configs/research/m2_s2_volatility_target.toml`
- source config 物理 SHA-256：
  `fd2ce82c4c3772752f383c7eb4439f1b89ee46d0272be4ce369eca84fbfaa9bf`
- source conclusion：`RESEARCH_ONLY`
- source 末折：fold 2，`top_k=2`、`regression_window=60`
- forward config：`configs/research/m2_s2_volatility_target_forward.toml`

M2-SOURCE-R10 是 FWD-R1 的唯一业务前置，且已以上述 canonical run 和 public fresh verify
证据关闭。PIT first-run、financial snapshot 和 PIT READY 不进入本任务的 source identity、
target 计算或 publication 闭包。

forward config 的 `candidate_source_*` 三字段只描述 verified source run 及其 source config。forward config
自身的 SHA-256 由 runner 对其原始字节计算并写入新 run；配置中禁止新增 forward config 自身 hash 字段，
避免自哈希循环。

## 3. 唯一文件白名单

仅允许修改或新增以下 7 个路径：

1. `src/quant/data/m2_forward_source_repository.py`（新增）
2. `src/quant/research/run_s2_forward_observation.py`
3. `tests/unit/test_m2_forward_source_repository.py`（新增）
4. `tests/unit/test_m2_forward_observation.py`
5. `configs/research/m2_s2_volatility_target_forward.toml`
6. `docs/agent/M2_FWD_R1_标准前向目标ResearchRun任务单.md`
7. `docs/agent/M2_FWD_R1_标准前向目标ResearchRun交付报告.md`

禁止 `git add -A`；禁止修改任何 `__init__.py`、`lightweight_run.py`、roadmap、README、用户事项或根
canonical artifact。

## 4. 数据 repository 公共合同

新增 API：

```python
class M2ForwardSourceError(ValueError):
    # message exact: M2_FORWARD_SOURCE_INVALID
    ...

@dataclass(frozen=True, slots=True)
class M2ForwardSourceSlice:
    prices: pl.DataFrame
    calendars: pl.DataFrame
    source_snapshot_id: str
    source_receipt: bytes

class M2ForwardSourceLoader(Protocol):
    def __call__(
        self,
        *,
        data_root: Path,
        candidate_symbols: tuple[str, ...],
        data_start: date,
        as_of: date,
    ) -> M2ForwardSourceSlice: ...

def load_m2_forward_source_slice(
    *,
    data_root: Path,
    candidate_symbols: tuple[str, ...],
    data_start: date,
    as_of: date,
) -> M2ForwardSourceSlice: ...
```

生产 runner 必须直接调用模块函数；Protocol 仅用于类型边界，不能成为 production dependency injection
入口。repository 只能读取：

- `clean/research_price_1d/date=YYYY-MM-DD/data.parquet`
- `clean/trade_calendar/market=SH/data.parquet`
- `clean/trade_calendar/market=SZ/data.parquet`

只选择 `[data_start, as_of]` 的价格分区、冻结候选、`TOTAL_RETURN_DIVIDEND` 价格及覆盖完整信号月份和
下一共同开市日所需的 SH/SZ 日历。路径、父目录和文件必须拒绝 symlink、junction/reparse、非普通实体、
硬链接及同 inode alias；所选 inventory、文件 stat 和目录 stat 在读取前后必须稳定。Parquet 必须从同一组
stable-open 原始字节解析。repository 不得 mkdir、写文件、联网或遍历 `data/legacy/`。任何异常统一为
`M2_FORWARD_SOURCE_INVALID`，`cause/context` 不泄露路径或底层异常。

## 5. canonical source receipt

`source_data_receipt.json` 的原始字节由 repository 内部生成，runner 必须原样写入，不得 decode 后重编码。
exact schema：

```json
{
  "schema_version": "m2-forward-source-receipt-v1",
  "source_snapshot_id": "<hex64>",
  "query": {
    "adjustment_method": "TOTAL_RETURN_DIVIDEND",
    "as_of": "YYYY-MM-DD",
    "calendar_markets": ["SH", "SZ"],
    "candidate_symbols": ["<sorted unique symbols>"],
    "data_start": "YYYY-MM-DD"
  },
  "files": [
    {
      "relative_path": "clean/.../data.parquet",
      "sha256": "<hex64>",
      "size_bytes": 123
    }
  ],
  "logical_inputs": [
    {
      "content_sha256": "<hex64>",
      "max_date": "YYYY-MM-DD",
      "min_date": "YYYY-MM-DD",
      "name": "calendars",
      "rows": 1
    },
    {
      "content_sha256": "<hex64>",
      "max_date": "YYYY-MM-DD",
      "min_date": "YYYY-MM-DD",
      "name": "research-prices",
      "rows": 1
    }
  ]
}
```

`files` 按 `relative_path` 排序；路径相对 `data_root`，禁止绝对路径。`logical_inputs` 按 `name` 排序，摘要
算法必须与 `dataframe_input_digest` 精确一致。codec 为 UTF-8、`ensure_ascii=False`、键排序、无空白、
`allow_nan=False`、日期 ISO、无 BOM/换行。

先构造不含 `source_snapshot_id` 的 body，再计算：

```text
source_snapshot_id = SHA256(
  canonical_json_bytes(["m2-forward-source-snapshot-id-v1", body])
)
```

最终 receipt 为 `{"source_snapshot_id": id, **body}` 的 canonical 原始字节。

## 6. runner 公共合同与 fresh 顺序

替换旧 direct-frame API：

```python
class M2ForwardObservationError(ValueError):
    # message exact: M2_FORWARD_OBSERVATION_INVALID
    ...

def publish_forward_research_run(
    *,
    project_root: Path,
    artifact_root: Path,
    config_path: Path,
    source_run_root: Path,
    data_root: Path,
    as_of: date,
) -> tuple[Path, LightweightResearchRunV1, bool]: ...
```

CLI 新增必填 `--source-run-root`；默认 config 改为 volatility-target forward config。公共入口不接受裸
DataFrame、config mapping、receipt、source run object、loader 或 caller-computed digest。

artifact parent 创建前必须依次完成：

1. exact scalar/path 校验，stable 读取并 exact parse forward config；
2. public `verify_lightweight_research_run` fresh 验 source；
3. stable 读取 source `run.json`、`report.json` 和 source config 原始字节；
4. 校验 source run id、`RESEARCH_ONLY`、source config path/物理 SHA、hypothesis、strategy、universe、
   candidate symbols、三种 timing 与 forward config exact 一致；
5. report 必须 canonical unique-key JSON，descriptor size/SHA 匹配；最后一折选择参数必须 exact 为
   `top_k=2`、`regression_window=60`；
6. 调 repository 获取唯一 source slice/receipt；
7. 校验 Schema、每个候选在 as_of 的价格和最小历史、完整双市场月份、no leverage、以及 as_of 后首个
   SH/SZ 共同开市日；
8. 构造所有 payload、inputs、binding 和待发布 run；
9. 第二次 public fresh verify source，并要求 verified object、run/report/source-config 原始字节均未漂移；
   同时第二次执行 repository stable load，要求 snapshot id、receipt 原始字节及两张逻辑 frame 与首次 exact
   相等；
10. 最后且仅最后调用 `publish_lightweight_research_run`。

任何 source、report、config 或 data 漂移必须在 artifact 目录创建前 fail closed。公共异常统一为
`M2_FORWARD_OBSERVATION_INVALID`，不得泄露底层异常、路径或 caller hostile `repr`。

## 7. 标准 run 与输出合同

新 run 的 source lineage 字段（hypothesis、strategy、universe、candidate symbols、timing、random seed）
来自 verified source，并要求 forward config 与其 exact 一致。其余字段：

- `conclusion="RESEARCH_ONLY"`；
- `config_relative_path/config_sha256` 指 forward config 及其原始字节；
- `data_start` 为 forward warmup 起点，`data_end=as_of`；
- `folds/cost_multipliers/selection_metric` 继承 verified source，仅表达 source lineage；
- caveat 明确 source folds/metrics 不是本次 forward realized evaluation；
- `aggregate_metrics` 只允许当前事实，按名字排序：
  `forward_execution_session_count`、`forward_positive_symbol_count`、
  `forward_target_count`、`forward_target_weight_sum`；禁止 return/Sharpe/drawdown。

`inputs` 按名称排序且 exact 为：

1. `calendars`（receipt 逻辑摘要，runner 用 `dataframe_input_digest` 重算相等）
2. `research-prices`（同上）
3. `source-config`（rows=1，date null，raw source config SHA）
4. `source-data-receipt`（raw receipt SHA）
5. `source-report`（raw report SHA）
6. `source-run-manifest`（raw run.json SHA）

output payload exact 4 项：

- `target_weights.parquet`
- `scheduled_targets.parquet`
- `source_binding.json`
- `source_data_receipt.json`

`source_binding.json` exact fields：

```text
schema_version=m2-forward-source-binding-v1
source_run_id
source_run_manifest_sha256
source_report_relative_path=report.json
source_report_sha256
source_config_relative_path
source_config_sha256
source_conclusion
source_selection_metric
source_last_fold
source_selected_parameters={regression_window,top_k}
forward_as_of
source_snapshot_id
source_data_receipt_sha256
```

target 必须通过 `TargetWeightSchema`、五列 canonical 排序、单一 identity、weight sum `<=1` 且不加杠杆；
scheduled target 必须为 `execution_date` 加同五列，drop execution_date 后与 target exact 相等，且唯一
execution date 是 as_of 后首个 SH/SZ 共同 verified open session。

## 8. 测试与反例

repository 定向测试至少覆盖：

- canonical receipt/id/raw-byte roundtrip 与 logical digest 交叉复算；
- reparse/symlink、hardlink/same-inode alias、非普通文件；
- scan/read 后 mutation、inventory drift；
- 非 canonical candidates/date、覆盖不足；
- stable error、zero writes。

runner 定向测试至少覆盖：

- R10-like source happy path，首次 `reused=false`、在 source 原始字节完全不变时再次执行为
  `reused=true`，public verifier 通过；逻辑摘要本身与行序无关，但 Parquet 原始字节漂移必须产生新的
  source snapshot identity，不能错误复用旧 run；
- exact 四项 output、source binding、receipt raw bytes、targets/schedule、RESEARCH_ONLY、无 return metrics；
- source run id、source config physical SHA、source report selected parameters 任一错配；
- 第二次 source verify 或 run/report/config bytes 漂移；
- pre-freeze、非完整双市场月末、候选缺 as_of、无下一共同开市日；
- forward config 合法变化只改变 forward run id，不改变 source-config 绑定语义；
- 所有 publication 前反例均要求 artifact parent 不存在。

## 9. 资源、验证与运行边界

CPU 8–11 已在 PIT first-run prerequisite 通过并退休后明确释放给 FWD-R1。该先后只是资源调度顺序，
不是业务依赖。本轮只执行模拟/fixture 和 pre-artifact 失败语义检查，仍禁止：

- Python 或 pytest；
- Ruff、mypy、formatter、cold import；
- 真实 repository load 或 artifact publish。

检查已严格单实例、`BelowNormal`、affinity `0xF00`、数值线程 `<=2`，按 focused pytest →
Ruff → mypy → cold import 顺序完成；未与其他 0xF00 进程并发。具体证据见交付报告。

## 10. 停止条件与交付

任一条件命中立即停止扩大动作：

- worktree/branch/HEAD 漂移或白名单外修改；
- 需要修改 `lightweight_run.py`、Schema、`__init__.py`、roadmap/README/shared SSOT；
- source run、config、report 或 source data 无法通过上述 fresh/稳定/identity 闭包；
- 需要接受 caller frame/receipt/digest/verified source object；
- 只能通过自建第二套 publisher、撮合或收益模拟完成；
- artifact 目录在任一前置失败后已被创建；
- conclusion 可能升为 `PAPER_CANDIDATE` 或产生订单/账户 I/O；
- CPU 槽未释放却需要运行 Python 或真实 publish。

交付报告固定为 `docs/agent/M2_FWD_R1_标准前向目标ResearchRun交付报告.md`，只记录 exact diff、开发检查、
未运行的真实边界和剩余风险；不声明 FWD 实际观察、PAPER 准入或任何更高 Gate 已通过。

本工作树只有在以下退出条件全部满足后才可由统筹退休：

1. 7 个白名单路径经 focused pytest、定向 Ruff/mypy、cold import 和 final diff 检查后，
   形成唯一安全提交；
2. 开发检查期间不生成或保留真实 2026-08-31 artifact，publisher 临时目录归零；
3. 该提交被 integration 显式吸收，且 ancestor/组合回归证据闭合；
4. Owner（框架开发 session，主 Agent）明确释放现场，统筹确认分支保留或归档策略；
5. worktree tracked/untracked 干净，无活跃进程、无临时目录、无 ignored 正式产物。
