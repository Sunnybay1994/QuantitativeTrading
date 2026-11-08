| 字段 | 内容 |
| --- | --- |
| 现象 | VALIDATION7：Parser、argv sentinel、exact-worktree identity **PASS**；focused exact3 **21 passed / 2 failed**（REWORK11 authority 分域已越过统一 fixture 失败）。Ruff、mypy、cold、scope **UNRUN**。证据根 `artifacts/agent_runs/m3-r2s-validation7-20260826T030000/`；focused stdout SHA-256 `20df397adf95fcc18f13320290dc2fdb2dd95e1f18a46ddc963f0da53d3d757b`；stage summary SHA-256 `a7ff660e5083a589a996bbbd0ada2f1ec85aab703e4ec490eb397be306d190b3`。 |
| 根因 1 | `test_temp_leaf_exact_ownership_...` 硬编码 `model_version="v1"`，与 bundle 真实 model/version 不闭合；temp leaf 校验通过后在 evaluation identity closure 失败。 |
| 根因 2 | `test_plan_selection_..._publication_drift` 误把 `selected[0]` 当 h5；`select_run_plan_nodes` 按 node-id 字典序返回，`summary.h10...` 排在 `summary.h5...` 前，篡改落在错误节点，无法稳定证明目标 horizon 拒绝。 |
| 规则 | §21：temp 正向 identity 必须用 `bundle["model_version"]` 且 node-id 断言同步；publication drift 按 exact node_id 或 `horizon == 5` 唯一定位，保持完整 plan closure；显式锁 h5/h10 分别定位、非目标 horizon 篡改不得冒充当前 horizon 失败、目标 model_version 目录漂移稳定拒绝；**不改** production `_select_canonical_summary_node` / `__post_init__` / temp / verifier。 |
| 最小复现 | 硬编码 v1 → legal temp 构建失败；`selected[0]`+h5 path 篡改 → horizon=5 选到未篡改 h5 而不 raise。 |
| 修正测试 | 仅 `tests/unit/test_m3_summary_stage.py`：temp 用例改真实 model_version；新增 `_unique_summary_plan_node`；publication drift 按 horizon/node_id 定位并补 h5/h10 分域反例。production / 另两 tests / 任务书 / review **未改**。 |
| 通过条件 | 两失败用例按合同闭合；STATIC_ONLY 未跑验证命令；不得把 VALIDATION8/Ruff/mypy/cold 写成通过。 |

## 18. VALIDATION8 完整证据（Windows 工程验证闭合）

经理授权 `EVIDENCE_UPDATE_GRANTED`。状态仅：`R2S_WINDOWS_ENGINEERING_VALIDATED`。

**明确未闭合**：R2A、bridge/CLI、actual worker、真实 Qlib、new root、retained、acceptance、目标终态 `FORMAL_SUMMARY_STAGE_PUBLICATION_COMPAT_VALIDATED`、M3 Gate。

### 18.1 证据根与阶段

- evidence root：`artifacts/agent_runs/m3-r2s-validation8-20260826T032000/`
- Parser / argv sentinel / exact-worktree identity：**PASS**
- focused exact3：**23 passed** / 39788 warnings / 468.67s
- Ruff：prod2 + tests3 **PASS**
- mypy：prod2 **PASS**
- cold import：prod2 exact **PASS**
- scope：exact8 / cached0 / diff-check **PASS**
- 收口：temp/cache 清；退出后 `0xF00` 清；writer PID 7692 / affinity `0x3` 不动

### 18.2 阶段 stdout SHA-256

| 阶段 | SHA-256 |
| --- | --- |
| stage summary | `3ff04d776f24b7216abef4eeccad369359ca74c9289743a535ca2cc4dc2e0548` |
| focused exact3 | `fb81b7192ad1cfe7d16709ca518ad72e36eaa9a3a953591956383b55f48165bd` |
| Ruff | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| mypy | `0c37c4158c91ef55c724ba017bf6465f26018199badb08e3ff13f98acdf056c2` |
| cold | `f72afd3366044b97ee5b46c7f235170a4f0b894255e77f4e87637109e1428279` |
| scope | `abc60e7b60096a8448aa986dca214b6dde7ab99cc5db87a39b0baa06c35da8a2` |

### 18.3 逐轮边界索引（历史不改写）

| 轮次 | 边界 |
| --- | --- |
| VALIDATION1 | carrier **invalid** |
| VALIDATION2 | **9 passed / 14 failed**（F4；见 §11） |
| VALIDATION3 | **18 passed / 5 failed**（F5；见 §12） |
| VALIDATION4 | **9 passed / 14 failed**（F6；见 §13） |
| VALIDATION5 | **9 passed / 14 failed**（§19；见 §15） |
| VALIDATION6 | **9 passed / 14 failed**（§20；见 §16） |
| VALIDATION7 | **21 passed / 2 failed**（§21；见 §17） |
| VALIDATION8 | 完整 PASS（本节目） |

§11–§17 正文证据与 STOP 边界保持原样。

## 19. 终态声明

- 历史交付与 VALIDATION1 carrier invalid、VALIDATION2–7 真实边界、§21 测试修复均保留。
- 本轮仅更新任务书与本 delivery；**未改** production、tests、review、evidence 目录。
- 终态：`R2S_WINDOWS_ENGINEERING_VALIDATED`（VALIDATION8）；**不是** R2A / bridge / CLI / actual worker / 真实 Qlib / new root / retained / M3 Gate 闭合。
