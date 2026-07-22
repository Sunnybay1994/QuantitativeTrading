# M4 D1 Route 闭包与 M3 HISTORY 截断返工任务单

日期：2026-07-17  
状态：**主 Agent 冻结，交外部 Agent 执行**  
执行顺序：D1-R → 独立初验 → HISTORY-H1 → 独立初验 → 停止等待网络授权  
模型：实现、返工和独立验收均使用非 fast `cursor-grok-4.5-high`

两个包代码文件互不重叠，但 HISTORY 的零网络 status 会捕获 source-tree identity。为避免身份漂移，本轮不并发：
必须先完成 D1-R 全部写入和独立初验，再启动 HISTORY-H1。

## 1. D1-R — Route-aware repository 闭包

### 1.1 目标

修复新版 `VerifiedMarketSnapshot.connect_contexts` 导致的两个公共入口回归，并使 D1 production/fake repository
能够按调用方显式 route 装配 HK snapshot。不能只给现有 A 股调用补 `connect_contexts=()` 后宣称完成。

### 1.2 冻结 public API

`MarketDataRepository`、`ValidatedCleanMarketDataRepository` 和 `InMemoryMarketDataRepository` 的加载接口统一为：

```python
def load_verified_market_snapshot(
    self,
    *,
    symbols: tuple[str, ...],
    session_date: date,
    as_of: datetime,
    connect_routes: tuple[ConnectRoute, ...],
) -> VerifiedMarketSnapshot: ...
```

`connect_routes` 无默认值，必须是按 `.value` 严格升序且唯一的 exact tuple，元素必须为精确 `ConnectRoute`。
A 股-only 调用显式传 `()`；含 HK state 必须至少给一条 route；不含 HK state 时非空 route 失败。

生产 repository 构造器新增可选依赖：

```python
connect_context_repository: ConnectMarketContextRepository | None = None
```

只在 validated clean states 中存在 HK 时使用该依赖。对每个请求 route 调用：

```python
load_verified_connect_market_context(
    route=route,
    session_date=session,
    as_of=bundle.known_as_of,
)
```

调用后必须显式验证：返回 exact `VerifiedConnectMarketContext`、identity 自证、route/session 全等、
`context.as_of <= bundle.known_as_of`。`runtime_checkable Protocol` 不能代替这些检查。

`InMemoryMarketDataRepository.from_states` 新增无默认的
`connect_contexts: Sequence[VerifiedConnectMarketContext]`。加载时请求 `connect_routes` 必须与 snapshot 中的 route
集合精确相等；不得返回 route 超集或子集。

### 1.3 稳定失败语义

沿用 `RepositoryContractError`，新增或复用稳定 code：

- `INVALID_CONNECT_ROUTES`
- `CONNECT_CONTEXT_REQUIRED`
- `CONNECT_CONTEXT_UNEXPECTED`
- `CONNECT_CONTEXT_REPOSITORY_REQUIRED`
- `CONNECT_CONTEXT_READER_FAILURE`
- `CONNECT_CONTEXT_CONTRACT_INVALID`
- `SNAPSHOT_CONNECT_ROUTES_MISMATCH`

所有底层异常必须脱敏并 `from None`；不得输出绝对路径、返回对象 repr 或 SDK 文本。

### 1.4 文件白名单

- `src/quant/execution/ports.py`
- `src/quant/data/repositories.py`
- `tests/unit/test_execution_ports.py`
- `docs/agent/M4_D1-R_RouteRepository闭包交付报告.md`

包导出若现有符号已导出则不改；发现确需修改 `src/quant/data/__init__.py` 时先在报告说明并停止，请协调者更新
白名单，不能擅自扩大。

### 1.5 必测反例

1. 所有既有 A 股 repository 测试显式 `connect_routes=()` 并恢复全绿，原错误仍转换为脱敏
   `RepositoryContractError`，不能漏出 TypeError。
2. route 裸 string、list、乱序、重复、伪 Enum 失败；bool/int 不得冒充。
3. HK states + 空 routes、缺 context repository、reader 返回错类型/错 route/错 session/未来 as_of/forged id 均
   fail closed。
4. A 股 states + 非空 route 失败，且 context repository 零调用。
5. 两 route 返回顺序不影响 snapshot identity；只改 quota/context payload 会改变 snapshot identity。
6. InMemory 请求 route 与 snapshot route 超集、子集或另一 route 均失败。
7. context reader 抛含绝对路径异常时，公开异常的 message、cause、context、traceback 不泄露。
8. `MarketDataRepository` runtime Protocol 仍只能证明方法存在；错误签名 fake 可 `isinstance`，测试不得误报经济闭包。

### 1.6 高效验证

```bash
python -m pytest tests/unit/test_execution_ports.py -q
python -m pytest \
  tests/unit/test_execution_contracts.py \
  tests/unit/test_connect_execution.py \
  tests/unit/test_pretrade_risk.py -q
python -m ruff check \
  src/quant/execution/ports.py src/quant/data/repositories.py \
  tests/unit/test_execution_ports.py
python -m mypy \
  src/quant/execution/contracts.py src/quant/execution/ports.py \
  src/quant/data/repositories.py src/quant/backtest/connect_execution.py \
  src/quant/execution/risk.py
```

不得跑全量 pytest。

## 2. HISTORY-H1 — suspend_d 确定性逐证券计划

### 2.1 目标与依据

旧月窗会在 5000 行接口边界触发截断门禁。新计划只抓取历史成员并集所需证券，以每个 symbol 一个完整 history
window 请求替代按月全市场请求。官方接口支持 `ts_code/start_date/end_date/suspend_type`：
<https://tushare.pro/document/2?doc_id=214>。

