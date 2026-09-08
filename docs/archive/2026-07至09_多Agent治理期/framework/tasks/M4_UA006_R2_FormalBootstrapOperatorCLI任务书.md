# M4-UA006-R2 Formal Bootstrap Operator CLI 任务书

日期：2026-08-26
状态：`FROZEN / STATIC_ONLY`
task id：`M4-UA006-R2-FORMAL-BOOTSTRAP-OPERATOR-CLI`

## 1. 身份与角色

- exact base：`27d42840c08d883d08c9578b3c2802b4630bd0f8`
- branch：`codex/m4-ua006-r2-formal-bootstrap-operator-cli`
- worktree：`artifacts/dev_worktrees/m4-ua006-r2-formal-bootstrap-operator-cli`
- 经理：唯一写本任务书。
- implementation：一个全新 Cursor Grok 4.5 High 会话，只写批准的 production、tests、delivery。
- independent review：另一个未参与实现的全新 Cursor Grok 4.5 High 会话，只写唯一 review。

不得创建第二实现者/reviewer、内部 subagent、替代 worktree 或重复 CLI。

## 2. 目标与不变量

提供一个窄、可审计、可 fresh 重验的 operator CLI，作为未来 UA-M4-006 fresh-root/new-epoch 证据包唯一调用入口。
CLI 只解析显式参数、在进程内取得 canonical UTC now、调用已合流 public bootstrap/reopen/fresh verifier，并输出
脱敏 canonical identity projection。

必须保持：

- root/layout/account/policy/binding/store/barrier 语义全部由现有 public API 与 validated config 决定；
- CLI 不复制 P1/P2 economic projection、bootstrap 顺序、schema、migration、store 或 barrier 逻辑；
- 无 submit、cancel、soak、scheduler、order、gateway dispatch、network 或真实 PAPER；
- Windows 工程验证不关闭 UA-M4-006、PAPER、soak 或 Linux Gate。

## 3. exact6 写白名单

1. `src/quant/execution/run_paper_formal_bootstrap.py`（new）
2. `tests/unit/test_run_paper_formal_bootstrap.py`（new）
3. `tests/integration/test_run_paper_formal_bootstrap.py`（new）
4. `docs/framework/tasks/M4_UA006_R2_FormalBootstrapOperatorCLI任务书.md`（经理唯一写）
5. `docs/framework/deliveries/M4_UA006_R2_FormalBootstrapOperatorCLI交付报告.md`（implementation 唯一写）
6. `docs/framework/reviews/M4_UA006_R2_FormalBootstrapOperatorCLI独立初验报告.md`（reviewer 唯一写）

禁止修改 `quant.execution.__init__`、`paper_formal_bootstrap.py`、broker/policy/account/runtime/config、schema、migration、
barrier、service、soak、pyproject、roadmap、handoff 或既有测试。

## 4. CLI exact contract

### 4.1 参数

入口：

```text
python -m quant.execution.run_paper_formal_bootstrap \
  --config <exact-absolute-path> \
  --session-date YYYY-MM-DD \
  (--initialize | --reopen)
```

- `--config`、`--session-date` 必需；`--initialize` 与 `--reopen` 必须恰好一个。
- 禁止其他参数、位置参数、env fallback、cwd discovery、默认 config、glob/latest/root override。
- 不提供 `--now`、clock/env 注入、root、epoch、account、gateway、store、cash、schedule、PAPER 或 soak 参数。
- `--config` 必须在调用 public API 前验证为当前平台 exact concrete absolute `Path`，拒绝 relative、PurePath/
  subclass、symlink/junction/reparse、缺失、非 regular file；不得读取/打印文件内容。
- `--session-date` 只接受 canonical `YYYY-MM-DD` 且 round-trip 逐字相等。
- `--help` 零业务调用并 exit 0；其他 argparse/usage 失败不得打印默认 usage 或路径。

### 4.2 时间与调用顺序

- `main` 每次业务调用只取得一次 `datetime.now(timezone.utc)`；必须是 aware UTC，微秒精度由现有 canonical
  wire helper处理。
