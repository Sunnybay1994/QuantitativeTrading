# M3 G8C-C1 U5 R1：G7E 首场景内部异常秒级诊断报告

日期：2026-08-12  
角色：外部 Cursor `auto` 独立诊断（U5）；未参与 U4 仪器/清理/Diagnostic 托管  
模型：`auto`（不声称具体底层模型）  

## 结论（压缩）

| 项 | 判定 |
|---|---|
| **Honest-chain 内部首异常 exact type/行级不变量** | **`INSUFFICIENT_INTERNAL_EVIDENCE`** |
| U4 首失败前边界 freshness | **已证明**（见 §1） |
| Public 脱敏异常 | `AShareSimulationError` / 消息类 `M3_A_SHARE_SIMULATION_INVALID` / `cause=None` |
| CLI 公开码 | `STAGE_BUILD_FAILED` / exit `5` |
| G7E/G7F 合成 fixture @0.5 | **PASS**（与 honest chain **不同输入**） |
| 异常翻译机制 | **已映射并探针验证**（§2） |
| 可否宣布产品/Gate PASS | **否** |

临时探针摘要（脱敏）：`C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u5-r1-internal-probe\u5_probe_results.json`、`u5_probe_v2.json`

上游：[M3_G8C_C1_U5_R1_G7E首场景内部异常秒级诊断任务单.md](M3_G8C_C1_U5_R1_G7E首场景内部异常秒级诊断任务单.md)、[M3_G8C_C1_U4_R1_owned残留精确清理与单次业务边界诊断报告.md](M3_G8C_C1_U4_R1_owned残留精确清理与单次业务边界诊断报告.md)

---

## 1. U4 首失败前已成功边界（fresh 输入证据）

来源：`phase_u4_observe.json`（U4 证据目录，只读复算）。

| 序 | 边界 | 调用 | 终态 | 说明 |
|---:|---|---:|---|---|
| 4–23 | `write_bytes`×10 / `read_bytes`×6 / `commit`×4 | 各 1–10 | ok | honest public-chain **前置 stage publication**；发生在 `build_backtest_artifact` 之前 |
| 24 | lifecycle `setup` | — | **passed** | 相对 U3 `setup/failed`：owned 残留已清除；**G1→target 链已 materialize** |
| 27 | `_validate_formal_inputs` | 1 | ok | formal bundle 输入契约 |
| 28 | `verify_backtest_plan_artifact` | 1 | ok | plan fresh 验证 |
| 29 | `load_verified_a_share_market_facts` | 1 | ok | facts fresh 加载 |
| 30 | `_formal_config_values` | 1 | ok | cost/initial_cash/annualization |
| **31** | **`simulate_formal_a_share_scenario`** | **1** | **failed** | **multiplier=`0.5`（首场景 `0p5x`）** |

**首失败**：seq 31；其后 `_formal_scenario_metrics` / `_formal_parquet_bytes` / readback 均未达。

Setup stdout 含 LightGBM「0 used features」警告 → **上游 target/model 可能退化**，但 **不能** 当作 simulation 内部触发点已证。

---

## 2. Public 边界与内部原始异常

### 2.1 Honest chain（U4 唯一 Diagnostic）

| 字段 | 值 |
|---|---|
| Public type | `quant.backtest.a_share_simulator.AShareSimulationError` |
| Public 消息类 | `M3_A_SHARE_SIMULATION_INVALID` |
| `.code` / instrument `code` | `null`（`AShareSimulationError` 无 `.code`；**非**「无稳定消息」） |
| `__cause__` / `__context__` | `null` / `null` |
| 翻译点 | `simulate_formal_a_share_scenario`：`except Exception: pass` → `raise AShareSimulationError(_FORMAL_SIMULATION_ERROR) from None`（`a_share_simulator.py` L429–431） |

**内部原始异常（honest chain）**：U4 observer 仅包装 **public** 边界；上述 swallow 使 **任何** `_simulate_formal_a_share_scenario` 内部 `Exception` 在 honest chain 路径 **不可观测** → **`INSUFFICIENT_INTERNAL_EVIDENCE`**。

### 2.2 探针验证的翻译机制（合成路径，非 honest 输入）

方法：系统临时目录 `u5_internal_probe*.py`，runtime monkeypatch **仅观察** `_simulate_formal_a_share_scenario` 抛出项，不改变 swallow 语义。

| 探针 | 输入 | multiplier | 内部（脱敏） | Public |
|---|---|---:|---|---|
| G7E `_case` 无 plan mock | 不完整 receipt | 0.5/1/2 | `ValueError` / `M3_BACKTEST_PLAN_ARTIFACT_INVALID` / `a_share_plan.py:173` | `AShareSimulationError` / `M3_A_SHARE_SIMULATION_INVALID` |
| G7F `_formal_case` + plan/facts mock | 合成 capability | 0.5/1/2 | **无**（`internal_all=[]`） | **ok**（nav=5, trades=3） |
| G7F `build_backtest_artifact` | 同上 | 0.5→2×3 | **无** | **ok** |

定向 pytest（`PYTHONPATH=src`，未改仓库）：

- `test_m3_g7e_formal_a_share_simulator.py::test_formal_replay_uses_fresh_plan_exactly_once` — **PASS**
- `test_m3_g7f_formal_backtest_artifact.py::test_formal_build_verify_actual_chain_exact_three_and_21_29` — **PASS**（含 actual `simulate` @0.5/1/2）

---

