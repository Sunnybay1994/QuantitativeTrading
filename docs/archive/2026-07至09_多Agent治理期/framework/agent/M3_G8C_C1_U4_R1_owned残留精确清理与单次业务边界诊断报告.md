# M3 G8C-C1 U4 R1：owned 残留精确清理与单次业务边界诊断报告

日期：2026-08-12  
角色：外部 Cursor `auto` 独立只读取证（U4-B）；未参与 U4-A 仪器准备、主 Agent 精确清理或唯一 Diagnostic 托管  
模型：`auto`（不声称具体底层模型）  
UA：UA-AGENT-002 已批准  

结论分层：

| 层 | 判定 |
|---|---|
| 精确 owned cleanup（dry-run + real） | **PASS** |
| U4 仪器 Handshake | **PASS** |
| 唯一 Diagnostic（业务首失败边界定位） | **FAIL / 已进入产品路径** |
| 首个业务失败边界 | `simulate_formal_a_share_scenario` call#1，multiplier=`0.5` |
| CLI 公开码 | `STAGE_BUILD_FAILED` / exit `5` |
| G7F 14 边界调用（相对 U3 全零） | **10 边界有事件；4 边界未达（首场景即失败）** |
| 可否由主 Agent 冻结最小实现返工 | **可进入冻结流程**（已定位可复现业务边界；**非本报告宣布修复/Gate**） |
| 可否重跑本轮 U4 Diagnostic | **否**（已唯一启动并终态明确） |