- initialize：`bootstrap_fresh_formal_paper_runtime(config_path, session_date, now)` →
  `verify_existing_formal_paper_runtime_bootstrap(bootstrap, same now)`。
- reopen：`reopen_verified_formal_paper_runtime(config_path, session_date, now)` →
  `verify_existing_formal_paper_runtime_bootstrap(bootstrap, same now)`。
- fresh verifier 返回对象必须与前一步 capability `is` 相同；否则 runtime fail-closed。
- callable 必须是 `paper_formal_bootstrap` 当前 package-owned public 真身；wrapper、partial、marker、双侧同一 impostor
  均拒绝。CLI 不得调用 loader/initializer/store/barrier 私有函数。

### 4.3 stdout identity projection

成功 stdout 必须恰好一行 canonical ASCII JSON，schema exact：
`m4-formal-bootstrap-operator-result-v1`。字段 exact 且仅：

1. `schema_version`
2. `mode`（`initialize` / `reopen`）
3. `session_date`
4. `bootstrap_identity`
5. `config_identity`
6. `config_raw_sha256`
7. `source_file_identity`
8. `runtime_environment_identity`
9. `runtime_layout_identity`
10. `execution_policy_identity`
11. `broker_binding_identity`
12. `account_verification_identity`
13. `broker_capability_identity`
14. `gateway_identity`
15. `execution_store_identity`
16. `barrier_epoch`
17. `barrier_capability_identity`
18. `barrier_lock_identity`

所有值必须来自 fresh-verified `VerifiedFormalPaperRuntimeBootstrap`，不得重算或接受 caller 投影。禁止输出 config/root/
SQLite 路径、account id、verified_at、token、对象 repr、exception、环境变量或任何配置内容。JSON 使用现有
`canonical_json_bytes`，stdout 末尾 exact 一个 LF。

### 4.4 错误与 exit

| 场景 | stderr | exit |
|---|---|---:|
| 成功 / help | 空 | 0 |
| 参数、path、date、mode 输入错误 | `PAPER_FORMAL_BOOTSTRAP_CLI_INPUT_INVALID\n` | 2 |
| public `FormalPaperBootstrapError` 且 `error.code` 为 stable token | 仅其 `error.code + "\n"`（verbatim） | 3 |
| public `FormalPaperBootstrapError` 但 `error.code` 非 stable token | `PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED\n`（整码替换，禁止部分消毒输出） | 3 |
| 未预期异常、callable drift、fresh verifier 非同一对象、业务段意外 `SystemExit` | `PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED\n` | 3 |

