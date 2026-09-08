# M3-G8F-R2C Actual Successor Run Admission 任务书

日期：2026-08-26
状态：`REFROZEN / STATIC_ONLY / NO_RUN`
task id：`M3-G8F-R2C-ACTUAL-SUCCESSOR-RUN-ADMISSION`

## 1. 身份与所有权

- exact base：`27d42840c08d883d08c9578b3c2802b4630bd0f8`
- branch：`codex/m3-g8f-r2c-actual-successor-run-admission`
- worktree：`artifacts/dev_worktrees/m3-g8f-r2c-actual-successor-run-admission`
- 经理：唯一写本任务书。
- implementation：使用一个全新 Cursor Grok 4.5 High 会话，只读代码/既有 Git 文档，唯一写交付报告。
- independent review：使用另一个未参与 implementation 的全新 Cursor Grok 4.5 High 会话，只读任务书、
  交付报告和权威源码，唯一写 review。

本任务不授权内部 subagent、第二实现者、第二 reviewer、替代 worktree 或角色合并。

## 2. 目标

在不创建 request、不创建 controlled root、不运行 Qlib/worker 的前提下，冻结第一次 package-owned production
successor 真跑所需的完整准入合同。后续 actual run 必须直接消费已合流的唯一入口：

```text
python -m quant.research.m3.run_successor --request <exact-absolute-request-path>
```

本任务只回答“什么输入和现场满足后才允许另行申请真实执行资源”，不回答真实运行结果，不宣布 M3 Gate。

首轮 implementation 已正确返回 `CONTRACT_STOP`：旧 §5.2 同时要求 static admission 时 root 不存在、又要求
bridge 调用时 root 已存在，且把 PROJECT 内合法 ignored 运行区误写成不得位于整个项目树。该 STOP 历史必须
保留；本次在同一 exact3 内重冻生命周期，不修改 bridge/runtime，也不创建 request/root。

## 3. exact3 写白名单

1. `docs/framework/tasks/M3_G8F_R2C_ActualSuccessorRunAdmission任务书.md`（经理唯一写）
2. `docs/framework/deliveries/M3_G8F_R2C_ActualSuccessorRunAdmission交付报告.md`（implementation 唯一写）
3. `docs/framework/reviews/M3_G8F_R2C_ActualSuccessorRunAdmission独立初验报告.md`（reviewer 唯一写）

除上述三份新文档外，所有 tracked/untracked/ignored 路径均为只读或禁止访问。不得修改 production、tests、
config、roadmap、handoff、`__init__.py`、retained 现场或任何既有 evidence。

## 4. 权威只读输入

- `src/quant/research/m3/successor_bridge.py`
- `src/quant/research/m3/run_successor.py`
- `src/quant/research/m3/successor_runtime.py`
- `src/quant/research/m3/successor_upstream_stage.py`
- `src/quant/research/m3/successor_downstream_stage.py`
- R2P、R2S、R2A、R2I、R2W rebuilt、R2B rebuilt 的 task/delivery/review
- `pyproject.toml` 与现有 Qlib/py312 环境验收文档

不得读取 LOCKED retained worktree、其中的 session config、失败产物或 ignored evidence；不得读取真实数据 root、
凭据、网络响应或未获批准的本地 request。

## 5. 准入合同

### 5.1 请求与入口身份

- request 必须由未来独立 run package 在获批现场生成，schema exact 为源码权威的
  `m3-successor-bridge-request-v1`。
- request path、成员路径、字段类型、canonical JSON、重复键/未知键、UTC 文本和 Decimal/float 规则全部服从
  `successor_bridge.py`；本任务不得复制第二套 parser/schema。
- request 生成后必须记录 canonical bytes、size、lowercase SHA-256、resolved absolute path、source Git SHA 和
  生成者；调用前 fresh 双读必须逐字相等。
- 入口必须是当前 main 的 `quant.research.m3.run_successor` 与
  `run_production_successor_bridge`；不得 wrapper、monkeypatch、复制 stage/fold/Gate 顺序或注入 callable。

