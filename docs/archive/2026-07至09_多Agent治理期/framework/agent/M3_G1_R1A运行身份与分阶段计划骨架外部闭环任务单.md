# M3 G1-R1A 运行身份与分阶段计划骨架外部闭环任务单

日期：2026-07-15  
状态：**外部实现—独立复验闭环完成，主 Agent 最终验收通过**  
任务性质：纯函数骨架；无网络、无生产数据写入、无 release 发布  
执行模型：非 fast `cursor-grok-4.5-high`

## 1. 目的

P4A–P4C 已提供“已取得全部输入后”的 candidate、跨源对账和 release 合同，但项目还没有一个唯一入口把
C0 配置、运行时代码/依赖身份、index-weight 阶段和 history 阶段组合成可恢复的 G1 执行计划。

R1A 只实现两个确定性边界：

1. 从项目源码和实际 base 依赖生成 G1 运行身份；
2. 从 `LoadedM3Config` 生成静态计划，再从已验真的 index-weight responses 派生唯一 history 计划。

R1A 不调用 Tushare/BaoStock、不读 token、不执行 batch、不写 journal/raw/release、不实现 CLI。通过只表示
编排骨架合同完成，不表示 R1B、B4、G1 或 Gate 通过。

## 2. 前置与 SSOT

- 必须等待 [`M3_G1_R0权威日历补全与真实源烟测外部闭环任务单.md`](M3_G1_R0权威日历补全与真实源烟测外部闭环任务单.md)
  通过主 Agent 终验后启动。
- 行为、环境、凭据和职责分离：[`../AGENTS.md`](../../../../../AGENTS.md)。
- 配置与 hash：`src/quant/research/m3/config.py`。
- 请求计划与 raw receipt：`src/quant/data/m3_backfill.py`。
- PIT 成员：`src/quant/data/index_membership.py`。
- G1 build/cross-source 固定版本：`src/quant/data/m3_g1_candidate.py`、
  `src/quant/data/m3_execution_facts.py`、`src/quant/data/m3_reference.py`。
- G1 取数口径：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.10、§6.4。

## 3. 文件白名单

```text
src/quant/research/m3/g1_planning.py
src/quant/research/m3/__init__.py              # 只导出本包公共接口
tests/unit/test_m3_g1_planning.py
docs/M3_G1_R1A运行身份与分阶段计划骨架交付报告.md
docs/M3_G1_R1A运行身份与分阶段计划骨架独立初验报告.md  # 初验 Agent 专属
```

不得修改 data 层既有合同、C0、配置示例、路线图、raw/clean/artifacts 或依赖。若现有常量未公开，R1A 在
本模块定义下列唯一编排版本，不得为修改上游文件扩大范围。

## 4. 冻结公共接口