stable `error.code` token（STATIC_REWORK1 / F2 冻结）：`type(code) is str`、非空、ASCII、首字符 `A-Z`、其余仅 `A-Z0-9_`。任何空白、CR/LF/TAB/ESC/其它控制字符、`/` `\` `:`、Unicode、path-like 或其它畸形码 **整码**映射为 generic runtime，不得 sanitize 后部分写出。

业务段（parse 成功之后）必须显式 `except SystemExit` → runtime/3/stdout 0B（STATIC_REWORK1 / F1）。**不得** `except BaseException`；`KeyboardInterrupt` / `GeneratorExit` 保持进程控制语义。parse 期 `--help`→0 与其它 argparse→INPUT/2 不变。

失败 stdout 必须 0B；stderr 不得包含绝对路径、argparse usage、config bytes、exception message/repr/chain。CLI 不得
吞掉 public stable code 后错误映射为 input，也不得把未知异常写成 underlying message。

## 5. 文件与副作用边界

- CLI 自身只允许读取 `--config` 的路径元数据；正式文件创建完全由 public bootstrap API负责。
- initialize 失败的 rollback/partial-root 语义完全沿用 public API；CLI 不清理、删除、重试、adopt 或扫描 root。
- reopen 不调用 initializer，不补 partial root，不创建新 epoch。
- 本任务测试只能使用最小 fixture，且任何 filesystem integration fixture root 必须由测试显式拥有、项目外/
  非 system temp，并在获批 Python 验证中精确清理。
- implementation/review 阶段 `STATIC_ONLY`：零 Python、pytest、Ruff、mypy、cold、SQLite probe、真实 config/root/
  epoch、PAPER、soak、submit、network、stage、commit。

## 6. 必测反例

unit/integration 测试至少覆盖：

1. help、缺参、多余参数、initialize+reopen 同时/均未指定；
2. relative/PurePath/subclass/symlink/reparse/missing/directory config；
3. 非 canonical date、datetime、无效日期、前后空白；
4. initialize 与 reopen 各自 exact public 调用顺序、same-now、fresh verifier `is`；
5. wrapper/partial/marker/双侧同一 impostor、错误返回类型、fresh equal-but-not-identical capability；
6. public input/runtime stable code、未知异常、路径型异常消息全部脱敏；业务段 initialize/reopen/verify
   `SystemExit`→runtime；hostile/`\n`/`\r`/控制字符/非 token `error.code` 整码→runtime（禁部分消毒）；
7. success projection exact keys/order/schema，且不含 path/account id/time/token/object；
8. failure stdout 0B、stderr exact 一行、exit 2/3；
9. initialize 失败不由 CLI 删除或重试；reopen 零 initializer；
10. config 由 public API 发生 TOCTOU/identity 漂移时 CLI 返回 runtime，不输出成功 JSON；
11. 真实 public fixture：fresh initialize → fresh verify → close/只读边界后，错误模式不得 reopen；完整 OPEN
    bundle 才允许 reopen，且 identity projection 与 capability 一致。

测试不得 monkeypatch `_actual_project_root`、`_system_temp_root` 或 public bootstrap 内部 authority 来造绿；允许在
unit 边界用精确 package callable seam 验证 CLI 调用形状，但 integration 至少有一个真实 public 正向和一个真实
fail-closed 反例。

## 7. 验收顺序

STATIC implementation/review 先行。`REVIEW_PASS` 后另向中央申请 Windows fixture 验证：

1. identity：`quant`、CLI、`paper_formal_bootstrap` 来自 exact worktree；
2. unit test；
3. integration test（中央批准 project-outside/non-system-temp fresh basetemp）；
4. Ruff CLI + tests；
5. mypy CLI；
6. cold import CLI；
7. exact6 Unicode-safe scope、cached0、diff/temp/cache/process residue。

首失败 STOP，不缩小失败轮冒充整包 PASS；Windows 绿只允许
`FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`。

## 8. 交付与 review 要求

implementation delivery 必须逐项记录：参数/时间/调用顺序、projection、错误码、零清理边界、反例映射、实际
dirty scope、全部 UNRUN。发现 public API 无法满足 same-now/fresh identity、需要修改白名单外模块或真实 root
才能测试时，必须 `CONTRACT_STOP`，不得自行扩围。

reviewer 必须独立挑战：

- CLI 是否复制 bootstrap/policy/P2 逻辑；
- 是否可通过 path/env/root/clock 注入绕过 config authority；
- success JSON 是否泄露路径/account/time/token；
- callable 双侧替换、equal-not-identical fresh return、TOCTOU 是否 fail-closed；
- initialize failure 是否被 CLI 擅自删除/重试；
- 是否把 Windows fixture 写成 UA-M4-006/PAPER/soak/Linux Gate。

## 9. 终态边界

本包不创建真实 formal root/epoch，不启动 PAPER/soak/scheduler/order/network，不修改正式 config，不启动 28 日
计时。真实 fresh-root 运行必须在本包合流后另建 run-only 包，显式冻结 config、root、session date、资源、证据与
处置。

UA-M4-006、PAPER、soak、fault drill、Linux Gate 全部保持 OPEN。

## 10. STATIC_REWORK1（相对 REVIEW_FAIL P1×2 + P2×1）

日期：2026-08-26。依据独立初验 `REVIEW_FAIL`（只读）。实现者仅写 exact6 之 CLI / unit / integration / 本任务书补充 / delivery；review 只读。

| ID | 冻结通过条件 |
| --- | --- |
| F1 | 业务执行段显式捕获 `SystemExit`→`PAPER_FORMAL_BOOTSTRAP_CLI_RUNTIME_FAILED` / exit 3 / stdout 0B；覆盖 initialize、reopen、verify 升起；不 `except BaseException`；`KeyboardInterrupt` 语义不变；parse 期 help 仍为 0 |
| F2 | `FormalPaperBootstrapError.code` 仅当 exact stable ASCII token（首 `A-Z`，其余 `A-Z0-9_`）时 verbatim 输出；否则整码→generic runtime；unit 覆盖 `\n`/`\r`/TAB/ESC/空白/slash/backslash/colon/Unicode/非 str |

保持：单次 UTC now、callable 真身、exact config Path、fresh `is`、canonical projection、其它 exit、零清理。STATIC_ONLY。

## 11. STATIC_REWORK2（VALIDATION1 unit fixture）

日期：2026-08-26。VALIDATION1 的 identity PASS；unit 为 `58 passed / 1 failed`，并在首失败后停止；integration、
Ruff、mypy、cold、scope 均 UNRUN。证据根：
`artifacts/agent_runs/m4-ua006-r2-validation1-20260826T2203/`。

| 项 | 冻结合同 |
| --- | --- |
| 现象 | Windows 无法创建真实 symlink 时，`test_symlink_or_reparse_config_is_input_invalid` 的 fallback 返回 exit 3，而合同要求 input exit 2 |
| 根因 | test-only fallback 把函数对象 `stat.S_IFMT` 用于 `~stat.S_IFMT`，先触发 `TypeError`；CLI 的 generic exception 边界随后按既有合同归一为 runtime failure |
| 规则 | 合成 `os.stat_result` 的 mode 必须使用明确的 symlink file-type bits 与原 permission bits；不得把 `stat.S_IFMT` 函数当位掩码，不得修改 production config guard 或异常归一 |
| 最小修正 | 仅在 unit fallback 使用 `stat.S_IFLNK | stat.S_IMODE(info.st_mode)` 或严格等价表达式；保留目标 path exact 匹配与真实 symlink 正向分支 |
| 回归断言 | fallback 与真实 symlink/reparse 均为 exit 2、stdout 0B、stderr exact input code，且不泄露 target path |
| 通过条件 | 同一原 reviewer 确认仅 unit+delivery（及本经理任务书）变化、production/integration 冻结；随后从 identity 起完整运行新的 VALIDATION2，不把本轮 58 个通过节点冒充整包 PASS |

本轮仍为 `STATIC_ONLY`：实现者只允许修改 unit test 与 delivery；任务书由经理维护；review 仅由原 reviewer 更新。

## 12. STATIC_REWORK3（VALIDATION2 integration identity）

日期：2026-08-27。VALIDATION2 的 identity PASS、unit `59 passed`；integration 为 `5 passed / 1 failed`，
并在首失败后停止；Ruff、mypy、cold、scope 均 UNRUN。证据根：
`artifacts/agent_runs/m4-ua006-r2-validation2-20260827T033820Z/`；integration stdout SHA256 为
`EC1ECFEBB0B43179056F7DE3164DC2DB6965E9DB9F402640A865D5F4EA1DBBF9`，summary SHA256 为
`A9FF402C39B5B7F6749ECFC25013EFBBBC009A41AB20E7412C0227EA9CE8B8A3`。

| 项 | 冻结合同 |
| --- | --- |
| 现象 | integration 将 CLI initialize 投影与后续 public reopen capability、CLI reopen 投影与再后续 public reopen capability 的 `bootstrap_identity` 逐字比较，且要求 initialize/reopen 两次 CLI identity 相同 |
| 根因 | `paper_formal_bootstrap` 的 identity payload 明确包含 `verified_at`；`bootstrap_identity` 是每次 fresh verification 的 time-bound identity，不是跨 reopen 的 durable identity |
| 规则 | `bootstrap_identity` 仍为 CLI 必需输出字段；每个值必须是 canonical lowercase 64-hex。CLI initialize、后续 public reopen、CLI reopen、再后续 public reopen 四次 fresh identity 必须互异；不得暴露 `verified_at`、删字段或修改 production identity 算法 |
| 稳定闭包 | 跨调用比较只排除 `bootstrap_identity`；schema/mode 仍按各调用语义验证，除该 time-bound 字段外的既有 durable projection、key 集合、脱敏、`barrier_epoch`、`execution_store_identity` 及其余 identity 全部保持原严格比较 |
| 同次投影 | unit owned-capability seam 继续证明同一次 CLI capability 的 `bootstrap_identity` 与输出逐字相等；integration 不得用后来另一次 reopen capability冒充前一次 capability |
| 通过条件 | 同一原 reviewer 确认仅 integration+delivery（及本经理任务书）变化，production/unit 冻结；随后从 identity 起完整运行 VALIDATION3，不继承本轮部分绿 |

本轮仍为 `STATIC_ONLY`：实现者只允许修改 integration test 与 delivery；任务书由经理维护；review 仅由原 reviewer 更新。

## 13. STATIC_REWORK4（VALIDATION3 完整身份分组）

日期：2026-08-27。本节取代 §12 中“跨调用只排除 `bootstrap_identity`”的不完整规则，但保留 §12 的失败历史。
VALIDATION3 的 identity PASS、unit `59 passed`；integration 为 `5 passed / 1 failed`，并在首失败后停止；Ruff、
mypy、cold、scope 均 UNRUN。证据根：
`artifacts/agent_runs/m4-ua006-r2-validation3-20260827T035206Z/`；integration stdout SHA256 为
`6AB242600679E219AB14EF1C744C9EC98215090510F8FF293F5497D0B913A8E8`，summary SHA256 为
`C556FBA20EB813232312BD43232D6C97F6CB2DB147C572CF7B3AEC209CBB7FCA`。

输出 18 键必须由以下互斥集合精确覆盖：

- 固定控制字段：`schema_version`；逐调用语义字段：`mode`。
- `TIME_BOUND` exact6：`bootstrap_identity`、`runtime_environment_identity`、
  `execution_policy_identity`、`broker_binding_identity`、`account_verification_identity`、
  `broker_capability_identity`。
- `DURABLE` exact10：`session_date`、`config_identity`、`config_raw_sha256`、`source_file_identity`、
  `runtime_layout_identity`、`gateway_identity`、`execution_store_identity`、`barrier_epoch`、
  `barrier_capability_identity`、`barrier_lock_identity`。

`runtime_layout_identity` 只在 cold absent→materialized 时变化；CLI initialize 已完成物化，后续 fresh reopen 必须保持
durable，不得把它归入 time-bound。integration 的 CLI initialize、后续 public reopen、CLI reopen、再后续 public
reopen 四次 fresh capability 中，每个 `TIME_BOUND` 字段均必须是 canonical lowercase 64-hex，且同字段四值互异；
每个 `DURABLE` 字段四次逐字相等。unit owned-capability seam 继续锁定同一次 capability→CLI exact 全字段投影。

不得删除输出字段、暴露 `verified_at`、修改 production identity 算法或继续逐字段删减。若任何 public identity 与上述
分组冲突，立即 `CONTRACT_STOP` 并提交源码证据。实现者只允许修改 integration test 与 delivery；任务书由经理
维护；review 仅由原 reviewer 更新；全程 `STATIC_ONLY`。review PASS 后必须完整执行 VALIDATION4。

## 14. STATIC_REWORK5（VALIDATION4 callable 类型收敛）

日期：2026-08-27。VALIDATION4 的 identity、unit `59 passed`、integration `6 passed`、Ruff 均 PASS；mypy
在 CLI 出现唯一错误后首失败停止，cold 与 scope UNRUN。证据根：
`artifacts/agent_runs/m4-ua006-r2-validation4-20260827T040605Z/`；mypy stdout SHA256 为
`AEE3A11B1C69E1FC45B9524717B1E7F4D257E56F4A71BEAC44B8667B31CF5307`，summary SHA256 为
`239DB23C8787667591DC48CA7B9C81A65006EF3F2EE282E5D4EF65ED3E6B2E05`。

| 项 | 冻结合同 |
| --- | --- |
| 现象 | `_build_callable_authority` 声明返回三个具体 `Callable[..., VerifiedFormalPaperRuntimeBootstrap]`，但 inner tuple 被推断为 `tuple[object, object, object]` |
| 根因 | outer 的 `true_bootstrap`、`true_reopen`、`true_verify` 参数被标成 `object`，该过宽类型沿 closure 传播到 inner 返回值 |
| 最小修复 | 定义单一窄 alias `_BootstrapCallable = Callable[..., VerifiedFormalPaperRuntimeBootstrap]`（等价风格命名可接受），并统一用于三个 outer 参数、outer Callable 返回中的三元组和 inner 返回三元组 |
| 禁止项 | 禁止 `cast`、`Any`、`type: ignore`、`Protocol`；不得修改函数体、`is`/`__code__`/`partial`/`__wrapped__` 检查、调用顺序、异常码、projection/schema或测试 |
| 通过条件 | 同一原 reviewer 确认仅 alias/annotations 与 delivery 变化、runtime 执行路径不变；随后运行 POSTFIX VALIDATION5：identity→Ruff仅CLI→mypy CLI→cold CLI→exact6 Unicode scope/cached0/diff/temp/cache/process |

VALIDATION5 不重复 VALIDATION4 已绿的 unit59、integration6 与 Ruff tests，除非 reviewer 发现行为变化。本轮仍为
`STATIC_ONLY`：实现者只允许修改 CLI source 与 delivery；任务书由经理维护；unit/integration/review 只读。

## 15. VALIDATION5 最终组合证据与状态上限

日期：2026-08-27。REWORK5 经同一原 reviewer 给出 `REWORK5_REVIEW_PASS` 后，中央按 §14 冻结的窄范围执行
POSTFIX VALIDATION5。证据根：
`artifacts/agent_runs/m4-ua006-r2-postfix-validation5-20260827T041948Z/`；summary SHA256 为
`8054701A99588936DD8646057CF994E2D33627E55D6AD4235BD472DDCC2EAEDB`。

最终 Windows 工程证据必须按以下组合解释，不能把任一历史首失败改写为整轮 PASS：

- VALIDATION4：identity PASS；unit `59 passed`；integration `6 passed`；Ruff（CLI 与两份 tests）PASS；mypy
  在唯一 callable 注解错误处首失败停止；cold、scope UNRUN。
- REWORK5：仅增加窄 `_BootstrapCallable` alias 并收窄 annotations；同一原 reviewer 静态确认运行路径、测试、
  projection/schema、真身检查与异常语义未变，允许复用 VALIDATION4 已绿节点。
- VALIDATION5：identity PASS；Ruff 仅 CLI PASS；mypy CLI `Success: no issues found in 1 source file`；cold CLI
  PASS；exact6 Unicode-safe scope、cached=0、`git diff --check`、temp/cache/`__pycache__`、0xF00 释放与
  writer PID7692 affinity `0x3` 全部 PASS。

以上组合仅将本包状态提升为
`FORMAL_BOOTSTRAP_OPERATOR_CLI_WINDOWS_ENGINEERING_VALIDATED`。真实 bootstrap、PAPER、soak、submit、network、
Linux Gate 与 UA-M4-006 继续 `OPEN`；本轮未执行这些能力，也不得据此开始真实运行或计时。

后续职责严格串行：同一原实现者仅更新 delivery，逐轮保留 V1–V5 首失败、UNRUN 与有效绿证据；production/tests
冻结且零 Python。随后同一原 reviewer 仅更新唯一 review，核证据根/SHA、actual exact6、cached/diff/residue 与
上述状态上限，输出 `EVIDENCE_REVIEW_PASS` 或 `EVIDENCE_REVIEW_FAIL`。只有 PASS 后方可申请 SAFE_COMMIT；
ignored evidence 必须保留且不得 stage。
