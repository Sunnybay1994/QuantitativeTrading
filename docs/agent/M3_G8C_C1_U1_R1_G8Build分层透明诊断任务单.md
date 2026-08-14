# M3 G8C-C1 U1 R1：G8 Build 分层透明诊断任务单

日期：2026-08-12  
状态：**诊断未完成（FAIL/证据不足）；外部会话中断，禁止重跑 U1；转 U2 分离长链生命周期**  
上游证据：[M3_G8C_C1_R3_真实CLI失败定位与单次终验返工交付报告.md](M3_G8C_C1_R3_真实CLI失败定位与单次终验返工交付报告.md) **FAIL**

## 1. 背景与唯一目标

C1 R3 已用一次真实 public chain 证明：

- `resolve_formal_backtest_cli_inputs` exact 一次成功；
- `run_formal_backtest_stage` exact 一次抛出
  `quant.research.m3.orchestration.M3StageRunnerError(code="STAGE_BUILD_FAILED")`；
- CLI 正确映射为 canonical JSON / exit 5；
- 根因位于 `StageRunner.handler -> build_backtest_artifact` 内部，而非 C1 seam。

`StageRunner` 与 G7F public boundary 按既有安全合同脱敏，外层证据无法再看到具体失败阶段。本任务唯一目标是：

> 不改变任何生产行为，只在 integration 测试中临时安装透明观察器，运行一次 Windows 真实链，确定
> `build_backtest_artifact` 内第一个失败的阶段边界；自然回收后恢复测试文件，并写唯一诊断报告。

本任务不是修复轮，不做 Phase B，不得宣布 C1/G8/G7F/Gate 通过。

## 2. 冻结证据

R3 诊断 evidence：

`C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-r3-diagnostic\M3_G8C_C1_R3_diagnostic_evidence.txt`

SHA-256：`5f5ffe29634624b7b7f82cdc56a2fca87588860b32700f1298f20a92f9342659`。

R3 observe：`...\phase_a_observe.json`，SHA-256
`299bc2919f2f1b06b00ad4242de5992950d5413d11eee51062e0db68ab286dc4`。

当前最终 integration 测试必须以 SHA-256
`5ba1d2fcbd14d73627940f0127742f3d44387533e2ab4b6be5bbece8fb8014b2` 为起点，并在诊断后恢复到相同 SHA；
其中永久保留 `assert code == 0, payload`。

## 3. 透明观察原则

所有观察器均位于 `tests/integration/test_m3_g8c_c1_backtest_cli.py`，通过 pytest `monkeypatch` 临时安装：

1. 保存原 callable/method；
2. 原位置参数、关键字参数原样传入；
3. 原返回值原样返回，原异常用 bare `raise` 原样传播；
4. 不缓存、不替换、不少调、不重试、不改变调用顺序；
5. 每次调用后立即把精简、canonical JSON 观察结果原子写到系统临时目录；
6. 只记录：边界名、序号、调用次数、开始/成功/失败、exact 返回/异常 type、exact `str` `.code`、exact
   `int` `.exit_code`、cause/context 是否 None；场景仅可记录 public multiplier canonical text；
7. 禁止记录异常 `str/repr`、路径、DataFrame、配置内容、原始 JSON/parquet、账号/token/secret 或正式数据；
8. 诊断结束后必须移除全部观察代码和诊断 import，恢复测试起点 SHA。

## 4. 必须覆盖的阶段边界

至少观察以下真实 callable；若名称/签名与当前源码不一致，停止并回报，不猜测替代：

### 4.1 G8/G7F 顶层

- `quant.research.m3.backtest_stage.build_backtest_artifact`
- `quant.backtest.a_share_reporting._formal_bundle`

### 4.2 `_formal_bundle` 内部顺序

- `_validate_formal_inputs`
- `verify_backtest_plan_artifact`
- `load_verified_a_share_market_facts`
- `_formal_config_values`
- `simulate_formal_a_share_scenario`（逐 multiplier 记录 0.5/1/2 的调用序号与终态）
- `_formal_scenario_metrics`
- `_formal_parquet_bytes`
- `_formal_scenario_manifest`

### 4.3 发布与 readback

- `ArtifactPublication.write_bytes`
- `ArtifactPublication.read_bytes`
- `_validate_formal_readback`
- `ArtifactPublication.commit`

如果某个直接条件判断发生在两个边界之间，报告用“最后成功边界 + 后续边界未调用”定位，不在测试中复制生产判断。

## 5. 单次诊断协议

### 5.1 前置