```python
@dataclass(frozen=True)
class G1DependencyVersionV1:
    distribution: str
    version: str

@dataclass(frozen=True)
class G1SourceDigestV1:
    relative_path: str
    sha256: str

@dataclass(frozen=True)
class G1RuntimeIdentityV1:
    schema_version: Literal["m3-g1-runtime-identity-v1"]
    code_version: str
    source_tree_sha256: str
    source_files: tuple[G1SourceDigestV1, ...]
    pyproject_sha256: str
    python_implementation: str
    python_version: str
    sys_platform: str
    machine: str
    kernel_release: str
    dependencies: tuple[G1DependencyVersionV1, ...]
    dependency_fingerprint_sha256: str

@dataclass(frozen=True)
class G1StaticPlanV1:
    schema_version: Literal["m3-g1-static-plan-v1"]
    config_version: str
    g1_config_sha256: str
    runtime: G1RuntimeIdentityV1
    signal_start: dt.date
    signal_end: dt.date
    universe: Literal["CSI300_TUSHARE_MONTHLY_OBSERVED_PIT_V1"]
    benchmark: Literal["H00300.CSI"]
    index_code: Literal["000300.SH"]
    index_weight_batch: TushareRequestBatch
    endpoint_policies: tuple[tuple[str, EndpointPolicy], ...]
    request_rate_per_minute: int
    max_attempts: int
    retry_base_seconds: float
    feature_warmup_sessions: int
    label_tail_sessions: int
    expected_constituent_count: Literal[300]
    factor_ratio_rtol: float
    build_spec: G1BuildSpec
    cross_source_policy: G1CrossSourcePolicy

@dataclass(frozen=True)
class G1DerivedHistoryPlanV1:
    schema_version: Literal["m3-g1-derived-history-plan-v1"]
    static_plan_sha256: str
    observations_sha256: str
    membership_sha256: str
    eligible_keys_sha256: str
    history_symbols: tuple[str, ...]
    history: HistoryWindow
    request_plan: G1RequestPlan
    derived_plan_sha256: str

class M3G1PlanningError(ValueError):
    code: Literal[
        "G1_PLANNING_INPUT_INVALID",
        "G1_PLANNING_PROJECT_ROOT_INVALID",
        "G1_PLANNING_SOURCE_TREE_INVALID",
        "G1_PLANNING_DEPENDENCY_INVALID",
        "G1_PLANNING_CONFIG_INVALID",
        "G1_PLANNING_CALENDAR_INVALID",
        "G1_PLANNING_MEMBERSHIP_INVALID",
        "G1_PLANNING_IDENTITY_MISMATCH",
    ]

def compute_g1_runtime_identity(*, project_root: Path) -> G1RuntimeIdentityV1: ...

def build_g1_static_plan(
    *, config: LoadedM3Config, project_root: Path,
) -> G1StaticPlanV1: ...

def derive_g1_history_plan(
    *, config: LoadedM3Config, project_root: Path,
    static_plan: G1StaticPlanV1,
    index_responses: Sequence[VerifiedRawResponse],
    calendars: pl.DataFrame,
    instruments: pl.DataFrame,
) -> G1DerivedHistoryPlanV1: ...
```

所有 dataclass 必须 exact-type、自证、冻结、排序；嵌套对象必须重建。所有 digest 是裸 64 位小写 hex。
`M3G1PlanningError.__str__` 仅等于 code，`repr/cause/traceback` 不得泄露绝对路径、依赖对象 repr 或配置值。

## 5. G1 运行身份

### 5.1 受控根与源码集合

`project_root` 必须是已存在的真实目录，入口和退出时从其父目录到文件系统根均不得出现 symlink，且根目录
物理 identity 不得变化。函数只读：

- `pyproject.toml`；
- `src/quant/**/*.py` 下所有普通文件。

集合至少一项，按 POSIX 相对路径字节序排序；拒绝 symlink、非普通文件、重复规范路径、路径逃逸和读取期间
大小/mtime/inode 变化。不得读取 `configs/tushare.local.toml`、`.git`、`data`、`artifacts`、`_old`、
`__pycache__` 或任何配置文件。M3 配置已由 C0 selector 单独进入 build identity，不能再被全文件 hash 污染。

每个 `G1SourceDigestV1.sha256 = SHA256(file bytes)`。`source_tree_sha256` 固定为规范 JSON：

```json
{
  "schema_version":"m3-g1-source-tree-v1",
  "files":[{"relative_path":"...","sha256":"..."}]
}
```

`code_version = "m3-g1-code-v1-" + source_tree_sha256`。不得用时间戳、Git dirty 文本、绝对路径或固定
`unavailable`。当前没有 Git 元数据，R1A 不探测 Git。

### 5.2 依赖集合和 fingerprint

固定、唯一、有序 distribution 集合：

```text
baostock
numpy
pandas
pandera
polars
pyarrow
tushare
```

名称按上表字典序保存；版本由 `importlib.metadata.version()` 读取。任一缺失、空白、含控制字符或无法解析，
抛 `G1_PLANNING_DEPENDENCY_INVALID`，不写 `NOT_INSTALLED` 后继续正式 G1。不得 import SDK 以取版本。

`python_version` 精确 `major.minor.micro`；implementation、`sys.platform`、`platform.machine()`、
`platform.release()` 必须是非空稳定字符串。`pyproject_sha256` 是原始 bytes hash。

`dependency_fingerprint_sha256` 固定为：

