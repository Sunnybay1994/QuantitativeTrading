# M3 G8C-C0 F0 R2：Windows 诚实 Formal Public Chain Support 交付报告

日期：2026-08-11  
角色：外部实现 Agent（`cursor-grok-4.5-high`，全新会话）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
解释器：`D:\Miniforge3\envs\m3chain312\python.exe`  
任务单：[`M3_G8C_C0_F0_R2_Windows诚实FormalPublicChainSupport任务单.md`](M3_G8C_C0_F0_R2_Windows诚实FormalPublicChainSupport任务单.md)  
结论：**按 §8 停止条件诚实停止；不宣称 F0/C0/C1/Gate PASS**

## 1. 白名单与实际改动

| 路径 | 处置 |
|---|---|
| `tests/support/m3_formal_public_chain/__init__.py` | 新增（15 行） |
| `tests/support/m3_formal_public_chain/session.py` | 新增（247 行） |
| `tests/support/m3_formal_public_chain/g1_inputs.py` | 新增（60 行） |
| `tests/support/m3_formal_public_chain/stage_chain.py` | 新增（817 行） |
| `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py` | 替换永久 stop skip → actual/hostile/WSL gate |
| 本交付报告 | 新增 |
| 任务单状态 | 更新为停止 |

support 合计 **1139 行**（≤1300，模块数=4）。未改 production/config/pyproject/既有 G1–G8 tests；未 add/commit；未联网。

## 2. 已通过的前置证据（写链过程中）

| 项 | 结果 |
|---|---|
| Windows `platform_supports_renameat2_noreplace()` | True |
| `build_provider_runtime_fingerprint().sha256` | `8f1148c7…5cc227`（与 F1 一致） |
| public `publish_g1_release` + `verify_g1_release` | PASS；exact 18 文件、无 receipt；扩展 history=40 / signal≈23 日 |
| owned config copy + `load_m3_config` | PASS（cross-section=5、top_k=5、embargo=10） |
| public snapshot build/request/receipt/verify | 到达 provider 前已成功（两轮 integration setup） |
| WSL/non-Windows capability gate | 在零链写入前 `pytest.skip`（DrvFS `supports=False`） |
| owned-only cleanup | 失败 teardown 后无 `_f0r2_*` / session config / G1 residual |
| Ruff（support+integration） | All checks passed |
| 确定性 Alpha158 worker 边界 | 已实现（仅拦截 `build-alpha158-formal`；dump/validate 仍走真实 subprocess） |

## 3. 停止条件（硬阻断）

现象：`materialize_qlib_provider` → `PROVIDER_INPUT_INVALID`；探针还原底层为  
`ValueError("regular unlinked file required")`。

根因：

1. `provider._validate_preflight` 对 `python_executable` 调用 `_read_regular`，要求 `st_nlink == 1`。
2. `D:\Miniforge3\envs\m3chain312\python.exe`（即 `sys.executable`）实测 **`st_nlink=2`**（conda 硬链接布局）；同环境其他 `python*.exe` 亦为 nlink=2。
3. 同预检还要求 `python_executable.resolve() == Path(sys.executable).resolve()`，因此不能改用副本/其他解释器绕过。

应遵循规则：任务 §8「任何真实 production API/schema 冲突 → 立即停止」；禁止 monkeypatch production builder/verifier/`_read_regular`。

最小复现（m3chain312）：

```text
os.lstat(sys.executable).st_nlink == 2
quant.research.m3.provider._read_regular(Path(sys.executable))
  -> ValueError("regular unlinked file required")
```

通过条件（需主 Agent 重冻，本 Agent 不扩权）：

- 放宽 production `_read_regular` 对 **interpreter 可执行文件** 的 `st_nlink==1` 约束；或  
- 提供 Windows 下 nlink=1 且仍等于 `sys.executable` resolve 身份的解释器合同；或  
- 另冻允许的公共兼容边界（非私有 monkeypatch）。

## 4. 验证终态

| 检查 | 终态 |
|---|---|
| Windows actual public chain + C0 integration | **未完整 PASS**（停于 provider preflight） |
| pytest integration（windows/missing/config） | 3 ERROR at fixture setup（同上根因） |
| WSL capability skip | 写入前 skip（非 PASS） |
| 长链墙钟 | 单轮 setup ≈8–9 min（G1+snapshot）；未超 7200s；低频等待、未重复开链 |

## 5. 禁止项自检

| 项 | 本轮 |
|---|---|
| fake verifier / SimpleNamespace / replace verified | 未做 |
| 固定 code/dependency/provider identity | 未做（取当前 runtime/fingerprint） |
| monkeypatch `_renameat2_noreplace` / production builder | 未做 |
| 读根项目正式 data / 长期 bytes / 联网 / MLflow | 未做 |
| StageRunner / G7F / tracking / CLI | 未跑 |

## 6. 非声明

- **不**宣称「Windows 诚实 public formal chain test support 工程合同 PASS」
- **不**宣称 C0 integration / C1 / Linux ext4 / Gate PASS
- 13 verifier once/order 与 resolver happy-path **未闭合**

## 7. 给主 Agent / 下一步

1. 复核：Windows conda `python.exe` nlink=2 与 `provider._read_regular` 的 nlink==1 合同互斥。
2. 重冻 production 预检或 F0 解释器合同后，再开外部实现续跑 provider→backtest_plan→resolver。
3. 现有 support 白名单实现可复用（G1/snapshot/session/cleanup/integration 骨架已在）；续跑时勿重复造链。
4. 独立初验：本轮无完整 actual happy-path；若主 Agent 接受停止证据，初验应核对「未伪造 provider、未改 production」。