1. 确认无其他 Cursor writer、C1/G8/G7F pytest；
2. 记录生产与 integration 测试 SHA；
3. 临时观察 revision 的 Ruff、目标 mypy、cold import PASS；
4. scoped diff 只含允许的临时 integration 观察代码与本任务/报告；
5. 本轮持久目录固定为新的
   `C:\Users\mbw\AppData\Local\Temp\m3-g8c-c1-u1-r1-g8-build-diagnostic\`，启动前必须不存在；不得覆盖旧证据。

### 5.2 唯一命令

```powershell
D:\Miniforge3\envs\m3chain312\python.exe -m pytest -q -p no:cacheprovider \
  tests/integration/test_m3_g8c_c1_backtest_cli.py
```

只允许启动一次，最大预算 10800 秒。wrapper 必须：

- 使用 `System.Diagnostics.Process` 或等价单一对象启动 pytest；
- 立即记录 wrapper PID、pytest PID、开始时间、命令、cwd、`PYTHONPATH`、`MODEL=auto`、候选 SHA；
- `WaitForExit()` 后 `Refresh()` 并读取明确整数 `ExitCode`，不得再留下空 `EXIT=`；
- stdout/stderr 分离持久化，结束后追加结束时间、墙钟、摘要、EXIT；
- 运行中只低频检查同一 PID，不读活动日志、不启动第二次。

该链预期仍可 FAIL；它是诊断证据，不是验收。无论 PASS/FAIL，禁止在本任务内启动第二条长链。

## 6. 诊断结论要求

报告必须给出：

1. 第一个失败边界的 exact callable、调用序号、场景（若适用）、exception exact type/public code；
2. 该边界之前所有必须阶段的调用次数与成功状态；
3. 该边界之后哪些阶段未调用；
4. 是否属于：
   - public-chain fixture 数据/窗口不满足已冻结 G7 业务合同；
   - G7F/G7E/G7D 等生产在真实 300-domain 链上的缺陷；
   - publication/readback/平台原语缺陷；
   - 仍无法区分；
5. 下一轮最小生产/fixture白名单建议和秒级回归设计；
6. “现象—根因（若已证明）—规则—最小复现—新增测试建议—通过条件”。

不得把 LightGBM warning、最后成功边界或猜测写成已证明根因。若观察仍停在泛化
`M3_A_SHARE_BACKTEST_ARTIFACT_INVALID` 而不能定位内部阶段，本轮结论为 FAIL/证据不足，主 Agent另冻 U2，禁止重跑。

## 7. 文件白名单

诊断会话永久写入只允许：

1. 本任务单：只更新状态；
2. 唯一报告：
   `docs/agent/M3_G8C_C1_U1_R1_G8Build分层透明诊断报告.md`。

`tests/integration/test_m3_g8c_c1_backtest_cli.py` 只允许**临时**加入观察代码；会话结束前必须恢复到起点 SHA。

所有生产、其他测试、R1–R3 历史任务/报告、C0 support、config/schema、正式 artifact/data 全部只读。禁止联网、
add/commit/push、删除历史脏文件或保留测试 fixture root。

## 8. 短验证与收尾

临时观察 revision：

```powershell
D:\Miniforge3\python.exe -m ruff check tests/integration/test_m3_g8c_c1_backtest_cli.py
D:\Miniforge3\python.exe -m mypy --follow-imports=silent tests/integration/test_m3_g8c_c1_backtest_cli.py
```

恢复后再次运行 Ruff/mypy，并核对：

- integration SHA 精确回到 §2 起点；
- `git diff --check` PASS；
- 无诊断函数/import/env marker 残留；
- pytest/wrapper 退出；
- `_f0r*`、stage/config/G1 owned root 无残留；
- evidence/observe/stdout/stderr SHA-256 写入报告。

## 9. 停止条件

命中任一项立即停止并写 FAIL 报告：

1. 需要修改生产或 C0 support；
2. 透明包装无法保证参数、返回、异常与调用顺序不变；
3. 临时 revision 静态检查未绿；
4. 持久目录已存在、无法取得明确整数 EXIT、observe/evidence丢失；
5. 同一 revision 已启动诊断后有人请求重跑；
6. teardown 不完整或存在其他 writer；
7. 外部服务异常导致终态不可审计。

## 10. 会话与后续

- 使用全新的外部 Cursor 会话，显式 `--model auto`；UA-AGENT-001 已长期批准。
- 该会话是诊断角色，不是实现/初验；只返回压缩证据，不宣布 Gate。
- 主 Agent 审核报告后另冻最小修复任务；修复仍须走“全新 Cursor 实现 → 另一全新 Cursor 独立初验 → 主验”。
