# M4 D1-R Route Repository 闭包独立初验报告

日期：2026-07-17  
角色：外部独立初验 Agent（D1-R；未参与实现）  
状态：**独立初验通过（待主 Agent 终验）**  
来源：
- [`M4_D1Route闭包与M3_HISTORY截断返工任务单.md`](M4_D1Route闭包与M3_HISTORY截断返工任务单.md)
- [`M4_D1-R_RouteRepository闭包交付报告.md`](M4_D1-R_RouteRepository闭包交付报告.md)

声明：本会话只读核对生产代码、实现者测试、配置与 data；唯一写入为本报告。未执行 HISTORY-H1；未联网；未初始化 Git；未跑全量 pytest；未修改任何生产/测试代码。

## 1. 范围与环境

| 项 | 内容 |
|---|---|
| 验证包 | 仅 D1-R |
| 权威合同 | 任务单 §1 |
| 只读核对 | `src/quant/execution/ports.py`、`src/quant/data/repositories.py`、`tests/unit/test_execution_ports.py`、交付报告 |
| 环境 | WSL `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，`/home/mabw/miniforge3/bin/conda run -n base` |
| 禁止项遵守 | 无 HISTORY-H1 / 无网络 / 无 Git init / 无全量 pytest / 无 Windows Python |

## 2. 合同逐项核对（标准 → 证据 → 结论）

| # | 合同点 | 证据 | 结论 |
|---|---|---|---|
| C1 | Public API 三入口统一 `connect_routes: tuple[ConnectRoute, ...]` 且无默认 | `ports.py` Protocol；`ValidatedCleanMarketDataRepository` / `InMemoryMarketDataRepository.load_verified_market_snapshot`；探针 A1/A7 | 通过 |
| C2 | exact tuple；元素 exact `ConnectRoute`；按 `.value` 严格升序且唯一 | `_require_exact_connect_routes`；实现者 `test_connect_routes_reject_string_list_unsorted_duplicate_fake_bool_int`；探针 A3（tuple 子类） | 通过 |
| C3 | 生产可选 `connect_context_repository`；仅 HK 时按 route 调用，且 `as_of=bundle.known_as_of` | `_assemble_connect_contexts` / `_load_connect_contexts_for_routes`；**对抗探针 A2**（实现者未断言该 as_of 传参） | 通过 |
| C4 | 返回 exact 类型、identity 自证、route/session 全等、`context.as_of <= known_as_of` | `_validate_loaded_connect_context`；实现者错类型/错 route/错 session/未来 as_of/forged id；探针 A5（known&lt;ctx.as_of&lt;request） | 通过 |
| C5 | A 股显式 `()`；非空 route → `CONNECT_CONTEXT_UNEXPECTED` 且 context repo 零调用 | 既有 A 股测试均 `connect_routes=()`；`test_a_share_nonempty_routes_...`；探针 A4（空 routes + 有 repo 成功且零调用） | 通过 |
| C6 | HK + 空 routes / 缺 repo / reader 失败语义 | `CONNECT_CONTEXT_REQUIRED` / `REPOSITORY_REQUIRED` / `READER_FAILURE` / `CONTRACT_INVALID` 测试与实现 | 通过 |
| C7 | InMemory `from_states` 无默认 `connect_contexts`；加载 route 集合精确相等 | `from_states` 签名；`SNAPSHOT_CONNECT_ROUTES_MISMATCH` 子集/超集/另一 route；探针 A1d | 通过 |
| C8 | 稳定错误码七项齐全且脱敏 `from None` | 代码字面量 + 实现者路径脱敏测试 + 探针 A6（链式 OSError） | 通过 |
| C9 | 两 route 顺序不影响 identity；quota 变化改变 identity | `test_two_routes_order_independent_quota_changes_identity` | 通过 |
| C10 | runtime Protocol 非经济闭包 | `test_market_data_repository_runtime_checkable_not_economic_closure` | 通过 |
| C11 | 未擅自改 `src/quant/data/__init__.py` | 交付声明 + `__init__.py` 无相关导出变更迹象 | 通过 |
| C12 | 白名单外未扩张本轮职责 | 对照任务单 §1.4 与交付文件清单；本初验未发现越权实现入口 | 通过 |

## 3. 实现者必测反例覆盖映射

| 任务单 §1.5 | 实现者测试 | 初验 |
|---|---|---|
| 1 A 股 `connect_routes=()` 全绿，原错误脱敏 | 既有用例补齐 + 定向 26 passed | 覆盖 |
| 2 裸 string/list/乱序/重复/伪 Enum/bool/int | `test_connect_routes_reject_...` | 覆盖 |
| 3 HK 空 routes / 缺 repo / 错类型 route session 未来 as_of forged | `test_hk_states_require_routes_...` | 覆盖 |
| 4 A 股非空 route + 零调用 | `test_a_share_nonempty_routes_...` | 覆盖 |
| 5 两 route 顺序与 quota identity | `test_two_routes_order_independent_...` | 覆盖 |
| 6 InMemory 超集/子集/另一 route | `test_inmemory_connect_routes_exact_set_mismatch` | 覆盖 |
| 7 reader 绝对路径不泄露 | `test_connect_context_reader_path_sanitized` | 覆盖 |
| 8 Protocol 非经济闭包 | `test_market_data_repository_runtime_checkable_...` | 覆盖 |

## 4. 对抗性反例（实现者未使用）

探针文件：`/tmp/d1r_adversarial_probe.py`（不落仓库）。退出码 **0**。

| ID | 反例（实现者套件未见） | 期望 | 结果 |
|---|---|---|---|
| A2 | request `as_of` 晚于 `known_as_of` 时，spy 断言 context reader 收到的 `as_of` **等于** `bundle.known_as_of` 且 **不等于** request | 合同冻结传参 | PASS |
| A3 | `tuple` 子类伪装 `connect_routes` | `INVALID_CONNECT_ROUTES` | PASS |
| A4 | A 股 `connect_routes=()` 且注入会爆炸的 context repo | 成功且零调用 | PASS |
| A5 | 返回 `known &lt; context.as_of &lt; request` 的 context | `CONNECT_CONTEXT_CONTRACT_INVALID` | PASS |
| A6 | 链式 `FileNotFoundError`→`OSError` 含绝对路径 | 脱敏、`__cause__ is None`、无路径泄露 | PASS |
| A7 | 省略 `connect_routes` 关键字 | `TypeError`（无静默默认） | PASS |

主对抗点 **A2** 直接对准任务单冻结调用：`as_of=bundle.known_as_of`。实现者交付测试未对该传参做 spy 断言；本初验独立证明行为符合合同。

## 5. 验收命令与退出码

```text
python -m pytest tests/unit/test_execution_ports.py -q
→ 26 passed  EXIT:0

