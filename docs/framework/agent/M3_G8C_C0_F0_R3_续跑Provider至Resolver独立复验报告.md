# M3 G8C-C0 F0 R3：续跑 Provider 至 Resolver 独立复验报告

日期：2026-08-11  
角色：外部独立初验 Agent（`cursor-grok-4.5-high`，全新上下文；未参与实现）  
工作树：`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m3-g4-formal`  
解释器：exact `D:\Miniforge3\envs\m3chain312\python.exe`（实测 `st_nlink=2`；`PYTHONPATH=src`；cwd=worktree）  
任务单：[`M3_G8C_C0_F0_R3_续跑Provider至Resolver任务单.md`](M3_G8C_C0_F0_R3_续跑Provider至Resolver任务单.md)  
交付报告：[`M3_G8C_C0_F0_R3_续跑Provider至Resolver交付报告.md`](M3_G8C_C0_F0_R3_续跑Provider至Resolver交付报告.md)

## 结论

**PASS** — 仅允许进入主验。  
不宣称 C0 resolver 整体主验 / C1 / WSL·Linux·ext4 Gate PASS。

## 1. 角色与只读边界

- 生产代码、`tests/support/m3_formal_public_chain` 四模块、`tests/integration/test_m3_g8c_c0_formal_cli_resolve.py`、任务单与交付报告：**只读**。
- 未修复、未格式化、未 add/commit、未联网、未用正式 data / 私有 capability。
- 唯一写入：本报告。临时探针仅系统 TEMP，结束后已清理脚本与交叉 root 目录。

## 2. 静态核对（对照任务单 / 交付报告）

| 项 | 结果 |
|---|---|
| support 模块数=4 | PASS：`__init__.py` / `g1_inputs.py` / `session.py` / `stage_chain.py` |
| 总行数 ≤1300 | PASS：**1141**（15+60+249+817） |
| public builder/publisher/verifier 来源 | PASS：G1→snapshot→provider→…→backtest_plan 均调用 `quant.*` public API；verified 来自对应 `verify_*` |
| 无 fake verifier / private issuer / SimpleNamespace / `object.__new__` / `object.__setattr__` / replace verified / production monkeypatch | PASS（白名单内无匹配；`dataclasses.replace` 仅用于 G1 raw inputs） |
| Alpha158 deterministic worker | PASS：仅拦截 `build-alpha158-formal` argv；其余 `subprocess.run` 透传；测试侧临时替换并 `finally` 恢复 |
| LightGBM | PASS：真实训练进程（adversarial/official stdout 均有 LightGBM warning） |
| owned cleanup | PASS：entity token + owned-only；hostile 后刷新 session config token；两轮终态无 `_f0r*` / 无 session config |
| verifier depth-0 exact-once/order 口径 | PASS（诚实）：`sys.setprofile` 仅计 contracted 13 名 **depth-0**；嵌套 upstream re-verify 以静态预期记录，未 wrap production |
| 固定 runtime/dependency/provider **artifact** identity | PASS：链上 `code_version` / dependency / provider fingerprint 取自当前 `compute_m3_runtime_identity` / `build_provider_runtime_fingerprint` |
| env 预检固定 provider fingerprint SHA | 见 §7 未决边界（R2 写前漂移门；非本轮伪造 verified） |

## 3. Windows actual integration（单次、自然终态）

命令（单次，未重跑）：

```text
$env:PYTHONPATH='src'
D:\Miniforge3\envs\m3chain312\python.exe -m pytest tests/integration/test_m3_g8c_c0_formal_cli_resolve.py -q --tb=line
```

| 字段 | 实测 |
|---|---|
| 结果 | **5 passed, 1 skipped**（`.....s`） |
| EXIT | 0 |
| pytest 墙钟 | **7276.71s**（2:01:16） |
| shell elapsed | 7285944 ms |
| skipped | `test_wsl_capability_gate_skips_before_chain_writes`（win32 skip；非 PASS） |
| happy path | module fixture 真实 G1→snapshot→provider→provider-validation→experiment→label/folds/feature→alignment→model→prediction→target→backtest_plan，再 resolver；未跑 StageRunner |
| 无效/重跑命令 | **无**（integration 仅启动一次） |