本包仅修改代码、测试和文档，**零网络**。禁止执行 `history`、`run-all`、BaoStock 或任何 Tushare 请求。

### 2.2 冻结请求合同

`TushareConnector.fetch_suspend_raw` 改为：

```python
def fetch_suspend_raw(
    self,
    *,
    symbol: str,
    start: date,
    end: date,
    fields: str,
) -> pl.DataFrame: ...
```

它必须验证标准 A 股 symbol，并向 SDK 精确传：

```text
ts_code=<symbol>
start_date=<history.start>
end_date=<history.end>
suspend_type=S
fields=<frozen fields>
```

`plan_history_requests` 对每个 canonical symbol 生成五个 per-symbol request：
`daily/adj_factor/stk_limit/dividend/suspend_d`；另生成唯一 `index_daily`。因此：

```text
HISTORY requests = 5*S + 1
S=637 → 3186
```

新 `suspend_d` spec 参数精确含 `ts_code/start_date/end_date/suspend_type/fields`。禁止 monthly/date-only spec、分页
猜测、提高 row limit 或放宽 `frame.height >= 5000` 门禁。empty response 仍为 ALLOW。

### 2.3 既有 evidence 复用

- 旧 5 个完成月窗与 1 个失败月窗目录保持原位，不删除、不移动、不改写；它们不属于新 plan，不能计入完成数。
- request ID 未变的 daily 36、adj_factor 28、stk_limit 29、dividend 21，共 114 份 receipt 必须零网络复用。
- `index_daily` 现有完成数为 0。
- 新计划生成后，零网络 `status` 必须仍为 `completed_stages=[INDEX]`，计划 HISTORY=3186；不得因额外旧 journal
  报 `JOURNAL_INVALID`。
- 独立审计必须得到新计划未完成 request identities=3072；若数值不同，停止并提交差异，不联网修正。

### 2.4 文件白名单

- `src/quant/data/connectors/tushare.py`
- `src/quant/data/m3_backfill.py`
- `tests/unit/test_tushare_connector.py`
- `tests/unit/test_m3_backfill_requests.py`
- `tests/unit/test_m3_g1_planning.py`
- `tests/unit/test_m3_g1_workflow.py`（只新增/调整小型计划与恢复反例；禁止运行 five-stage 长测）
- `docs/agent/M3_G1_HISTORY-H1逐证券停牌计划交付报告.md`
- `docs/agent/M3_G1_R1C-B真实运行授权与资源清单.md`（仅在零网络数值验真后更新）

若生产代码事实要求修改 `g1_planning.py` 或 `run_g1.py`，实现 Agent 必须先停止并提交证据，由协调者重新冻结
白名单；不得擅自扩张。

### 2.5 必测反例

1. 两个 symbol 产生精确 11 个 HISTORY requests；其中两个 suspend spec 分别绑定 symbol，均覆盖完整 window。
2. symbols 输入顺序/重复不改变 plan；只改 symbol/window 会改变对应 request id 和 plan identity。
3. connector 裸 string 格式错误、非 A 股 symbol、倒置日期失败；SDK kwargs 精确包含 ts_code。
4. suspend response 4999 行可接受、5000 行仍拒绝；空响应仍允许。
5. `_fetch` 对 suspend spec 缺 ts_code 或使用旧月窗 spec 必须稳定失败，不能无 symbol 调 SDK。
6. 新 plan 下 114 个不变 receipt 可恢复；旧 5+1 suspend journal 作为 extra evidence 不参与新 plan但不阻塞 status。
7. 恢复不得触发 connector 构造或任何网络；凭据、绝对路径和 SDK异常不进入报告。
8. 不改配置日期、endpoint policy、max_attempts、限频、INDEX request ids 或 membership identity。

### 2.6 高效验证

只运行新增及直接相关节点：

```bash
python -m pytest tests/unit/test_tushare_connector.py -q
python -m pytest tests/unit/test_m3_backfill_requests.py -k 'history or suspend or truncat' -q
python -m pytest tests/unit/test_m3_g1_planning.py -k 'history_plan' -q
python -m pytest tests/unit/test_m3_g1_workflow.py -k 'history and not five_stage' -q
python -m ruff check \
  src/quant/data/connectors/tushare.py src/quant/data/m3_backfill.py \
  tests/unit/test_tushare_connector.py tests/unit/test_m3_backfill_requests.py \
  tests/unit/test_m3_g1_planning.py tests/unit/test_m3_g1_workflow.py
python -m mypy src/quant/data/connectors/tushare.py src/quant/data/m3_backfill.py
```

实现和独立初验均禁止运行 `test_five_stage_fake_publish_and_inspect_closure`、整份 workflow 慢测或全量 pytest。

外部独立初验通过后，由一个全新只读会话运行一次零网络：

```bash
python -m quant.research.m3.run_g1 \
  --config configs/research/m3_qlib_example.toml status
```

然后审计 plan/journal 数量并停止。不得启动 HISTORY。

## 3. 外部闭环与交付

每个包必须使用一个全新实现 Agent 和另一个全新、代码/data 只读验收 Agent。初验失败回实现 Agent返工，再开
新的独立复验，直至通过。两个包的报告统一更新
`docs/agent/M3_M4后续外部执行总报告.md`，状态只能写“外部闭环通过，待主 Agent 验收”。

两包闭环后停止所有外部会话，向用户返回：

- D1 四测试文件和五模块 mypy 是否全绿；
- 新 HISTORY 总计划、复用 receipt、未完成 request identity 精确数量；
- 旧 suspend evidence 保留情况；
- 建议的新网络授权语句。

没有用户新的明确授权，不得执行 HISTORY。