### 5.2 fresh controlled root 三阶段生命周期（REFREEZE）

`resume` exact 为 `false`。request 内 `controlled_output_root` 始终是 PROJECT-relative canonical posix path；中央
在 future run package 中另行记录其 resolved exact absolute path。两者必须解析到同一对象，不得把绝对路径写入
request 字段，也不得由 cwd/env/latest/glob 推导。

#### A. STATIC admission（本 R2C）

- exact controlled absolute path 必须不存在，且获批 parent 已存在、为 native real directory、无 symlink/
  junction/reparse、无未知 owner 或冲突 sibling。
- 只冻结路径、身份、no-clobber 和资源合同；零 mkdir、零 request、零 probe、零 Qlib/worker。
- 路径允许位于 `project_root` 内的 Git ignored 运行区（例如未来经中央批准的 `artifacts/...`），但不得位于
  Git tracked `src/`、`tests/`、`docs/`、`configs/`，不得位于任何旧 worktree、LOCKED retained、legacy/data、
  system temp 或用户 home。
- 本阶段任一失败后 exact controlled path 必须仍不存在。

#### B. future run package 单步创建

- 只有全部可离线完成的 request/config/release/toolchain/path/no-clobber/LOCKED 隔离检查 PASS，且中央已明确
  授权 exact resolved path 与创建动作后，future run package 才可执行一次窄 mkdir。
- 创建后立即以非跟随方式验证：exact path 是 native real directory、empty、非 symlink/junction/reparse，解析后
  仍位于获批 PROJECT ignored 运行区；父目录、device/volume 与批准值未漂移。
- mkdir 竞争、路径已存在、创建后非空或 identity 漂移均 STOP；不得 adopt、清空、重命名或重试到另一 root。
- B 创建前失败遵循“root 不存在”；B 成功创建后发生任何失败，必须保留 exact root，进入只读调查。

#### C. CLI / bridge 调用

- 调用 `run_successor` 前 controlled root 必须已经是 B 验真的 exact existing empty real directory；这与 A 的
  “尚不存在”属于不同阶段。
- CLI/bridge 必须再次 fresh 验证 PROJECT-only 路径闭包：request 的 canonical PROJECT-relative
  `controlled_output_root` 解析到中央记录的 exact absolute root；两个 config 的 `artifact_root` 分别经现有
  `project_stage_root` 解析后必须形成唯一 `Path`，且该 `Path` 与 controlled root 相等。现有 bridge 不保证
  config 原始字符串与 request 字符串三方逐字相同，本包不得虚构第二套字符串比较器。
- bridge 自身继续 fresh 验证 request、config、release、toolchain、canonical entrypoints；不得因 B 已通过而缓存
  或跳过生产门禁。
- CLI/bridge 进入后无论在 fresh guard、Qlib、stage、Gate 或 terminal 哪一步失败，都保留 exact root 及其中任何
  partial evidence；不得由 carrier/CLI/经理自动删除、回滚或声称 root 仍不存在。

本 R2C 只冻结 A/B/C 合同，不执行任何阶段的创建或调用。

### 5.3 LOCKED retained 隔离

detached `c9f2f36cf0cd76721fe62e6a8de7566ae8dd6d79` 及其 worktree 保持 LOCKED。未来 request 的 project root、
controlled root、G1 release、config、tool、receipt 或 resume 输入不得解析到该 worktree、其子孙路径、硬链接/
reparse target 或其冻结 session config。不得用 `resume=true`、复制文件或重签 identity 规避隔离。

### 5.4 G1、two-fold config 与工具链

未来 run package 必须在 B 创建前完成所有可离线验证，并在 C 由 bridge 再次 fresh 验证：

- exact 一个当前有效 `VerifiedG1Release`，其 source/config/provider/runtime identity 均可由 public verifier 重建；
- exact two-fold config，fold id 唯一且顺序 canonical，两个 fold 的 public Qlib dump tool spec 完全一致；
- `python_executable` 为获批 py312 exact native absolute path，版本/环境用途与既有验收文档一致；
- `qlib_dump_tool_path` exact 等于 package-owned `DEFAULT_TARGET_PATH`，regular-file bytes/size/SHA 与两 fold
  public tool spec 一致；
