# M3 G1 R1B / R1C-A 主验返工独立初验报告

日期：2026-07-17  
角色：全新外部独立初验 Agent（未参与两轮实现）  
模型：按任务要求使用非 fast 独立会话（本报告不宣称具体底层模型名之外的 Gate 结论）  
范围：只读核对生产代码与实现者测试；**仅写本报告**  
结论：**F1–F4 本轮全部成立，可交主 Agent 复验**  
声明：**不宣布 R1B / R1C / G1 / Gate 通过**；不启动 R1C-B；未跑全量 pytest；未联网 / 未读 token / 未访问 archive 与 data legacy；未 git init。

前置链接：

- [`M3_G1_R1B_R1C-A主Agent终验报告.md`](M3_G1_R1B_R1C-A主Agent终验报告.md)
- [`M3_G1_R1B_R1C-A主验返工任务单.md`](M3_G1_R1B_R1C-A主验返工任务单.md)
- [`M3_G1_R1B_R1C-A主验返工交付报告.md`](M3_G1_R1B_R1C-A主验返工交付报告.md)

---

## 1. 初验边界与方法

- 完整阅读 `AGENTS.md`、主验报告、返工任务单、交付报告，以及当前 `g1_workflow.py` / `run_g1.py` 与两个目标测试。
- 逐条核对 F1–F4；对抗只用 **小型 fresh + INDEX**，**未**重跑 300 成分 / 1205 history 完整五段链。
- 生产代码与实现者测试严格只读；命令均在 WSL `/mnt/g/BaiduSyncdisk/wsl/Cursor/quant`，`/home/mabw/miniforge3/bin/conda run -n base`。

---

## 2. F1–F4 逐条核对

### F1 `VerifiedG1WorkflowStateV1` 自证 — 成立

| 核对项 | 证据 |
|---|---|
| `__post_init__` 调 `_validate_workflow_state_closure` | `g1_workflow.py` `:221–259`、`:762–891` |
| INDEX 未完成：产物全空 + counts 为 plan totals（history/ref/symbols=0） | `:772–791` |
| INDEX 完成：index responses exact-id 顺序闭包 + derived 必有 | `:793–800` |
| HISTORY 未完成不得提前 history/ref/candidate/prepared/published | `:805–822` |
| HISTORY 完成必须有 candidate；REFERENCE/PREPARE/PUBLISH 双向产物 | `:824–891` |
| counts 永远是 verified plan totals，非 receipt 完成数 | 各分支构造 `G1WorkflowCountsV1` 后与 `state.counts` 相等比较 |
| 失败为稳定 `ValueError`，无 IO/联网/目录扫描 | 闭包内仅 plan 派生计算；异常统一 `ValueError` 文案 |
| 实现者测试覆盖 P0-A 与任务单 §2 所列反例（fresh/INDEX） | `test_verified_state_self_proof_bidirectional_closure` |

主验 P0-A 复现路径：`dataclasses.replace(..., completed_stages=("INDEX","HISTORY"))` 在 fresh/INDEX 上均 `ValueError`（实现者测试 + 本轮对抗）。

### F2 `G1CliResultV1` 自证 — 成立

| 核对项 | 证据 |
|---|---|
| 非空 digest：`type is str` + 小写裸 64 hex | `run_g1.py` `:182–187`（拒绝 bool/子类/任意串） |
| identity 生命周期双向（HISTORY 前全空；HISTORY/REFERENCE 仅 candidate；PREPARE 才有 release；PUBLISH 才有 manifest） | `:188–214` |
| FAILED/SUCCESS/INCOMPLETE × error_code × error_operation 闭包 | `:216–233`：workflow 必须合法 Operation；CLI-only 不得带 operation；非 FAILED 无 error 字段 |
| 实现者测试 | `test_cli_result_rejects_illegal_hex_and_identity_lifecycle` / `..._error_operation_closure` / `..._accepts_legal_identity_samples` |

### F3 项目内 config 路径闭包 — 成立

| 核对项 | 证据 |
|---|---|
| `_validate_config_path(path, *, project_root)` | `run_g1.py` `:582–627` |
| 项目根内相对、拒绝 `..`、末端与祖先非 symlink、读取前后 fingerprint TOCTOU | `:586–620` |
| 失败 → `CLI_CONFIG_INVALID` / exit 2，stdout/stderr 无路径 | `_run` `:847–858` + 实现者 outside/穿越/symlink/TOCTOU 测试 |
| 不强制 `configs/research/` | `test_config_inside_project_accepted`（`custom/anywhere.toml`） |

### F4 argparse 后保留已识别 command — 成立

| 核对项 | 证据 |
|---|---|
| `_peek_command` 跳过 `--config`/`--project-root` 等取值 | `:532–563` |
| 无/多/未知 command → `None`；无歧义单 command 在后续失败时保留 | `_run` `:792–817`；`test_argparse_rejects_token_and_unknown` 已修正 |
| config 值形似 `status` 不误认 | `test_argparse_skips_config_value_looking_like_command` |

---

## 3. 实现者未使用的对抗（本轮新增）

全部在临时目录 / 进程内探针执行，**未改**生产或测试文件。结果：`adversarial_total=8 failed=0`。

### 3.1 state 双错误组合（提前产物 + counts / response order）

实现者分开测 early artifact 与 counts/response；本轮**同时**注入：