## 3. 首个触发函数 / 不变量 / 输入形状（honest chain）

| 维度 | 已冻结 | 未冻结 |
|---|---|---|
| Public 触发函数 | `simulate_formal_a_share_scenario` call#1 | — |
| Private core | `_simulate_formal_a_share_scenario` | exact 抛出点 |
| multiplier | `Decimal("0.5")` | — |
| symbol/date/shape | honest chain 真实 target/plan/facts（setup 已 fresh） | 具体 symbol 集、scheduled_targets 形状、权重和 |
| 内部异常 type/message 类 | — | **缺失** |

Core 内 **候选** `raise ValueError` 密集区（只读源码，**未证 honest chain 命中**）：identity/plan 对齐（L467–480）、session loop `pre_trade_equity <= 0`（L576–577）、transition 一致性（L590–598）、entitlement `replay.phase != COMPLETE`（L732–733）等。

---

## 4. G7E/G7F 单测未覆盖 honest chain 的原因

| 差异维 | G7E/G7F fixture | U4 honest chain |
|---|---|---|
| 数据来源 | `_five_session_facts` / capability 合成 3 符号 × 5 日 | `public_formal_chain_session(horizon=5)` 全链 materialize |
| Plan/facts 验证 | G7F **mock** `verify_backtest_plan_artifact` / `load_verified_a_share_market_facts` 返回内存对象 | **实际** verify/load + publication receipts |
| Target 权重 | 固定 `(0.2,0.2,0.2)` 等 | LightGBM **0 used features** 后真实 target（形状/权重未知） |
| multiplier 覆盖 | G7F actual 三场景含 0.5 | 首场景 0.5 **即失败** |
| 典型 G7E 默认 | `_case` 默认 `multiplier=Decimal("1")` | 首场景强制 0.5 |

**结论**：现有单测证明 **合成 formal 路径** 在 0.5x 可 replay；**不能** 证明 honest-chain 产物等价。

---

## 5. 现象—根因—规则—最小复现—测试—通过条件

| 项 | 内容 |
|---|---|
| **现象** | U4 Diagnostic `EXIT=1`；首失败 `simulate_formal_a_share_scenario` @0.5x；public `AShareSimulationError`；CLI `STAGE_BUILD_FAILED`/5 |
| **根因（已证）** | Public hostile boundary 吞没 `_simulate_formal_a_share_scenario` 全部内部异常；U4 仪器无法观测内部 |
| **根因（honest chain 内部，未证）** | **`INSUFFICIENT_INTERNAL_EVIDENCE`** — 缺 retained honest target/plan/facts 快照 |
| **应遵循规则** | 禁止重跑 U4 73min Diagnostic；禁止 `object.__new__`/伪 capability/seal 绕过；不得把 instrument `code=null` 写成无公开消息 |
| **最小复现（honest）** | 需 **retained** 链产物或 ≤分钟级「仅 backtest stage」探针 + 内部 observe wrapper；**本轮未执行** |
| **最小复现（合成对照）** | 临时目录 G7F `_formal_case` → `simulate_formal_a_share_scenario(..., multiplier=Decimal("0.5"))` → **ok** |
| **建议新增测试** | （1）honest-chain **衍生**最小 plan/facts/target fixture（从一次可丢弃 chain 快照冻结）上 actual simulate @0.5，断言内部类型或允许 pass；（2）可选 diagnostic 构建：`pytest`-外置 wrapper 记录 `_simulate` 首异常（不进入生产） |
| **U5 诊断通过条件** | 已获得 **可冻结翻译链 + fixture 差异 + 探针方法论**；**未**获得 honest chain 内部 exact 证据 → 按任务书报告 **`INSUFFICIENT_INTERNAL_EVIDENCE`** |

---

## 6. 最小实现白名单（**仅当主 Agent 下一步选择「先补诊断」时**）

| 优先级 | 路径 | 条件 |
|---|---|---|
| — | **无产品返工白名单** | honest 内部触发点未证，不宜默认改 simulator/reporting |
| D0 | 主 Agent 托管 **一次性** honest 链产物快照 retain（或 ≤分钟 backtest-only 探针） | 解冻内部 exact 证据 |
| D1 | 临时 observe wrapper（系统 temp，不入库） | 已有方法论，可复用 |

**若未来内部证据指向具体 `ValueError` 不变量**，再按 U4 §5 候选：`a_share_simulator.py` → `a_share_reporting.py` → `test_m3_g7f_formal_backtest_artifact.py`。**不在无证据时扩大** stage/publication/CLI。

---

## 7. 秒级回归（本轮已跑）

```text
# 探针（temp）
D:\Miniforge3\python.exe C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u5-r1-internal-probe\u5_internal_probe_v2.py

# 合成对照
set PYTHONPATH=F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal\src
D:\Miniforge3\python.exe -m pytest -q tests/unit/test_m3_g7e_formal_a_share_simulator.py::test_formal_replay_uses_fresh_plan_exactly_once tests/unit/test_m3_g7f_formal_backtest_artifact.py::test_formal_build_verify_actual_chain_exact_three_and_21_29 -p no:cacheprovider
# 2 passed (~530s)
```

禁止用以上代替 U4 Diagnostic 或 WSL Gate。

---

## 8. 所有权

| 允许 | 禁止 |
|---|---|
| 本报告 + U5 任务状态 | 改 production/tests/config/data/artifacts/support；重跑 U4 Diagnostic/完整 chain |

本报告为 U5 唯一持久交付。
