# M3 G8C-C0 F0 R3：续跑 Provider 至 Resolver 交付报告

日期：2026-08-11  
角色：外部实现 Agent（`cursor-grok-4.5-high`，全新会话）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
解释器：`D:\Miniforge3\envs\m3chain312\python.exe`（`PYTHONPATH=src`；实测 `st_nlink=2`）  
任务单：[`M3_G8C_C0_F0_R3_续跑Provider至Resolver任务单.md`](M3_G8C_C0_F0_R3_续跑Provider至Resolver任务单.md)  
结论：**Windows 诚实 public formal chain support 工程合同自测 PASS；不宣称 C0/C1/Linux Gate PASS；待独立初验**

## 1. 白名单与实际改动

| 路径 | 处置 |
|---|---|
| `tests/support/m3_formal_public_chain/__init__.py` | 复用（未改职责） |
| `tests/support/m3_formal_public_chain/g1_inputs.py` | 复用（未改） |
| `tests/support/m3_formal_public_chain/session.py` | 最小修正：hostile 后刷新 session config entity token，保证 owned-only 清理 |
| `tests/support/m3_formal_public_chain/stage_chain.py` | 最小修正：`_rcpt.scope` 标注 `Literal[...]`（mypy） |
| `tests/integration/test_m3_g8c_c0_formal_cli_resolve.py` | top-level verifier order 观察；补 runtime/cross-platform hostile；零写基线 |
| 本交付报告 | 新增 |
| 任务单状态 | 更新为待独立初验 |

support 合计 **1141 行**（≤1300，模块数=4）。未改 production / F2 tests / unit / config / pyproject；未 add/commit；未联网。

## 2. 冻结边界与已用确定性 worker

| 项 | 说明 |
|---|---|
| F2 Windows current-exe handle | 只读复用；`materialize_qlib_provider(python_executable=sys.executable)` 在 nlink=2 下通过 |
| Alpha158 external worker | 仅拦截 `build-alpha158-formal` argv；dump/validate 仍真实 subprocess |
| LightGBM | 真实训练进程（setup stdout 有 LightGBM warning）；未 fake |
| Verified 值 | 全部来自 public builder/publisher/verifier；无 SimpleNamespace / replace verified |

## 3. Integration 完成条件映射

| 条件 | 证据 |
|---|---|
| G1→backtest_plan actual public chain | module fixture 成功；终态 pytest **5 passed, 1 skipped** |
| exact resolver + 可绑定 `run_formal_backtest_stage` | happy-path PASS；未跑 StageRunner |
| resolver 前后零写；第二次只读等价 | happy-path 双次 `_profile_verifiers` + tree signature |
| verifier exact-once/order | `sys.setprofile` **depth-0** 观察 13 名依次 exact-once；嵌套 upstream re-verify 为静态预期（见 §5） |
| receipt 缺失 / config 实体替换 / runtime code_version 漂移 / dependency_fingerprint 跨平台模拟 | 四个 hostile 均 `FormalCliResolveError`、`__cause__ is None`、零写 |
| WSL capability | Windows 上 skip；非 PASS |

## 4. 验证终态

| 检查 | 结果 |
|---|---|
| Windows actual integration（终轮） | **5 passed, 1 skipped**；墙钟 **6539.56s**（<7200） |
| Ruff（support+integration） | All checks passed |
| mypy（`--follow-imports=silent`，`PYTHONPATH/MYPYPATH=src`） | Success: 5 source files |
| cold import | PASS |
| owned cleanup | 终态无 `_f0r*` stage、无 session config、无 G1 residual |

长链轮次（均单次、自然结束后才修正）：

1. 首轮：链成功；order 断言因嵌套 verifier 失败（1 failed / 2 passed / 1 skipped，4699s）  
2. 次轮：happy/missing/config PASS；新增 drift 零写基线取错（2 failed，6587s）  
3. 终轮：全部 PASS（6539s）

过程文件计数（首轮中间快照，owned 已清）：snapshot≈302；provider≈2103；provider-validation=2；receipts 含 backtest_plan。

## 5. Verifier 观察限制（诚实记录）

`formal_cli_resolve` / 各 artifact verifier 在顶层调用后会递归 re-verify upstream，故裸 `setprofile` 会看到远多于 13 次的同名 call。本轮合同采用：

- **actual**：depth-0 进入 13 个 contracted 名，顺序与 `_VERIFY_ORDER` 一致，各一次；  
- **静态映射**：嵌套同名 call 来自 upstream re-verify，不算 resolver 顶层二次调用。

未 wrap/patch production verifier。

## 6. 禁止项自检

| 项 | 本轮 |
|---|---|
| fake verifier / private issuer / SimpleNamespace / replace verified | 未做 |
| production / F2 monkeypatch | 未做 |
| 固定 runtime/dependency/provider identity | 未做 |
| 正式 data / 长期 bytes / 联网 / StageRunner | 未做 |
| 第五 support 模块 / >1300 行 | 未触发（1141） |

## 7. 非声明

- **可**声明：Windows 诚实 public formal chain support 工程合同自测 PASS（待独立初验）  
- **不**宣称 C0 resolver 整体主验 / C1 / Linux ext4 Gate PASS  
- 独立初验必须另开全新会话自跑 actual happy-path，并追加未用 hostile

## 8. 给独立初验

唯一报告：`docs/agent/M3_G8C_C0_F0_R3_续跑Provider至Resolver独立复验报告.md`  
解释器 exact `D:\Miniforge3\envs\m3chain312\python.exe`，`PYTHONPATH=src`，cwd=本 worktree。  
production / F2 / 实现测试只读；仅写独立报告。