```json
{
  "schema_version":"m3-g1-dependency-fingerprint-v1",
  "pyproject_sha256":"...",
  "python":{"implementation":"...","version":"..."},
  "platform":{"sys_platform":"...","machine":"...","kernel_release":"..."},
  "dependencies":[{"distribution":"...","version":"..."}]
}
```

规范 JSON 使用 UTF-8、键排序、紧凑 separators、`allow_nan=False`。

## 6. 静态计划

`build_g1_static_plan` 必须重建并校验 `LoadedM3Config` 九个 identity；禁止信任调用者用 `replace` 伪造的
hash。只消费公开 `section()` 返回的冻结值，不读取 TOML。它必须用同一 `project_root` 内部调用
`compute_g1_runtime_identity`，不接受调用者自报 runtime。

编排版本固定为：

```text
mapper_version                         = m3-g1-mapper-v1
schema_version                         = m3-g1-schema-v1
build_code_version                     = runtime.code_version
membership_method_version              = 配置唯一 literal
price_limit_method_version             = G1_PRICE_LIMIT_METHOD_VERSION
corporate_action_selection_version     = G1_CORPORATE_ACTION_SELECTION_VERSION
corporate_action_reconciliation_version= G1_CORPORATE_ACTION_RECONCILIATION_VERSION
```

其余值只从 C0 document 取得；不得复制示例数值作为默认。`meta.enabled=false` 允许生成纯计划，不能在 R1A
改为 true。

`index_weight_batch` 只调用 `plan_index_weight_requests`。endpoint policy 必须覆盖七个且按 endpoint 排序：

- `index_weight/daily/adj_factor/index_daily/stk_limit`：`empty_response="REJECT"`；
- `suspend_d/dividend`：`empty_response="ALLOW"`；
- row limit 逐项来自 C0 `g1_backfill.endpoint_row_limits`。

`G1CrossSourcePolicy` 逐项来自 `g1_backfill.reconciliation`，reference source 必须为 `baostock`。
`G1BuildSpec.g1_config_sha256` 必须等于公开 loader 的 G1 selector；dependency hash 来自重建后的 runtime。

`G1StaticPlanV1` 自证时必须重建其 `runtime`，证明 `build_spec.build_code_version` 与
`dependency_fingerprint_sha256` 分别等于 runtime 的两个对应字段，并从自身字段重算 index batch、build
spec/cross-source policy 的全部固定闭包，禁止只检查 digest 格式。static plan 的规范 digest不作为字段
保存，但 `derive_g1_history_plan` 计算
`static_plan_sha256` 时使用 schema `m3-g1-static-plan-identity-v1` 和全部逻辑字段；不得包含依赖可变 repr。

## 7. 动态 history 计划

执行顺序固定：

1. 从传入的 `config/project_root` 重新调用 `build_g1_static_plan`，要求与传入 static plan 精确相等；不得只重建
   static dataclass 后信任一套整体伪造的自洽值；
2. 对 `index_responses` 重建 `VerifiedRawResponse` 并要求与 index batch request multiset 精确闭包；
3. 只调用 `normalize_index_weight_observations`、`build_observed_membership`、
   `verify_observed_membership_result`，不得复制成员算法；
4. calendars/instruments 先经权威 Schema 验证。calendar 必须同时含 SH/SZ，两个市场自然日期域和
   `is_open` 逐日完全一致；只从 `market="SH" and is_open=true` 派生严格唯一 session 向量，但完整两市场
   frame 传给既有 PIT builder。自然日表必须完整覆盖 observation 生效、signal 边界、warmup 和 tail；
5. history symbols 是全部 observation 中 A 股证券的严格排序唯一并集，不能只取 signal start/end 当日成员；
6. 只调用 `resolve_history_window` 和 `plan_history_requests`；
7. 返回 observations/membership/eligible digest 必须等于已验真 result，request plan 必须绑定 static index
   batch、全历史并集、基准与 history window；
8. `derived_plan_sha256` 对除自身外的所有字段做规范 JSON hash，schema 固定
   `m3-g1-derived-history-plan-identity-v1`。

函数全程无网络、时钟、随机数、环境变量和文件写入。输入顺序变化不得改变结果。少/多/重复 response、
非 SH signal 边界、日历缺 warmup/tail、未知证券、伪造 receipt/frame/digest 都 fail-closed。