python -m pytest \
  tests/unit/test_execution_contracts.py \
  tests/unit/test_connect_execution.py \
  tests/unit/test_pretrade_risk.py -q
→ 87 passed  EXIT:0

python -m ruff check \
  src/quant/execution/ports.py src/quant/data/repositories.py \
  tests/unit/test_execution_ports.py
→ All checks passed!  RUFF_EXIT:0

python -m mypy \
  src/quant/execution/contracts.py src/quant/execution/ports.py \
  src/quant/data/repositories.py src/quant/backtest/connect_execution.py \
  src/quant/execution/risk.py
→ Success: no issues found in 5 source files  MYPY_EXIT:0

python /tmp/d1r_adversarial_probe.py
→ SUMMARY_FAILS 0  PROBE_EXIT:0
```

## 6. 残留风险（不阻塞初验）

- `runtime_checkable` Protocol 仍只证明方法名；经济闭包依赖调用方显式校验（合同已承认）。
- 白名单外若仍有未改动的生产调用方未传 `connect_routes`，合流时可能暴露；本轮未跑全量 pytest（符合任务边界）。
- context reader 若直接抛出带敏感信息的 `RepositoryContractError`，当前实现会原样重抛；非“底层 Exception”路径。建议主验/后续可考虑是否统一再包装；**不作为本轮初验失败项**。

## 7. 结论

**D1-R 独立初验通过。** 公开调用闭包、稳定错误码、A 股零 context、HK exact routes、as_of/identity 与对抗探针均满足任务合同。不得据此宣称 D1 / M4 / Gate / 主验通过。下一步：主 Agent 终验通过后，方可按任务单串行启动 HISTORY-H1。