1. INDEX 合法 state + 提前 `candidate` stub **且** `history_requests += 7` → `ValueError`（`HISTORY 未完成产物闭包非法`），无路径/repr 泄露。
2. INDEX 合法 state + 提前 `prepared` stub **且** `index_responses` 逆序 → `ValueError`（`index responses 闭包非法`）。
3. 补充：fresh 声称 `completed_stages=("INDEX",)` 而无 index 产物 → 拒绝（阶段提前/滞后）。

### 3.2 `G1CliResult` identity / `error_operation` 组合

实现者分开测 identity 与 error_operation；本轮组合：

1. **合法 PUBLISH identity**（三枚 hex 齐备）+ `FAILED` + `CLI_CONFIG_INVALID` + `error_operation="PUBLISH"` → 拒绝（`CLI-only error 不得携带 error_operation`）。
2. PREPARE + 合法 candidate/release + **提前 manifest** → 拒绝（identity 生命周期）。
3. HISTORY SUCCESS + 合法 candidate + **`error_operation="HISTORY"`** → 拒绝（非 FAILED 不得带 error）。

### 3.3 config 祖先 symlink 出项目 / command peek 形似子命令

1. **末端普通 `.toml`，中间目录 symlink 指向项目外** → exit 2，`CLI_CONFIG_INVALID`，stdout/stderr **零路径泄露**（实现者仅测过项目内祖先 symlink；本组合指向项目外）。
2. `--project-root` 值字面为 `index`（形似子命令），真实 command=`publish` + 未知 option → `command=="publish"`，`CLI_ARGUMENT_INVALID`（实现者只测过 `--config` 值为 `status`）。

---

## 4. 防挂复现与残留

命令（Linux `timeout -s KILL 30`）：

```bash
timeout -s KILL 30 python -m pytest \
  tests/unit/test_m3_g1_workflow.py::test_verified_state_self_proof_bidirectional_closure \
  tests/unit/test_m3_g1_workflow.py::test_verified_state_self_proof_does_not_hang -q --tb=line
```

结果：`2 passed in 5.11s`，timeout **未**触发（非 124/137）。与交付报告“测试构造过重而非 journal 死锁”一致；本轮未见 flock 阻塞等待。

临时诊断文件：两测本身不写诊断产物；`pytest` `tmp_path` 生命周期内清理。扫描 `/tmp` 与 Windows Temp 仅见历史 R0 残留与本轮对抗探针脚本，**无**本轮防挂测试新留诊断文件。对抗探针位于系统 Temp，不在仓库白名单内。

---

## 5. 定向验证命令与结果

```text
# 定向（排除 five_stage_fake）
conda run -n base python -m pytest \
  tests/unit/test_m3_run_g1.py tests/unit/test_m3_g1_workflow.py -q -k "not five_stage_fake"
→ 53 passed, 1 deselected in 20.20s

conda run -n base python -m ruff check \
  src/quant/research/m3/g1_workflow.py src/quant/research/m3/run_g1.py \
  tests/unit/test_m3_g1_workflow.py tests/unit/test_m3_run_g1.py
→ All checks passed

conda run -n base python -m mypy \
  src/quant/research/m3/g1_workflow.py src/quant/research/m3/run_g1.py
→ Success: no issues found in 2 source files
```

未跑全量 pytest；未重跑 `test_five_stage_fake_publish_and_inspect_closure`（单 HISTORY 量级约数分钟，任务允许初验用小型链）。

---

## 6. 任务单 §9 / 生产路径抽查

| §9 项 | 结果 |
|---|---|
| 合法阶段“提前/滞后”替换 | fresh/INDEX 已覆盖；HISTORY+ 合法构造依赖既有五段测，本轮按指示未重跑长链 |
| PREPARE 提前 manifest / PUBLISH 缺 manifest | 实现者测试 + 本轮 F2 组合均拒绝 |
| 中间目录 symlink 到项目外 | 本轮 F3 对抗通过且零路径泄露 |
| config 值形似 command 的归属 | 实现者（`--config=status`）+ 本轮（`--project-root=index`）均正确 |
| 无新增网络 / token / `os.replace`；M4-C0 不在本白名单改动 | `g1_workflow.py`/`run_g1.py` 无 `os.replace`；`--token` 仅拒绝；闭包无 connector/网络。M4 并行工作树另有时间戳，**本初验未改**任何 M4 文件；交付白名单与本报告写入集合一致 |

`g1_workflow` 中既有 journal `iterdir` 属 R1B journal 校验，非值对象构造期扫描，不构成 F1 违约。

---

## 7. 残留风险（供主 Agent，不阻断本轮初验）

1. 合法 HISTORY/REFERENCE/PREPARE/PUBLISH 状态机自证仍主要依赖 `test_five_stage_fake_*`；本轮按指示未重跑，主验若需闭合长链证据应**串行**单跑并预留长等待。
2. P2 stdout 部分写失败加固为可选，本轮未要求、未验收。
3. 工作树存在并行 M4-C0 改动痕迹；全量回归仍应按任务单在 M4 停止写入后由主验执行。

---

## 8. 初验结论

- **F1、F2、F3、F4：全部成立**
- 实现者未用对抗（双错误 state、identity×error_operation、出项目祖先 symlink、project-root 形似 command）：**全部拒绝且脱敏**
- 防挂两测：`timeout 30` 下 2 passed / ~5s，无死锁、无本轮诊断残留
- 定向 pytest / ruff / mypy：**通过**

**可交主 Agent 复验。**  
**不宣布 R1B / R1C / G1 / Gate 通过。** 初验完成，停止。