- timeout 为源码允许的 positive exact type；不得取 env/default `sys.executable`、PATH discovery 或网络下载；
- A/B 创建前发现 config、release、tool 任一双读/mtime/bytes/identity 漂移时稳定 STOP，root 不存在；C fresh
  复验发现漂移时稳定 STOP并保留 B 已创建的 exact root/partial evidence。

本任务只冻结上述证明字段；不得自行挑选真实 G1/config/tool 路径，也不得宣称它们当前 READY。

### 5.5 资源与执行边界

真实执行必须另行申请：唯一 actual worker、CPU/affinity/线程预算、py312/Qlib、exact cwd/PYTHONPATH、fresh
evidence root、stdout/stderr/exit、最长运行窗口和首失败 STOP。默认禁止 network；若未来确需网络，必须作为独立
授权列出 endpoint、用途、次数和凭据边界。

本任务资源级别固定 `STATIC_ONLY`：零 Python、Qlib、worker、network、new root、request generation、retained
读取、stage、commit、merge。

## 6. Fail-closed 反例

交付与 review 至少逐项证明以下请求在 future execution admission 前必须 STOP：

1. `resume=true` 或缺失/非 bool resume；
2. A 阶段 controlled root 已存在，或拟议路径落入 tracked src/tests/docs/config、retained/legacy/system temp/home；
3. B 创建结果非 empty native real directory、发生创建竞争，或为 symlink/reparse；
4. G1 release 不是当前 public fresh verifier 的 exact 有效返回；
5. fold 缺失、重复、次序漂移或两 fold tool spec 不同；
6. config/tool/request 在校验期间发生 same-size bytes 替换；
7. python/dump tool path、size、SHA、timeout、code version 任一漂移；
8. package-owned callable 被单侧或双侧同一 impostor 替换；
9. request 使用 LOCKED retained 的任一路径或 identity；
10. C 阶段任一失败后 carrier 自动删除 root/partial evidence，或错误声称 root 仍不存在。

反例只做静态源码映射，不运行探针或构造真实文件。

## 7. 交付要求

implementation 交付报告必须包含：

- 权威入口与 request schema 的源码定位；
- 待未来 run package 填入的 exact identity/evidence 清单，不填写猜测路径或 SHA；
- 十类反例与对应 fail-closed guard；
- 唯一未决资源/用户选择；
- 明确 `UNRUN` 表：Python、Qlib、worker、network、request、root、retained、Gate；
- 状态只能是 `ACTUAL_SUCCESSOR_RUN_ADMISSION_CONTRACT_FROZEN` 或 `CONTRACT_STOP`。

原 delivery 的 `CONTRACT_STOP` 章节与事实不得删除、改写为误报或伪装成首轮通过；implementation 必须在同一
delivery 追加 `REFREEZE` 章节，说明旧冲突、A/B/C 修订、root 保留语义及新的通过条件。

reviewer 必须独立挑战：是否暗含第二套 schema/stage/Gate、是否偷读 retained、是否把“代码入口存在”写成真实
Qlib ready、是否遗漏 zero-write/no-clobber、是否留下可由执行者猜测的路径或身份。

## 8. 通过条件与后续

STATIC_ONLY 通过条件：

- actual dirty exact 为 taskbook + delivery + review；cached=0；`git diff --check` PASS；
- 三文档 UTF-8 LF、trailing whitespace=0、single EOF LF；
- production/tests/config/retained/ignored evidence 零改动；
- independent `REVIEW_PASS`，且不出现任何真实路径、凭据或伪造 READY 结论。

通过后仅允许向中央提交“future actual-run package freeze request”。在中央明确批准 request 生成位置、fresh
controlled root、G1/config/toolchain identity 和资源租约前，不得运行 CLI。

边界保持：actual worker、真实 Qlib、new root、retained resume、Linux、M3 Gate 全部 OPEN。