## 8. 测试要求

必须从既有真实 C0 示例和既有 G1 fixture 构造，不复制第二份完整配置。至少覆盖：

1. runtime identity 两次运行稳定；修改任一临时源码 bytes 改变 source/code identity，但不改变 dependency
   fingerprint；修改 mock 依赖版本只改变 dependency fingerprint；
2. source symlink、根 symlink、文件增删/替换/TOCTOU、空源码集合、缺 pyproject、路径逃逸；
3. runtime dataclass 传入 list/dict、bool/int 混淆、乱序/重复依赖、伪造任一 digest；
4. config 九 identity 任一伪造、未知/缺 endpoint policy、empty policy 反转、冻结版本漂移；
5. index responses 乱序结果相同；少一、多一、重复、frame/receipt/spec 漂移均失败；
6. history 使用 observation 历史并集，构造“已调出证券不在结束日成员但仍必须抓历史”的反例；
7. SH 日历恰好缺第 60 个 warmup 或第 10 个 tail、signal 边界标记闭市、缺 SZ 日期或沪深某日
   `is_open` 不一致；
8. 所有公开异常无绝对路径、cause/traceback 敏感内容；
9. monkeypatch socket、RawStore write、connector 方法、Path 写方法，证明两个 builder 零网络零写入。

验证：

```bash
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q \
  tests/unit/test_m3_g1_planning.py tests/unit/test_m3_config.py \
  tests/unit/test_m3_backfill_requests.py tests/unit/test_index_membership.py
/home/mabw/miniforge3/bin/conda run -n base python -m pytest -q
/home/mabw/miniforge3/bin/conda run -n base python -m ruff check src tests
/home/mabw/miniforge3/bin/conda run -n base python -m mypy src
```

## 9. 独立初验

全新 `cursor-grok-4.5-high` 会话只读生产代码和实现者测试，只允许写初验报告。必须逐项映射合同，并新增
至少以下未公开对抗：

1. source 文件在 hash 完成后、函数返回前被同大小 inode 替换；
2. 伪造一个自洽但不等于 C0 重算值的 `LoadedM3Config`；
3. index response 集整体替换为另一套 request/receipt/frame 自洽对象；
4. observation 中加入早期已调出证券，证明 history union 不退化为结束日截面；
5. runtime dependency tuple 用大小写别名或 Unicode 控制字符碰撞。

不通过时必须按“现象—根因—应遵循规则—最小复现—新增测试—通过条件”返回原实现 Agent。独立初验
通过仍只进入主 Agent 终验，不关闭任何 Gate。

## 10. 与 R1L 的两路并行执行屏障

R0 主验后，R1A 允许与 R1L 同时由两个全新的 `cursor-grok-4.5-high` 实现会话执行，因为两包生产代码、
测试和交付报告白名单互斥。并行模式必须遵循：

1. R1A 完成自身全部文件写入和定向测试后，在自身交付报告写入精确标记
   `PARALLEL_BARRIER_READY: R1A`；写入该标记后不得再修改生产代码或实现者测试。
2. 只读等待 R1L 交付报告出现 `PARALLEL_BARRIER_READY: R1L`；不得读取 R1L 未冻结的中间源码来调整本包。
3. 双方标记齐全后，才运行全量 pytest、Ruff、mypy。为避免两个重检查争抢资源，三项命令整体必须在 WSL
   `flock /tmp/quant-m3-r1-validation.lock` 下串行执行；协调 lock 不进入项目、不承载业务状态，但任何会话均
   不得 unlink，避免旧 inode 持锁时创建新 inode 形成 split-brain。静态文件可留在 `/tmp`，后续只复用 flock。
4. 全量验证完成后补齐报告并改为“待独立初验”。任一方在屏障前失败，另一方保持待合流状态，由主 Agent
   处理失败包；不得把对端未完成写成自己的通过。

两个实现会话都退出且报告完整后，R1A 与 R1L 的两个全新独立初验会话才可并行启动；初验同样使用上述
临时 `flock` 串行运行重检查，并且只写各自互斥的初验报告。
