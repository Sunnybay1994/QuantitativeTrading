# M3 G1 L0A + B1 + B2B 核心映射外部闭环任务单

日期：2026-07-13  
状态：**待外部实现 Agent 执行**  
任务包：`G1-P1`  
主设计 SSOT：[`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §4.1、§4.10  
总任务：[`M3_G1数据实现与初验任务单.md`](../archive/M3_G1数据实现与初验任务单.md)  
B2A 前置验收：[`M3_G1_B2A主Agent最终验收报告.md`](M3_G1_B2A主Agent最终验收报告.md)

## 1. 为什么组成一个包

本包关闭一条最小纵向链：

```text
Tushare 七个 raw endpoint
  -> B2A VerifiedRawResponse（已主验通过）
  -> 四张 G1 核心标准映射表
  -> readiness 正确区分股票与全收益基准
```

L0 标签和 B1 endpoint 已有初版，当前主要缺口是 readiness 仍把基准当股票、B1 尚未独立闭环，以及
B2B 核心 mapper 尚未实现。三者一起交付可以验证真实接口边界，又不把 B3 PIT、B2C 公司行动/涨跌停、
B4 全局审计与 release 混入同一轮。

## 2. 外部实现—复验闭环

执行方必须组织以下两个不同角色：

1. **外部实现 Agent**：按本任务书实现、自测并写交付报告，不宣称主验/G1/Gate 通过。
2. **外部独立验收 Agent**：未参与本包编码，只读核对并增加未公开反例。若不通过，把结构化返工清单
   退回实现 Agent；实现—复验迭代到独立验收通过后再交主 Agent。

不得由实现者给自己的自测改名为独立验收。返工问题必须写明“现象—根因—应遵循规则—最小复现—
新增测试—通过条件”，报告保留历史并互相链接。

报告名：

- 实现：`docs/M3_G1_L0A_B1_B2B核心映射交付报告.md`
- 独立验收：`docs/M3_G1_L0A_B1_B2B核心映射独立初验报告.md`
- 若返工，在文件名加入“一次返工/二次返工”，不得覆盖旧报告。

## 3. 开始前必读

实现和验收 Agent 均须完整阅读：

1. 根 [`../AGENTS.md`](../../AGENTS.md)；
2. [`../karpathy-guidelines.md`](../../karpathy-guidelines.md)；
3. [`M3实施与Agent交接.md`](../M3实施与Agent交接.md) §2.2、§4.1、§4.3、§4.10、§7；
4. [`M3_G1数据实现与初验任务单.md`](../archive/M3_G1数据实现与初验任务单.md) L0A、B1、B2；
5. [`M3_G1设计审查与修订记录.md`](M3_G1设计审查与修订记录.md)；
6. [`M3_G1_B2A主Agent最终验收报告.md`](M3_G1_B2A主Agent最终验收报告.md)。

不得读取 `_old/`，不得读取或输出 `configs/tushare.local.toml`，不得联网。所有 Python、pytest、Ruff、
mypy 只在 WSL Miniforge `base` 执行。

## 4. 文件范围

允许修改：

```text
src/quant/research/m3/readiness.py
src/quant/data/connectors/tushare.py          # 仅 B1 契约缺口；现有正确逻辑不重写
src/quant/data/m3_mappers.py                  # 新建
src/quant/domain/schemas.py                   # 仅 Suspension1dSchema
src/quant/domain/__init__.py                  # 仅导出 Suspension1dSchema
tests/unit/test_m3_readiness.py
tests/unit/test_tushare_connector.py
tests/unit/test_m3_g1_mappers.py              # 新建
docs/M3_G1_L0A_B1_B2B核心映射交付报告.md
```

除测试构造 helper 外，禁止修改已经主验通过的 `src/quant/data/m3_backfill.py` 和
`tests/unit/test_m3_backfill_requests.py`。若发现 `VerifiedRawResponse/TUSHARE_FIELDS` 的真实契约缺陷，
停止扩大实现并在报告给出最小证据，由主 Agent 决定是否重开 B2A。

禁止修改 configs、路线图勾选项、G0–G9 状态、B3/B4/G2–G9 代码、现有通用
`TushareBarMapper/TushareAdjustmentFactorMapper`、凭据或 `_old/`。

## 5. L0A：readiness 基准契约联调

### 5.1 固定输入语义

`audit_m3_readiness` 签名不变。股票 `bars` 继续使用现有股票字段；`benchmark_bars` 精确使用
`BenchmarkBar1dSchema`：

```text
benchmark,trade_date,open,high,low,close,source,source_snapshot_id
```

基准不是证券：不得要求 `symbol,volume,amount,adj_factor`，不得调用股票 `_valid_bars`、
`_check_positive_factor` 或按 symbol 分组。M3 v1 配置中的 benchmark 只接受 `H00300.CSI`；旧 fixture
中的 `000300.SH` 不能继续冒充全收益基准。

### 5.2 门禁与失败语义

- required columns 不足：`BENCHMARK_MISSING_FIELDS`；
- Schema/OHLC/null/non-finite/非正错误：`BENCHMARK_INVALID`；
- `(benchmark,trade_date,source)` 重复：`BENCHMARK_DUPLICATE_KEYS`；
- 配置不是 `H00300.CSI` 或响应混入其他 benchmark：`BENCHMARK_SYMBOL_MISMATCH`；
- 配置 source 选不到行：保留 `DATA_SOURCE_MISSING`；
- 配置区间内 SH 开市日缺基准：`BENCHMARK_DATE_COVERAGE`；
- 完全合法但零行：`BENCHMARK_EMPTY`。

readiness 继续返回排序后的 issue 列表，不因表错误向外抛 Polars/Pandera 异常。缺前置列时跳过依赖检查，
不得制造二次异常。

### 5.3 L0A 必测反例

1. 完全通过 `BenchmarkBar1dSchema` 且不含股票专属列的表，不出现任何 benchmark 类错误；
2. 同表重复 `(benchmark,date,source)` 失败；
3. null/NaN/Infinity/零/负 OHLC 分别失败；
4. `low > open` 或 `close > high` 失败；
5. 混入另一 benchmark 或另一 source 时，严格按配置选择且不静默混用；
6. `benchmark=000300.SH` 即使表结构合法也失败；
7. dense coverage 只从 `benchmark` 列取日期，训练 session 计数不回退到股票 helper。

## 6. B1：七个 raw endpoint 收口

当前初版实现以最小改动为原则保留。实现 Agent 逐项证明：

- 七个方法名、keyword-only 参数和 Tushare SDK method 精确对应 SSOT；
- 日期传 `YYYYMMDD`，`suspend_d` 固定额外参数 `suspend_type="S"`；
- `fields` 原字符串、原顺序传给 SDK；connector 不决定 fields allowlist；
- 返回供应商原始行顺序、重复键和原始列，不排序、不去重、不分块、不映射、不附加请求列；
- 空响应原样返回零行 DataFrame；endpoint 的 ALLOW/REJECT 由 B2A receipt policy 决定；
- A 股/指数代码和日期范围在网络前验证；fake client 测试不得初始化 token。

至少补一个跨七 endpoint 的反例：供应商返回同键两行且顺序为 `[B,A]`，结果仍精确为 `[B,A]`；不能只
断言行数。另验证输入 DataFrame 对象不是同一个引用也不能成为要求；只比较值、列顺序和行顺序。

## 7. B2B：四个核心 mapper

### 7.1 公共接口

新建 `src/quant/data/m3_mappers.py`，只公开：

```python
class M3G1MappingError(ValueError):
    code: str

def map_g1_daily_response(*, response: VerifiedRawResponse) -> pl.DataFrame: ...
def map_g1_adjustment_factor_response(
    *, response: VerifiedRawResponse
) -> pl.DataFrame: ...
def map_g1_benchmark_response(*, response: VerifiedRawResponse) -> pl.DataFrame: ...
def map_g1_suspension_response(*, response: VerifiedRawResponse) -> pl.DataFrame: ...
```

不得增加 class hierarchy、注册表、插件或可配置 source。只允许 import data/domain 层；不得反向 import
`quant.research`。函数只接受 exact `VerifiedRawResponse`，不接受裸 frame 或 duck-typed object。

### 7.2 精确输出

| 函数 | endpoint | 输出列（顺序固定） | key/sort |
|---|---|---|---|
| daily | `daily` | `symbol,trade_date,open,high,low,close,volume,amount,source` | `symbol,trade_date,source` |
| factor | `adj_factor` | `symbol,effective_date,adj_factor,source` | `symbol,effective_date,source` |
| benchmark | `index_daily` | `benchmark,trade_date,open,high,low,close,source,source_snapshot_id` | `benchmark,trade_date,source` |
| suspension | `suspend_d` | `symbol,trade_date,suspension_scope,suspension_detail,source,source_snapshot_id` | `symbol,trade_date,source` |

所有输出 `source="tushare"`。benchmark/suspension 的 `source_snapshot_id` 取 receipt 的
`raw_snapshot_id`；daily/factor 的 receipt 血缘由后续 candidate 的 response 闭包保存，禁止修改
`Bar1dSchema/AdjustmentFactorSchema` 强塞字段。

daily 尚未拼 factor，严禁写 `adj_factor=1.0`。单位换算固定为 `vol*100` 股、`amount*1000` 元。
factor 每个供应商交易日均保留，包括连续相同值。

### 7.3 消费边界门禁

每个 mapper 在读取值前重新检查：

1. response 类型、endpoint、spec/receipt endpoint 和 frozen fields/columns；
2. per-symbol response 中每行 `ts_code == spec.parameters["ts_code"]`；
3. `index_daily` 请求和每行都只有 `H00300.CSI`；
4. `daily/adj_factor/index_daily` 非空；
5. 日期严格为 8 位 `YYYYMMDD` 且位于 request start/end；
6. 数值不能宽松 `strict=False`、字符串吞错、null、NaN 或 Infinity；
7. OHLC 正且 `low <= open/close <= high`，volume/amount 非负，factor 正；
8. 结果 key 唯一并稳定排序。

raw 有额外列、缺列或列顺序改变都报 columns invalid。不要因 `Verified` 名称而跳过消费边界验真。

### 7.4 suspension 规范化

- `suspend_type` 非 `S`：失败；
- 同键所有 `suspend_timing` 为 null：一行 `FULL_DAY`，detail 为 null；
- 同键所有 timing 非空：一行 `PARTIAL`；原字符串不 strip/改写，相同值去重，Unicode 码点排序，以
  精确 `" | "` 连接；
- FULL/PARTIAL 同键并存：失败；
- A 股代码非法、日期越界或 source key 重复：失败；
- 合法空响应：返回固定列和 dtype 的零行表。

### 7.5 Suspension Schema

在 `schemas.py` 新增并从 `quant.domain` 导出：

```python
class Suspension1dSchema(pa.DataFrameModel):
    symbol: str                         # 仅六位 A 股 .SH/.SZ
    trade_date: pl.Date
    suspension_scope: str              # FULL_DAY / PARTIAL
    suspension_detail: str | None
    source: str
    source_snapshot_id: str
```

严格列；唯一键 `(symbol,trade_date,source)`；`FULL_DAY` 当且仅当 detail=null，`PARTIAL` 当且仅当 detail
为非空字符串。source/source_snapshot_id 均为非空、无控制字符字符串。

### 7.6 稳定错误

`M3G1MappingError.code == str(error)`，只允许：

```text
G1_MAPPER_RESPONSE_INVALID
G1_MAPPER_ENDPOINT_MISMATCH
G1_MAPPER_EMPTY
G1_MAPPER_COLUMNS_INVALID
G1_MAPPER_REQUEST_SCOPE_MISMATCH
G1_MAPPER_VALUE_INVALID
G1_MAPPER_DUPLICATE_KEY
G1_MAPPER_SUSPENSION_CONFLICT
G1_MAPPER_SCHEMA_INVALID
```

底层 `PolarsError/Pandera/OSError/TypeError/ValueError` 转换使用 `from None`。message、repr、显式 cause 和
格式化 traceback 不得包含原始行、绝对路径、token、client/receipt 完整 repr。不得 catch
`BaseException/KeyboardInterrupt/SystemExit`。

## 8. 明确排除项

本轮不实现：

- `stk_limit`/dividend mapper、公司行动公告版本选择、factor-ratio reconciliation；
- `apply_adjustment_factors_strict`；
- B3 membership/PIT；
- B4 candidate/audit/BaoStock/release；
- 真实 Tushare 调用、配置加载、CLI、snapshot/provider/Qlib/MLflow；
- G0–G9 状态或路线图勾选。

这些功能分别进入 B2C/B3/B4，不能用本包的占位实现抢跑。

## 9. 实现 Agent 最低测试矩阵

除 L0A/B1 反例外，B2B 至少覆盖：

1. daily 两行乱序后稳定排序、单位换算、准确 dtype；
2. daily/factor/benchmark 的 endpoint 互换全部拒绝；
3. A spec+B frame（内部 receipt 自洽但行 `ts_code` 与请求不一致）拒绝；
4. fields 缺一列、多一列、换序分别拒绝；
5. 日期非法、越界，字符串数字、null、NaN、Infinity 分别拒绝；
6. daily OHLC 非法、负量额；factor 0/负；三类重复 key；
7. factor `[1,1,2]` 输出仍三行；
8. benchmark 输出不含 symbol/volume/amount/adj_factor，且通过 `BenchmarkBar1dSchema`；
9. suspension empty/FULL/PARTIAL/多 detail/重复 detail/FULL+PARTIAL/非 S；
10. 输出输入乱序不影响 bytes-independent 内容和排序；
11. 构造底层异常包含绝对路径和疑似 token，公开异常四个观察面均脱敏；
12. `quant.data.m3_mappers` import 不触发 token、网络或 research/heavy dependency import。

测试必须构造真实 `VerifiedRawResponse`，不得用 `SimpleNamespace` 绕过 B2A 值对象。

## 10. 独立验收 Agent 要求

独立 Agent 不改生产代码或实现者测试，至少增加下列未公开变体：

1. response 本身合法，但 per-symbol frame 混入第二个合法 A 股代码；
2. benchmark 请求合法，frame 混入 `000300.SH`；
3. 数值列为 decimal-looking string，确认 strict cast 不吞错；
4. suspension 两个 partial detail 输入顺序相反，输出必须相同；
5. 全部 FULL 重复 raw 行只能规范成一行，不能因 raw 重复被 connector 吞掉；
6. Polars 日期解析异常的 message/cause/traceback 注入绝对路径标记；
7. readiness 合法基准不含股票列，且配置区间外行不补足区间内缺口；
8. import spy 证明没有 `quant.research` 反向依赖、token 读取或网络调用。

逐项映射任务书证据；不能以“全量绿”代替。发现问题按 P0/P1/P2/P3 分级，业务前视、raw 证据丢失、
单位错误、身份错配、安全泄露和错误基准均至少 P1，并退回实现闭环。

## 11. 验证命令

实现与独立复验都在 WSL Miniforge base 执行：

```bash
PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base --no-capture-output \
  python -m pytest tests/unit/test_m3_readiness.py \
  tests/unit/test_tushare_connector.py tests/unit/test_m3_backfill_requests.py \
  tests/unit/test_m3_g1_mappers.py -q

PYTHONPATH=src /home/mabw/miniforge3/bin/conda run -n base --no-capture-output \
  python -m pytest -q

/home/mabw/miniforge3/bin/conda run -n base --no-capture-output \
  python -m ruff check src tests

/home/mabw/miniforge3/bin/conda run -n base --no-capture-output \
  python -m mypy src
```

另做静态检查：`src/quant/data` 不 import `quant.research`；新模块不出现 token、配置路径、网络调用、
`unique(keep="last")`、`strict=False`、默认 factor 1.0。

## 12. 交付边界

独立复验通过时只可声明：`G1-P1 外部闭环通过，可交主 Agent 终验`。不得声明 L0/B1/B2/G1/M3/Gate
最终通过，不得更新路线图。主 Agent 将再复核源代码、未公开反例、全量回归、SSOT 和跨模块不变量。