说明：交付报告终轮为 6539.56s；本独立复验同合同绿但墙钟 **>7200**。已遵守“必须自然终态、不重复启动”，未在 7200 处强杀。是否将硬预算视为 Gate 条件交主验（§7）。

附加：大量 pandera DeprecationWarning；`.pytest_cache` WinError 5（Access denied）——未写入工作树残留。

## 4. 独立对抗（实现者未使用；TEMP pytest）

脚本：`%TEMP%\m3_g8c_c0_f0_r3_indep_adversarial.py`（跑完已删）。  
另建 `public_formal_chain_session`（全 public chain），**未**改只读测试文件。

| 对抗 | 相对实现者 | 结果 |
|---|---|---|
| 同 bytes plan receipt 实体替换（unlink+同字节写回→新 inode） | 实现者只测缺失 / 不同字节 config | `same_bytes_plan_receipt_accepted=True`（内容哈希路径接受）；resolve 后零写 |
| config hardlink path alias（`os.link`→`st_nlink>=2`） | 未用 | **fail-closed** + `__cause__/__context__ is None` + stage 零写 |
| 跨 root `project_root`（TEMP 空壳树） | 未用 | **fail-closed** + 脱敏 + owned stage 零写 |
| 损坏 receipt + 递归 cause/context/traceback 脱敏（含 SECRET 载荷） | 实现者仅 `__cause__ is None` | **fail-closed**；无 SECRET 泄漏；二次 resolve 仍零写 |
| 完好链 resolve 前后 G1/stage 完全零写 | 独立于 profile happy-path | PASS |

汇总：**5 passed** in **6316.94s**；EXIT=0。至少一个有效未用对抗成立（config hardlink 为确定性 fail-closed）。

## 5. 定向静态 / 冷导入 / 残留

| 检查 | 结果 |
|---|---|
| Ruff（support+integration） | All checks passed |
| mypy `--follow-imports=silent`（`PYTHONPATH/MYPYPATH=src`） | Success: 5 source files |
| cold import（formal_cli_resolve + 四 support） | PASS；无 top-level `qlib`/`lightgbm`/`mlflow`/`lgb` 包冷导入 |
| owned 残留（两轮后） | none（无 `_f0r*` stage、无 `_m3_f0r2_chain_session.toml`） |
| 工作树临时探针残留 | none |

## 6. WSL 只读轻探针（非 Gate）

| 环境 | `platform_supports_renameat2_noreplace()` |
|---|---|
| WSL Miniforge `base` | `False` |
| WSL Miniforge `py312` | `False` |

仅 capability/skip 语义；**不**把 skip 当 PASS；**不**宣称 Linux/ext4/C0/C1。

## 7. 未决边界（供主验）

1. **墙钟预算**：独立 actual integration **7276.71s > 7200**；功能绿且自然终态。主验需裁定 7200 是否硬门禁。
2. **同 bytes plan receipt**：独立探针显示 content-equivalent 实体重写可被接受；R3 合同强制项仍是 receipt 缺失与 config 实体/内容绑定。是否要求 receipt 也绑 inode 属 C0 主验范围，本轮不据此 FAIL。
3. **session 预检固定 provider fingerprint SHA**：写前环境门（R2 延续）；与“artifact identity 取当前 public 返回值”并存。交付“未做固定 provider identity”按 artifact 口径可接受，但主验应知悉该 SHA 锁。
4. Windows 证据不得外推 WSL/Linux Gate。

## 8. 映射任务完成条件

| 条件 | 独立证据 |
|---|---|
| actual public chain→backtest_plan + public verified | §3 fixture 绿 |
| exact resolver、可绑定 stage、不跑 StageRunner | happy-path PASS |
| resolver 前后零写；二次只读等价 | happy-path + 独立零写对抗 |
| verifier depth-0 13 exact-once/order | 静态+测试实现口径诚实；actual 绿 |
| 缺失/config/runtime/跨平台 hostile | 实现者四测绿；独立 hardlink/跨 root/脱敏补充 |
| WSL capability skip 非 PASS | win32 skip + WSL False 探针 |

---

**最终：PASS（只允许进入主验）。**