证据目录（只读核验）：
`C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u4-r1-g8-build-diagnostic\`

上游：
- [M3_G8C_C1_U4_R1_owned残留精确清理与单次业务边界诊断任务单.md](M3_G8C_C1_U4_R1_owned残留精确清理与单次业务边界诊断任务单.md)
- [M3_G8C_C1_U3_R1_仪器Handshake与单次业务边界诊断报告.md](M3_G8C_C1_U3_R1_仪器Handshake与单次业务边界诊断报告.md)（U3 setup 残留阻断；U4 cleanup 解除）

---

## 1. 证据完整性与 SHA / EXIT / lifecycle

### 1.1 U4-B 复算 SHA-256（本会话只读）

| 文件 | 长度 | SHA-256 |
|---|---:|---|
| `cleanup_u4_owned.py` | 15063 | `db4d5cc6f5b2e320087fb8492f8c7a4d9218bbb3ccfe3fbd773e61ba18718b8e` |
| `u4_observer_plugin.py` | 13095 | `93819dc27de1a4cf7dd961a31d72eb48edff481a00fc67dc1bee44363c229d76` |
| `run_u4_diagnostic.ps1` | 8462 | `627b2ceff7f931952bb8e44207c028f004b4d3c66568e04a1a5a07011fd7863f` |
| `M3_G8C_C1_U4_R1_cleanup_dry_run.txt` | 693 | `7c876252f2c9a15a5f12fbd20fa15a3b606a0079dddad82781cce92b18b811a5` |
| `M3_G8C_C1_U4_R1_cleanup_evidence.json` | 3361 | `d5bf11f50738e2e4dac56ee3642c5bc92b6d640eb2acf2f5408d718187a46c36` |
| `M3_G8C_C1_U4_R1_handshake_evidence.txt` | 1605 | `c34ca293cc145e257821229eb35e32e3ccc8b03ecd1fb04997d2135bfefd1a7b` |
| `M3_G8C_C1_U4_R1_handshake_assert.txt` | 478 | `23422861e537326b22215643d7ecabe511b37cc9a60e106f6db8525dc91bc690` |
| `phase_u4_handshake_observe.json` | 642 | `3980e1e2f034efade8e5a79615a2af306be00ebb9c49290259083297d943416c` |
| `M3_G8C_C1_U4_R1_diagnostic_evidence.txt` | 1997 | `5c35c53bc5a3665ab6b74a91f23b1f44f1ec3c1f8dbedabb2d5e519fbf4aba44` |
| `M3_G8C_C1_U4_R1_diagnostic_stdout.txt` | 3821 | `d108aa88c0249633fdde6a98a35f17c18f30750270d939261e74873515a5747a` |
| `M3_G8C_C1_U4_R1_diagnostic_stderr.txt` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `phase_u4_observe.json` | 8936 | `05511434a412148115820f5c9471e78c80f7c1f65127530104afe6b942036635` |
| `tests/integration/test_m3_g8c_c1_backtest_cli.py` | 4963 | `5ba1d2fcbd14d73627940f0127742f3d44387533e2ab4b6be5bbece8fb8014b2` |

prepare / handshake / diagnostic evidence 内 `SHA256_integration` 与 `FROZEN_INTEGRATION_SHA` 均为
`5ba1d2fcbd14d73627940f0127742f3d44387533e2ab4b6be5bbece8fb8014b2`，与工作树复算一致。

### 1.2 Cleanup

| 阶段 | EXIT | 关键字段 |
|---|---|---|
| dry-run | `0` | `DELETES=0`；三项 `MATCH`；token/SHA 与任务单 §2 一致 |
| real | （脚本整数退出；evidence `status=REMOVED_ALL_THREE`） | 删除顺序：g1 release → stage → config；三项 precheck `MATCH` |

U4-B 现地复核：§2 三路径 **`exists=False`**（config / stage / g1 release 均不存在）。

### 1.3 Handshake

| 字段 | 值 |
|---|---|
| `MODE` | `Handshake` |
| `STATUS` | `FINISHED` |
| `EXIT` | `0` |
| `ELAPSED_SEC` | `2` |
| `MODEL` | `auto` |
| `SUMMARY` | `sU4_HANDSHAKE_STDOUT_MARKER_c4e81f09 \| 1 passed, 1 skipped in 0.25s` |
| 权威断言 | `M3_G8C_C1_U4_R1_handshake_assert.txt` → `OVERALL=PASS` |

lifecycle：`collection_complete/ok` → `protocol/started` → `install/ok` → `setup/passed` → `call/passed` → `teardown/passed`  
boundary：`ping` calls=1，`first_failure=null`。

### 1.4 唯一 Diagnostic

| 字段 | 值 |
|---|---|
| `MODE` | `Diagnostic` |
| `STATUS` | `FINISHED` |
| `EXIT` | `1` |
| `ELAPSED_SEC` | `4392` |
| `START` / `END` | `2026-08-12T17:39:16+08:00` / `2026-08-12T18:52:27+08:00` |
| `WRAPPER_PID` / `PYTEST_PID` | `39948` / `9288` |
| `MODEL` | `auto` |

lifecycle：`collection_complete/ok` → `protocol/started` → `install/ok` → **`setup/passed`** → **`call/failed`** → `teardown/passed`  
（相对 U3 的 `setup/failed`，证明 owned cleanup 已解除 fixture 阻断。）

stdout：pytest `1 failed, 1 skipped`；CLI payload `STAGE_BUILD_FAILED` / `exit_code=5`。  
stderr 长度 0（失败在 stdout；与 U3 同类，不构成 wrapper 排空回归证明失败）。

---

## 2. G7F 14 边界调用次数（U3 → U4）

仪器冻结 14 名（short static `BOUNDARIES=14`）；observe 按 boundary 聚合 `calls`。

| # | 边界 | U3（setup 阻断） | U4（cleanup 后 Diagnostic） | U4 首事件终态 |
|---:|---|---:|---:|---|
| 1 | `build_backtest_artifact` | 0 | 1 | failed |
| 2 | `_formal_bundle` | 0 | 1 | failed |
| 3 | `_validate_formal_inputs` | 0 | 1 | ok |
| 4 | `verify_backtest_plan_artifact` | 0 | 1 | ok |
| 5 | `load_verified_a_share_market_facts` | 0 | 1 | ok |
| 6 | `_formal_config_values` | 0 | 1 | ok |
| 7 | `simulate_formal_a_share_scenario` | 0 | 1 | **failed**（multiplier=`0.5`） |
| 8 | `_formal_scenario_metrics` | 0 | 0 | 未达 |
| 9 | `_formal_parquet_bytes` | 0 | 0 | 未达 |
| 10 | `_formal_scenario_manifest` | 0 | 0 | 未达 |
| 11 | `_validate_formal_readback` | 0 | 0 | 未达 |
| 12 | `write_bytes` | 0 | 10 | ok（链前置 publication） |
| 13 | `read_bytes` | 0 | 6 | ok |
| 14 | `commit` | 0 | 4 | ok |

说明：`write_bytes`/`read_bytes`/`commit` 事件 seq 4–23 发生于 `build_backtest_artifact`（seq 25）之前，对应 honest public-chain fixture 前置 stage publication；非 G7F bundle 内 readback 失败。

---

## 3. 首个失败边界（exact）

来源：`phase_u4_observe.json` → `first_failure` + stdout 公开码。

| 字段 | 值 |
|---|---|
| **boundary** | `simulate_formal_a_share_scenario` |
| **call_n** | `1` |
| **multiplier** | `0.5`（`_SCENARIOS` 首场景 `0p5x`） |
| **exc_type** | `quant.backtest.a_share_simulator.AShareSimulationError` |
| **public code（exception `.code`）** | `null` |
| **cause_none / context_none** | `true` / `true` |
| **CLI 公开码** | `STAGE_BUILD_FAILED` |
| **CLI exit_code** | `5` |
| **传播链（observe 事件序）** | `simulate…/failed` → `_formal_bundle/failed` → `build_backtest_artifact/failed` |

生产只读对照：`simulate_formal_a_share_scenario` 对任意内部异常 `except Exception: pass` 后统一
`raise AShareSimulationError("M3_A_SHARE_SIMULATION_INVALID") from None`（`a_share_simulator.py`），与
observe 的 `cause_none=true` 一致；observer 的 `_public_code` 仅读 `.code` 属性，故 instrument 层 `code=null`
**不**表示无稳定消息字符串。

---

## 4. 现象—根因候选—应遵循规则—最小复现—建议新增测试—通过条件

| 项 | 内容 |
|---|---|
| **现象** | Cleanup 三项 MATCH 并删除；Handshake PASS；Diagnostic `EXIT=1`、`ELAPSED_SEC=4392`；setup 通过；14 边界中 10 有事件；首失败于 `simulate_formal_a_share_scenario` multiplier `0.5`；CLI `STAGE_BUILD_FAILED`。 |
| **根因（工程/fixture，已证明）** | U1 owned 残留已由 U4 exact cleanup 清除；U3 `FileExistsError` 阻断已解除；仪器 U3→U4 生命周期修正有效。 |
| **根因候选（产品/G7E，未证明内部触发点）** | 首场景 formal replay 在 `_simulate_formal_a_share_scenario` 内抛出被吞没的异常，对外仅见 `AShareSimulationError`；其前 `_validate_formal_inputs` / plan / facts / config 均 ok。setup 日志含 LightGBM「0 used features」警告，提示上游 target 可能退化，**不能**单独当作 simulation 失败已证根因。 |
| **应遵循规则** | 禁止重跑 U4 Diagnostic；不得把 instrument `code=null` 写成「无公开码」；不得在本报告宣布 C1/G8/G7F/Gate PASS；返工须先主 Agent 冻结白名单再外部实现—独立初验—主验。 |
| **最小复现（不得在本会话执行）** | 清理后 Windows honest public-chain：`main backtest …` 或同 integration node；期望在 G7F 首场景 `0p5x` 再现 `AShareSimulationError` → CLI `STAGE_BUILD_FAILED`。秒级探针：G7F unit fixture 调 `simulate_formal_a_share_scenario(..., multiplier=Decimal("0.5"))` 对照 honest chain 产物。 |
| **建议新增测试** | （1）G7F unit：honest-chain 衍生最小 plan/facts 上 actual `simulate_formal_a_share_scenario` @0.5x，断言非 `AShareSimulationError` 或捕获允许的内部类型；（2）integration 子集：mock 仅 publication，保留 actual simulation；（3）回归：U4 observe 首失败边界序列稳定。 |
| **通过条件（业务诊断）** | 整数 EXIT + observe 非空且指向首个失败边界 — **本轮已满足**。 |
| **通过条件（产品修复/Gate）** | 需主 Agent 冻结返工 + 外部实现—初验—主验；**本报告不宣布**。 |

---

## 5. 主 Agent 可冻结的最小实现白名单（建议，非本报告授权修改）

| 优先级 | 路径 | 理由 |
|---|---|---|
| P0 | `src/quant/backtest/a_share_simulator.py` | 首失败边界与 hostile swallow 合同 |
| P1 | `src/quant/backtest/a_share_reporting.py`（`_formal_bundle` 场景循环） | 直接调用方；失败传播至 `build_backtest_artifact` |
| P1 | `tests/unit/test_m3_g7f_formal_backtest_artifact.py` | 已有 actual G7E 计数/三场景合同 |
| P2 | `tests/integration/test_m3_g8c_c1_backtest_cli.py` | 端到端 honest chain（返工后） |

**不在首轮白名单**（无 observe 证据）：`backtest_stage.py`、publication primitive、U4 临时 plugin/wrapper。

---

## 6. 秒级回归（定向，非 Gate）

| 命令 | 用途 |
|---|---|
| `D:\Miniforge3\python.exe -m pytest -q tests/unit/test_m3_g7f_formal_backtest_artifact.py` | G7F 合同邻接 |
| `D:\Miniforge3\envs\m3chain312\python.exe -m pytest -q -p no:cacheprovider -p u4_observer_plugin test_u4_handshake.py`（U4 证据目录） | 仪器 handshake 回归 |
| 新增/扩展后：`pytest -q tests/unit/test_m3_g7f_formal_backtest_artifact.py -k "simulate or scenario"` | 首场景 0.5x 探针 |

禁止用以上秒级命令代替已完成的唯一 Diagnostic 或宣布 WSL Gate。

---

## 7. 所有权边界（本报告）

| 允许 | 禁止 |
|---|---|
| 只读 U4 证据、任务单、U3 报告、production/tests（未读 config 正文） | 重跑 Diagnostic/清理；改 production/tests/support/plugin/evidence |
| 写入本唯一报告 + 更新 U4 任务状态 | 联网；add/commit/push；宣布 Gate/产品修复 PASS |

---

## 8. 结论

| 判定 | 结果 |
|---|---|
| U4 owned cleanup | **PASS** |
| U4 Handshake | **PASS** |
| U4 唯一 Diagnostic | **FAIL（业务首失败：`simulate_formal_a_share_scenario` @0.5x）** |
| 相对 U3 进展 | setup 阻断已解除；**首次进入 G7F 业务路径** |
| 主 Agent 下一步 | 冻结 §5 白名单 → 外部实现—独立初验—主验；**禁止重跑 U4 Diagnostic** |

本报告为 U4-B 唯一持久交付。
