# M3 G8C-C1 U3 R1：仪器 Handshake 与单次业务边界诊断报告

日期：2026-08-12  
角色：外部 Cursor `auto` 独立只读取证（U3-B）；未参与 U3-A 仪器准备与主 Agent Diagnostic 托管  
模型：`auto`（不声称具体底层模型）  
UA：UA-AGENT-002 已批准  

结论分层：

| 层 | 判定 |
|---|---|
| 仪器（Handshake / wrapper / exact-node lifecycle） | **PASS** |
| 唯一 Diagnostic（业务首失败边界定位） | **FAIL / 未进入产品路径** |
| 失败落点 | module fixture `setup`：owned config 残留触发 `FileExistsError` |
| G7F 14 业务边界调用次数 | **全部为 0** |
| 能否冻结产品/G7F 根因返工 | **否** |
| 可否重跑本轮 U3 Diagnostic | **否**（已唯一启动并终态明确） |

证据目录（只读核验）：
`C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u3-r1-g8-build-diagnostic\`

脱敏残留元数据（主 Agent 本地生成；本会话未打开 config 正文）：
`C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u3-owned-residue-sanitized.json`

上游：
- [M3_G8C_C1_U3_R1_仪器Handshake与单次业务边界诊断任务单.md](M3_G8C_C1_U3_R1_仪器Handshake与单次业务边界诊断任务单.md)
- [M3_G8C_C1_U2_R1_外置观察插件与单次长链诊断报告.md](M3_G8C_C1_U2_R1_外置观察插件与单次长链诊断报告.md)（仪器缺陷已证明；本轮 U3 修正后 handshake PASS）

---

## 1. 现象（已证明事实）

### 1.1 权威 Handshake（handshake5）PASS

| 字段 | 值 |
|---|---|
| `MODE` | `Handshake` |
| `STATUS` | `FINISHED` |
| `EXIT` | `0` |
| `ELAPSED_SEC` | `1` |
| `SUMMARY` | `sU3_HANDSHAKE_STDOUT_MARKER_a91c2e7b \| 1 passed, 1 skipped in 0.08s` |
| `WRAPPER_PID` / `PYTEST_PID` | `26084` / `20664` |
| `MODEL` | `auto` |
| 权威断言 | `M3_G8C_C1_U3_R1_handshake5_assert2.txt` → `OVERALL=PASS` |

`phase_u3_handshake5_observe.json` 精确含：

- lifecycle：`collection_complete` → `protocol/started` → `install/ok` → `setup/passed` → `call/passed` → `teardown/passed`
- boundary：`ping` `started` + `ok`，`calls=1`
- `first_failure=null`
- skip 用例未阻挡 target observe；无二次安装 / O_EXCL 失败事件

stdout / stderr 分别含已知 marker 且非空（wrapper 排空机制在 handshake 上已验证）。

说明：`handshake5_assert.txt` 曾因 CRLF 行锚点假阴性将 evidence STATUS/EXIT/MODE 判 FAIL；`assert2` 以行切分复核后全部 PASS。权威以 assert2 为准。

### 1.2 唯一 Diagnostic 终态：setup 失败，业务零调用

| 字段 | 值 |
|---|---|
| `MODE` | `Diagnostic` |
| `STATUS` | `FINISHED` |
| `EXIT` | `1` |
| `ELAPSED_SEC` | `5` |
| `START` / `END` | `2026-08-12T13:41:56+08:00` / `2026-08-12T13:42:01+08:00` |
| `WRAPPER_PID` / `PYTEST_PID` | `27444` / `11288` |
| 命令 | 与任务单冻结 Diagnostic 命令一致 |
| Integration SHA | `5ba1d2fcbd14d73627940f0127742f3d44387533e2ab4b6be5bbece8fb8014b2`（工作树复算一致） |

`phase_u3_observe.json` 终态：

```json
{"boundaries":{},"events":[],"first_failure":null,"lifecycle":[
  {"phase":"collection_complete","seq":1,"status":"ok"},
  {"phase":"protocol","seq":2,"status":"started"},
  {"phase":"install","seq":3,"status":"ok"},
  {"phase":"setup","seq":4,"status":"failed"},
  {"phase":"teardown","seq":5,"status":"passed"}
],"model":"auto"}
```

含义（仪器已证明可见）：

1. 精确目标 node 已进入 `pytest_runtest_protocol`；
2. 边界包装 **install ok**（U2 的 O_EXCL/整文件匹配缺陷本轮未复现）；
3. **setup failed** → call 从未发生 → `boundaries={}` / `events=[]` → **G7F 14 业务边界零调用**；
4. 因此 **产品根因仍未进入**，不得把 setup 残留失败写成 G7F/`build_backtest_artifact` 业务缺陷。

stdout 脱敏可读摘要（仅异常类型与栈帧位置；本会话未打开 `_m3_f0r2_chain_session.toml` 正文）：

- module fixture `formal_chain_locator` → `public_formal_chain_session(...)`
- `session.py` no-clobber：`if config_path.exists(): raise FileExistsError(config_path)`
- exact type：`FileExistsError`
- pytest：`1 skipped, 1 error in 3.51s`

stderr 文件长度 0（错误落在 stdout；与 handshake 非空 stderr 对照，不构成 wrapper 排空回归证明失败）。

---

## 2. 文件哈希清单（U3-B 本轮复算 SHA-256）

| 文件 | 长度 | SHA-256 |
|---|---:|---|
| `u3_observer_plugin.py` | 13095 | `c961edd4c4817554e8f68ead3f99b426d7ca3fe4c5b6815bfa6ac3daa663499f` |
| `run_u3_diagnostic.ps1` | 8422 | `a997796bea08c0d57f0b6578a6699d5ae2bfb220ca6dca790c41c685499b410e` |
| `test_u3_handshake.py` | 602 | `e2b99de1f7be49874a6367007787358813b7b66c0cd2f279da8183fa68ffaaa4` |
| `u3_handshake_target.py` | 235 | `21c4b871cb555163a3e72f644e37aa19aa82d1fe74011dbe3f5dfdb917d84291` |
| `u3a_short_static_checks_recheck.txt` | 495 | `01aaea96d4c40c31e69a1bc6fffc4f699e31c8d4b96be32aa006ced0c150c0c8` |
| `M3_G8C_C1_U3_R1_prepare_evidence.txt` | 1293 | `612060fd6bc2923c9e832209782beb2b7eb04aacbf26c7587f93364b55bb92bb` |
| `M3_G8C_C1_U3_R1_handshake5_evidence.txt` | 1517 | `f58b13e50ccc666233fd561da1e1229db89fa6849acd4d22b001dbab283b1bdb` |
| `M3_G8C_C1_U3_R1_handshake5_stdout.txt` | 71 | `2d4433e80d2b2034e60c345fc6e9dd5dbeb39aa8690a895bbbadbd879b8a0dac` |
| `M3_G8C_C1_U3_R1_handshake5_stderr.txt` | 37 | `d6fff1bf0e3c6fc203217322ff488576b4063c7383f5fe07471c21a7711f3435` |
| `M3_G8C_C1_U3_R1_handshake5_assert2.txt` | 549 | `6e2566cb76d7ef722285e0cf88f89de6c89d9742db1c731c2f76fc5cf5d213df` |
| `phase_u3_handshake5_observe.json` | 642 | `3980e1e2f034efade8e5a79615a2af306be00ebb9c49290259083297d943416c` |
| `M3_G8C_C1_U3_R1_diagnostic_evidence.txt` | 1707 | `2f4ca0826922888f5c2dea2fc474f29399588efb725832c22d7db7fee52a4847` |
| `M3_G8C_C1_U3_R1_diagnostic_stdout.txt` | 2335 | `c999569408b16db668354c08bb481a6621086c661f24cc782840c9e9ed6841da` |
| `M3_G8C_C1_U3_R1_diagnostic_stderr.txt` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `phase_u3_observe.json` | 314 | `293a23772f4f8beb799672d75400c365acc21d9223bbf03694e72727f2c4e386` |
| `tests/integration/test_m3_g8c_c1_backtest_cli.py` | 4963 | `5ba1d2fcbd14d73627940f0127742f3d44387533e2ab4b6be5bbece8fb8014b2` |

prepare / handshake5 / diagnostic evidence 内记载的 plugin、wrapper、integration SHA 与上表一致。  
本会话未修改 production / tests / support / plugin / evidence；未联网；未 add/commit/push。

---

## 3. 只读审计要点

### 3.1 仪器合同（相对 U2 缺陷的修正）— PASS

| 合同项 | 证据 |
|---|---|
| exact nodeid（非整文件） | plugin `_DIAG_NODE` / `_HS_NODE`；Diagnostic observe 仅在 Windows happy-path protocol 创建 |
| `pytest_runtest_protocol` + install once | handshake/diagnostic lifecycle 均有 `install/ok`；skip 不创建 diag observe |
| wrapper 双模式 + 排空 | `WaitForExit(timeout)` 后无参 `WaitForExit()`；handshake stdout/stderr marker 非空 |
| 14 边界名 | short static recheck `BOUNDARIES=14` / `boundaries14=PASS` |
| 脱敏 | observe 无路径/异常文本/秘密字段 |
| 未在 U3-A 启动真链 | prepare `REAL_CHAIN_STARTED=NO`；权威 handshake 时 diag 文件尚不存在 |

### 3.2 支持层清理协议（只读 `session.py`，非秘密）

`tests/support/m3_formal_public_chain/session.py`：

- 创建顺序：`stage_root` → `g1_release_root` → `_write_owned_config`；
- 每次创建后立即 `_record_owned`（`lstat` → `(dev, ino, kind)`）；
- `finally` 仅删除 **token 仍匹配** 的 owned 实体；link/reparse/type/dev-ino 漂移则 skip；
- config 路径固定 `configs/research/_m3_f0r2_chain_session.toml`，存在即 `FileExistsError`（no-clobber）；
- U1 证据链与脱敏 JSON 一致表明：U1 pytest 启动后创建了三项 owned 实体，但 **缺 finally teardown**，残留挡住后续 session。

### 3.3 为何「无法进入第一个业务边界」（本轮，已证明）

**已证明：**

1. 仪器可用：handshake PASS；Diagnostic `install/ok` + `setup/failed` 可审计。
2. 失败点在 **module fixture setup**，exact type `FileExistsError`，触发点为 owned config 路径已存在。
3. `ELAPSED_SEC=5` + 空 `boundaries/events` 与「未进入 `build_backtest_artifact` / G7F 内部」相容。
4. 因此首个可定位失败边界是 **fixture/session no-clobber（owned residue）**，不是 G7F 14 业务包装点。

**未证明（禁止当作结论）：**

- G7F/G7E/G7D 业务缺陷、publication/readback 缺陷、任一业务 boundary 的 exception type/public code；
- C1 R3 `STAGE_BUILD_FAILED` 的内部阶段定位。

---

## 4. Owned 残留 ownership 置信度（仅用脱敏 JSON + 元数据；未读 config 正文）

对照 `m3-g8c-c1-u3-owned-residue-sanitized.json`，并对三项做 **元数据级** 复核（路径存在性、length/SHA、目录属性、reparse 位、时间线；**不**读取 config 内容、**不**遍历 stage/G1 业务内容）。

| 检查项 | config | stage_root | g1_release_root |
|---|---|---|---|
| exact path / shape | `configs/research/_m3_f0r2_chain_session.toml` 精确存在 | 唯一 `_f0r2_<12-hex>`，path_sha256=`d8e1ea97…963ed` 与 JSON 一致 | 唯一 `<64-hex>`，name_sha256=`d4b4ba5b…06a0` 与 JSON 一致 |
| lstat regular / dir | regular file；len=7184 | directory | directory |
| nonlink / non-reparse | `reparse=False`；无 LinkType | `reparse=False` | `reparse=False` |
| SHA / creation timeline | sha256=`cd01fd63…f5d1`；created=last_write=`2026-08-12T11:56:07.2970305+08:00` | created=`11:47:52`；last_write=`12:06:22` | created=`11:55:48`；last_write=`11:55:51` |
| config 生成器 match | JSON：`exact_support_generator_match=true` → `session.py::_write_owned_config`（未读正文验证；以脱敏声明 + SHA 稳定为准） | — | — |
| stage reference | — | JSON：`referenced_by_generated_config=true` | — |
| G1 窗口唯一性 | — | — | JSON + 现地：`only_release_created_in_u1_window`；当前匹配目录数=1 |
| 创建顺序 vs U1 窗口 | config 晚于 stage/g1；均在 `u1_pytest_started_at=11:47:40` 之后 | 同左 | 同左 |

**ownership 置信度：三项均为高置信 U1 owned-fixture 残留。**  
**删除前置（任一漂移即不删）：**

1. 删除前再次核对 exact path/shape、regular/dir、nonlink/non-reparse、config SHA+length、stage path_sha、g1 name_sha、时间线未被人/他进程替换；
2. 仅删除这三项目标；禁止通配、禁止 `rmtree` 上级、禁止触碰非匹配 release/stage；
3. 删除实现应镜像 support 合同：按 path 深度逆序、删除前二次 `lstat` identity；漂移 → skip 并 FAIL，不强删；
4. 本 U3-B **不执行清理**；亦不得在本报告后无 U4 合同擅自删除。

---

## 5. 现象—根因—规则—最小复现—测试建议—通过条件

| 项 | 内容 |
|---|---|
| **现象** | Handshake PASS；唯一 Diagnostic `EXIT=1`、`ELAPSED_SEC=5`；observe：`install/ok` + `setup/failed`；14 边界零事件；stdout 显示 config 路径 `FileExistsError`。 |
| **根因（工程/fixture，已证明）** | U1 owned session 缺 finally cleanup，残留 `configs/research/_m3_f0r2_chain_session.toml`（及配套 stage/G1）使 `public_formal_chain_session` no-clobber 在 module setup 失败；业务 call 未达。 |
| **根因（产品/G7F，未证明）** | 无。 |
| **应遵循规则** | 禁止重跑已启动的 U3 Diagnostic；不得用 setup 残留失败推断 G7F；删除必须 exact-target + identity 校验；任何漂移不删；诊断与清理职责分离。 |
| **最小复现（不得在本会话执行）** | 在 owned config 仍存在时进入 `public_formal_chain_session` → 期望 `FileExistsError`；清理且 identity 未漂移后，新临时仪器目录 handshake PASS，再允许一次新 Diagnostic。 |
| **新增测试建议** | （1）fixture 中断/缺 teardown 后的 owned residue 检测与拒绝启动；（2）cleanup 对 token 漂移 skip；（3）U4 后新轮 Diagnostic 必须先 handshake，且 observe 至少出现 call 期边界事件或可审计的业务 setup 之后失败。 |
| **通过条件（业务诊断）** | 新一轮（非重跑 U3）唯一 Diagnostic：整数 EXIT + observe 显示 call 已进入或业务边界事件非空，能指出首个失败业务边界 **或** 用完整事件证明无法区分。本轮 **未满足**。 |
| **通过条件（产品修复冻结）** | 须以上业务证据；本轮 **不可冻结**。 |

---

## 6. 冻结的 U4 建议（本会话不创建 U4 文件、不执行清理）

1. **先**由全新外部 Cursor 准备 **只读核对 + 精确删除计划**（白名单仅三项 owned 目标；写清 pre-delete identity 检查清单与回滚/中止条件）；  
2. **主 Agent 审核**计划与脱敏证据一致后，方可授权执行精确 owned cleanup；  
3. 清理后：**新临时仪器目录**（no-clobber）+ 秒级 handshake + **唯一**新 Diagnostic；**禁止重跑 U3**；  
4. 新 Diagnostic 仍走「外部准备 → 主托管真链 → 另一外部只读取证」；  
5. 在未拿到业务边界事件前，不得冻结 G7F/C1 产品返工，不得宣布 Gate。

---

## 7. 所有权边界（本报告）

| 允许 | 禁止 |
|---|---|
| 只读 U3 证据、任务单、U2 报告、脱敏 JSON、`session.py` 非秘密清理协议 | 打开/复制/发送 `_m3_f0r2_chain_session.toml` 正文 |
| 写入本唯一报告 + 更新 U3 任务状态 | 修改/删除残留 config、stage、G1、production、tests、support、plugin、evidence |
| 结论区分仪器 PASS vs 业务未进入 | 运行 pytest/长链；联网；add/commit/push；创建 U4 文件；执行清理；重跑 U3 |

---

## 8. 结论

| 判定 | 结果 |
|---|---|
| U3 仪器 Handshake | **PASS** |
| U3 唯一 Diagnostic（定位 `build_backtest_artifact` 内首个业务失败边界） | **FAIL（setup owned-residue；业务零调用）** |
| 能否冻结产品/最小实现返工 | **否** |
| 下一步 | 主 Agent 冻结 **U4**：外部只读删除计划 → 主审核 → 精确 owned cleanup → 新仪器目录 handshake → 唯一新 Diagnostic（不得重跑 U3） |

本报告为 U3-B 唯一持久交付。
