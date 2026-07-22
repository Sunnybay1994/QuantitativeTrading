# M4 D1-R Route Repository 闭包交付报告

日期：2026-07-17  
角色：外部实现 Agent（D1-R；cursor-grok-4.5-high）  
状态：**待独立初验**  
来源：[`M4_D1Route闭包与M3_HISTORY截断返工任务单.md`](M4_D1Route闭包与M3_HISTORY截断返工任务单.md)

声明：本报告只交付 D1-R 实现与定向自测证据；不兼任独立初验；不宣称 D1 / M4 / Gate / 主验通过。未执行 HISTORY-H1。

## 1. 实现摘要

| 项 | 内容 |
|---|---|
| Public API | `MarketDataRepository` / `ValidatedCleanMarketDataRepository` / `InMemoryMarketDataRepository.load_verified_market_snapshot` 统一增加无默认 `connect_routes: tuple[ConnectRoute, ...]` |
| Route 门禁 | exact tuple；元素 exact `ConnectRoute`；按 `.value` 严格升序且唯一；裸 string / list / 乱序 / 重复 / 伪 Enum / bool / int → `INVALID_CONNECT_ROUTES` |
| 生产装配 | `ValidatedCleanMarketDataRepository` 可选 `connect_context_repository`；仅 HK states 时按 route 调用 `load_verified_connect_market_context(route, session_date, as_of=bundle.known_as_of)`，并做 exact 类型、identity 自证、route/session 全等、`as_of <= known_as_of` |
| A 股路径 | 显式 `connect_routes=()`；非空 route → `CONNECT_CONTEXT_UNEXPECTED` 且 context repository 零调用 |
| HK 失败 | 空 routes → `CONNECT_CONTEXT_REQUIRED`；缺 repository → `CONNECT_CONTEXT_REPOSITORY_REQUIRED`；reader 异常 → 脱敏 `CONNECT_CONTEXT_READER_FAILURE`；错类型/错 route/错 session/未来 as_of/forged id → `CONNECT_CONTEXT_CONTRACT_INVALID` |
| InMemory | `from_states` 新增无默认 `connect_contexts`；加载时 request route 集合必须与 snapshot route 集合精确相等，否则 `SNAPSHOT_CONNECT_ROUTES_MISMATCH` |
| 回归修复 | 所有 `build_verified_market_snapshot` 调用补齐 `connect_contexts`；原 TypeError 不再漏出 |

稳定错误码：`INVALID_CONNECT_ROUTES` / `CONNECT_CONTEXT_REQUIRED` / `CONNECT_CONTEXT_UNEXPECTED` / `CONNECT_CONTEXT_REPOSITORY_REQUIRED` / `CONNECT_CONTEXT_READER_FAILURE` / `CONNECT_CONTEXT_CONTRACT_INVALID` / `SNAPSHOT_CONNECT_ROUTES_MISMATCH`。底层异常均脱敏并切断 `__cause__`/`__context__`。

未改 `src/quant/data/__init__.py`（现有导出无需变更）。

## 2. 已改文件（白名单）

- `src/quant/execution/ports.py` — Protocol 增加 `connect_routes`
- `src/quant/data/repositories.py` — route-aware 装配与失败语义
- `tests/unit/test_execution_ports.py` — 既有 A 股调用补 `connect_routes=()` / `connect_contexts=()`；新增 8 类必测反例
- `docs/agent/M4_D1-R_RouteRepository闭包交付报告.md` — 本文件

## 3. 定向自测

环境：WSL `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，Miniforge `base`（`conda run -n base`）。未联网、未改 data、未初始化 Git、未跑全量 pytest。

```text
python -m pytest tests/unit/test_execution_ports.py -q
→ 26 passed  (exit 0)

python -m pytest \
  tests/unit/test_execution_contracts.py \
  tests/unit/test_connect_execution.py \
  tests/unit/test_pretrade_risk.py -q
→ 87 passed  (exit 0)

python -m ruff check \
  src/quant/execution/ports.py src/quant/data/repositories.py \
  tests/unit/test_execution_ports.py
→ All checks passed!  (exit 0)

python -m mypy \
  src/quant/execution/contracts.py src/quant/execution/ports.py \
  src/quant/data/repositories.py src/quant/backtest/connect_execution.py \
  src/quant/execution/risk.py
→ Success: no issues found in 5 source files  (exit 0)
```

## 4. 风险与未决

- `runtime_checkable` 的 `MarketDataRepository` / `ConnectMarketContextRepository` 仍只证明方法名存在；经济闭包依赖 adapter/caller 显式校验（测试已覆盖）。
- 白名单外调用方若尚未传入 `connect_routes` 会在合流时暴露；本轮未改其他生产调用点，也未跑全量 pytest。
- 下一步：由**未参与本轮实现**的全新外部 Agent 只读独立初验（含实现者未使用的对抗性反例）；初验通过后再启动 HISTORY-H1。
