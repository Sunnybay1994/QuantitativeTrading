# M3-G8F-R2C Actual Successor Run Admission 独立初验报告

日期：2026-08-26
身份：未参与 implementation 的全新独立静态初验 Agent（STATIC_ONLY；无委派 / 无 subagent）
task id：`M3-G8F-R2C-ACTUAL-SUCCESSOR-RUN-ADMISSION`
exact base / HEAD：`27d42840c08d883d08c9578b3c2802b4630bd0f8`（一致）
branch：`codex/m3-g8f-r2c-actual-successor-run-admission`
worktree：`artifacts/dev_worktrees/m3-g8f-r2c-actual-successor-run-admission`
唯一写入：本报告
结论：**F1_REVIEW_PASS**（§8；§0–§7 首轮 **REVIEW_FAIL** 原文保留）
终态上限声明：可支持向中央提交 future actual-run package freeze request；actual worker / 真实 Qlib / new root / retained resume / Linux 终验 / M3 Gate 全部 **OPEN**。本审查（含 F1 复验）**未** 运行 Python / pytest / Ruff / mypy / Qlib / network，**未** 创建或 probe request/root。

## 0. 审查边界

- 已完整阅读：任务书 `docs/framework/tasks/M3_G8F_R2C_ActualSuccessorRunAdmission任务书.md`、交付报告（含首轮 `CONTRACT_STOP` §1–§8 与 REFREEZE §9）、权威只读源码 `successor_bridge.py` / `run_successor.py` / `successor_runtime.py`（及为定位调用边界所需的 upstream/downstream 公开符号引用）。
- 任务书 / 交付 / production / tests / config / retained / ignored evidence：**只读**；未改、未 stage、未 commit。
- **STATIC_ONLY**：零 Python、pytest、Ruff、mypy、Qlib、worker、network、request 生成、controlled root mkdir/probe、LOCKED retained 读取。
- dirty（写入本报告前只读观察）：仅 taskbook + delivery 两份 `??`；HEAD=exact base；`git diff --cached` 空；`git diff --check` 空输出；production/tests 相对 HEAD 无改动。写入后 exact3 = task + delivery + 本 review。
- 任务书 / 交付字节形态（非 Python）：UTF-8 无 BOM、无 CR、无行尾空白、单 EOF LF。

## 1. 强制核对项（对照派发 + 任务书 REFROZEN §5–§8）

| # | 核对点 | 静态结论 | 证据摘要 |
| --- | --- | --- | --- |
| 1 | exact3 写白名单 | **通过** | 仅三文档；未见 production/tests/config/roadmap/`__init__`/retained 改动 |
| 2 | 首轮 `CONTRACT_STOP` 历史保留 | **通过** | 交付 §1–§8 完整保留；§9 声明不得改写为误报；旧冲突→A/B/C 映射可读 |
| 3 | A/B/C 生命周期与 bridge「调用时已存在」对齐 | **通过（合同面）** | A 尚不存在；B 授权单步 mkdir；C 前必须为 B 验真 existing real dir；与 `successor_bridge`「永不 mkdir + `_require_real_directory`」一致 |
| 4 | request 相对 vs 中央绝对双记录 | **通过（合同面）** | 交付 §9.3：request 仅 PROJECT-relative；中央另记 resolved absolute；禁绝对写入 request / cwd/env/latest/glob；对齐 `_require_project_relative`（拒 `\`/`:`/`/`/`.`/`..`） |
| 5 | PROJECT ignored 运行区 vs 禁止区 | **通过（合同面）** | 允许 `project_root` 内 ignored（如未来批准的 `artifacts/...`）；禁 tracked `src/`/`tests/`/`docs/`/`configs/`、旧 worktree、LOCKED retained、legacy/data、system temp、home；与 PROJECT-only 源码拓扑不再字面冲突 |
| 6 | pre-create 不存在 vs post-create/CLI 保留 | **通过（合同面）** | §9.4：A/B 创建前失败→root 不存在；B 创建后与 C 任一失败→保留 exact root/partial；禁自动删除或谎称仍不存在 |
| 7 | PROJECT-only + 两 fold config root 接合 | **部分失败** | 源码：`project_stage_root`×2 必须唯一且 `== controlled`（`successor_bridge` 358–384）；**但不**对两 fold `tracking.artifact_root` 文本与 request `controlled_output_root` 做三方字符串逐字比较（见 F1） |
| 8 | 零 request/root/Qlib 产品执行 | **通过** | 交付 UNRUN 表与 §9.8；本审查未生成/probe；占位均为 `<UNRESOLVED>`，无伪造 READY |
| 9 | 两次未授权 `python -c` | **通过（诚实性）** | 交付 §9.9 永久更正：违反 STATIC_ONLY；解释器/时间戳 UNKNOWN；**零验证价值**；不得计入通过证据。本审查采纳该定性，不洗白 |
| 10 | 无第二套 schema/stage/Gate；无偷读 retained | **通过** | schema/入口定位到 `REQUEST_SCHEMA_ID`/`run_successor`/`run_production_successor_bridge`；stage/Gate 交 package-owned runtime；retained `UNRUN` 且禁止 |
| 11 | 十类反例静态映射 | **大体通过 / F1 侵蚀 C 接合表述** | §9.5 覆盖任务书 §6 十项；A 落点与 C 保留语义分离正确；但 C「逐字」被写成 bridge 已保证（F1） |

## 2. 发现分级

### [P1] REFREEZE 将「三字段逐字相同」过归因于 bridge — 交付 §9.2 C

任务书 §5.2 C 与交付 REFREEZE §9.2 C 均要求：两 fold `tracking.artifact_root` 与 request `controlled_output_root` **逐字相同**，并解析到中央记录的 exact absolute root；交付将该义务写成「bridge 再次 fresh」已覆盖。

权威源码实际保证为：

1. request 字段经 `_require_project_relative` 得到相对路径；
2. `controlled = _require_real_directory(project / relative)`，且 `controlled.relative_to(project).as_posix()` 与 request 相对串相等；
3. 每个 fold 经 `project_stage_root` 读取 config 的 `tracking.artifact_root`，解析为 real directory 后，`len(set(stage_roots)) == 1` 且 `stage_roots[0] == controlled`。

**不存在**对 `loaded.section("tracking")["artifact_root"]` 与 request `controlled_output_root` 的字符串三方 `==`。在大小写不敏感卷或其它「异文同解析」场景下，config 文本可与 request 字段逐字不同而仍通过 bridge。

后果：准入合同把源码未提供的保证写成已由 CLI/bridge 强制，未来 actual-run package 可能省略离线逐字证明。STATIC_ONLY 准入冻结不得靠猜测补第二套比较器，也不得把 Path 相等美化为逐字相等。

### 无 P0

入口身份、A/B/C 时序消解旧 STOP、相对/绝对双槽、禁止区、失败保留、identity 占位不填猜测、OPEN 边界与两次 `python -c` 的过程违规诚实披露，主轴可读且与「不改 bridge」约束一致。本轮 FAIL 主因是 **C 接合「逐字」证据过声明（F1）**。

## 3. 实现者未使用的对抗反例（新增）

### 反例 R1 — 两 fold `artifact_root` 异文、同解析根（case / 等价拼写）

实现者 §9.5 覆盖 fold 乱序/重复与 tool spec 不等，**未**钉「config 文本 ≠ request 相对串但仍解析到同一目录」。

**最小静态复现（未执行）：**

1. request `controlled_output_root` 精确为 `artifacts/run_a`（相对）。
2. fold_001 / fold_002 的 `tracking.artifact_root` 设为同目录的异文（例如仅 ASCII 大小写不同的 `Artifacts/run_a`），其余字段合法；中央绝对路径记录指向该目录。
3. B 已创建 empty real dir；调用 `run_production_successor_bridge`。
4. 按当前源码：在大小写不敏感 FS 上，`stage_roots[0] == controlled` 可成立 → **INPUT 门禁可能放行**。
5. 按 REFROZEN 合同字面「逐字相同」：必须在进入 C 前 STOP；该 STOP **不能**指望现有 bridge 字符串比较。

**通过条件：** 交付必须改写为：bridge 只保证解析后单根 Path 相等；三字段字符串逐字相等由 future run package 在 B 前离线证明并写入中央旁路记录；或经理重冻任务书，使权威要求与源码 Path 相等语义一致。不得在未改源码时继续宣称 bridge 已做逐字。

### 反例 R2 — B→C 窗口向 empty root 投放 sentinel 文件

实现者反例 3 钉 B 创建后非空 STOP；反例 10 钉 C 失败后删根。**未**钉「B 验真 empty 之后、CLI argv 之前」被投放文件。

**最小静态复现（未执行）：**

1. 完成 B：exact root 为 empty native real directory。
2. 在调用 `python -m quant.research.m3.run_successor` 前，向该 root 写入任意 sentinel（非 symlink）。
3. 调用 bridge：`_require_real_directory` **不**检查 empty → 可进入后续 fresh config/release 路径。
4. 合同预期：C 前置条件「B 验真 empty」被破坏时，future run package / carrier 必须在调用前再次非跟随 empty 检查并 STOP；不得把「bridge 已接住非空」写进冻结保证。

**通过条件：** 准入合同明确 empty 复检所有权在 C 调用方（非 bridge）；交付反例表增加本窗口，避免执行者假设 bridge 重验 empty。

### 反例 R3 — request `controlled_output_root` 写入绝对路径，中央「双记录」看似齐全

实现者禁止绝对写入 request，但反例表侧重 A 落点黑名单与 retained。补充绝对路径形态。

**最小静态复现（未执行）：**

1. 中央旁路已记录合法 resolved absolute。
2. request 字段却写入该绝对串（含盘符 `:` 或 leading `/`）。
3. `_require_project_relative` → 稳定 `SUCCESSOR_BRIDGE_INPUT_INVALID`。
4. 预期：不得因中央绝对记录存在而放行；双记录不能互相替代。

**通过条件：** 离线 request 生成器测或交付映射明确指向 `_require_project_relative` 拒绝对形态；中央绝对仅旁路。

### 反例 R4 — 拟议相对路径落在 tracked `docs/` 下被误当「PROJECT-only 即合法」

实现者反例 2 含 tracked 禁区，但未强调 **bridge 不会执行该禁区策略**。

**最小静态复现（未执行）：**

1. A/B 若被跳过，直接准备 `docs/.../out` 为 existing empty real dir，request 相对路径指向它，两 fold `artifact_root` 同串。
2. bridge PROJECT-only 与 real-dir 检查可对「位于 docs 下的目录」**放行**（源码无 `src/tests/docs/configs` 前缀黑名单）。
3. 合同预期：A 阶段即 STOP；禁区由 future run package 离线策略强制，不得写成 bridge 行为。

**通过条件：** 交付持续区分「A 策略禁区」与「bridge PROJECT-only」；actual-run 离线清单含 tracked 前缀拒绝证据。

## 4. 失败项（现象—根因—规则—最小复现—修正—通过条件）

### F1 — 「逐字相同」过归因于 bridge

| 字段 | 内容 |
| --- | --- |
| 现象 | 交付 §9.2 C 声称 bridge fresh 保证两 fold `artifact_root` 与 request `controlled_output_root` 逐字相同 |
| 根因 | 源码只做解析后 Path 单根相等 + request 相对串与 `relative_to(project)` 相等；无 config 文本三方逐字比较 |
| 规则 | 任务书 §5.2 C、§7（不得暗含与权威源码不符的第二套保证）；AGENTS SSOT：实际实现以代码为准 |
| 最小复现 | 静态对照交付 §9.2 C 与 `successor_bridge._build_runtime_request` 358–384、`project_stage_root` 1593–1610；见 §3 R1 |
| 修正 | 拆分保证：bridge=Path 单根；逐字=B 前离线/中央记录；或重冻任务书与源码语义对齐。更新 §9.5 反例，避免执行者依赖不存在的字符串门禁 |
| 通过条件 | 独立复验确认交付不再把逐字写成 bridge 已强制；R1 窗口有明确 owner；仍不改 production |

## 5. 已通过项（压缩）

- exact3 / HEAD=base / 零 production 改动；任务书与交付 LF/无尾空白形态可读通过。
- 旧 `CONTRACT_STOP` 正确保留；A/B/C 消解「调用前不存在 vs bridge 必须已存在」与「整树禁止 vs PROJECT-only」旧冲突。
- 入口与 schema 只定位源码：`m3-successor-bridge-request-v1`、`run_successor --request`、`run_production_successor_bridge`；无第二套 parser/Gate 顺序。
- bridge/CLI 无 `mkdir`；失败保留语义与 A 零写分离清楚。
- identity A1–A22 不填猜测路径/SHA；Qlib/Gate/worker **OPEN**；无「入口存在⇒READY」。
- 两次 `python -c`：永久视为 STATIC_ONLY **过程违规**，产品验证价值 = 0；本审查不引用其输出为通过证据。

## 6. 未运行与未关闭边界（强制）

| 项 | 状态 |
| --- | --- |
| Python / pytest / Ruff / mypy / cold（本审查） | **UNRUN** |
| 实现者两次 `python -c` | **过程违规**；**零验证价值**；非产品证据 |
| Qlib / actual worker / network | **UNRUN** / **OPEN** |
| request 生成 / controlled root 创建或 probe | **未执行** |
| LOCKED retained 读取 | **未执行**（且禁止） |
| M3 Gate / 真跑 / Linux 终验 | **OPEN** |
| future actual-run package freeze 申请 | **阻断**（需返工至 `REVIEW_PASS`） |

## 7. 结论

**REVIEW_FAIL**（P1/F1：REFREEZE 将 config/request 根路径「逐字相同」过声明为 bridge 已强制，与权威源码 Path 单根相等语义不符）。

返工仅限交付报告（必要时经理重冻任务书措辞）；**不得**改 production/tests；**不得**用 Python/Qlib/request/root 探针「补证」。复验须由未参与实现的独立上下文对照 F1/R1–R4 只读闭合后，方可 `REVIEW_PASS` 并仅允许向中央提交 future actual-run package freeze request。

---

## 8. F1_REVIEW（对照经理修正后任务书 §5.2 C + 交付 §9.2 C / §10）

日期：2026-08-26
身份：与首轮同一独立初验者；未参与实现
范围：只读终稿任务书、交付（含 §10 F1_REWORK）、本报告 §0–§7；权威 bridge/runtime **只读**复核 Path 合同
本轮唯一写入：本报告追加本节；**未**改 task/delivery/source/tests
STATIC_ONLY：零 Python / Qlib / network / root / request / stage / commit

### 8.1 F1 闭合核对

| # | 检查 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 任务书 §5.2 C 权威合同 | **通过** | request canonical PROJECT-relative 解析到中央 exact absolute；两 config `artifact_root` 经 `project_stage_root` 得唯一 `Path` 且 `== controlled`；明文：**不**保证三方原始字符串逐字相同；**不得**虚构第二套字符串比较器 |
| 2 | 交付 §9.2 C 与 §10.2 对齐源码 | **通过** | 同 Path 合同；显式引用 `len(set(stage_roots)) == 1` 且 `stage_roots[0] == controlled`；否定三方逐字/按字符相等与第二套比较器/normalize/自研谓词 |
| 3 | 无三方 raw-string 相等主张残留为现行依据 | **通过** | §9.2 C 现行正文已改正；F1 注记 + §10.1 将旧「逐字相同」标为历史过述、**不作为准入依据**；现行保证面无第二比较器 |
| 4 | 与 `successor_bridge` / `project_stage_root` 一致 | **通过** | 只读复核：相对→`_require_real_directory`；config 经 `project_stage_root`；单根 Path `== controlled`；无 config 文本三方 `==` |
| 5 | 首轮 §0–§7 `REVIEW_FAIL` / F1 六段式 | **保留** | 未删除、未改写为误报；本轮仅追加闭合 |

### 8.2 对抗反例 R1 状态（首轮提出）

首轮 R1 在旧「逐字」合同下要求异文同根 STOP。经理/交付已把权威改为 **Path 相等**：异文若解析为同一 `Path`，bridge 放行与源码一致，**不再**构成合同违反。R1 通过条件（改写交付或重冻任务书与 Path 语义对齐）已满足。残留提醒（不阻断）：未来 run package 若业务上仍想约束字符串形态，须自行离线证明，**不得**写成 bridge 保证。

R2（B→C empty 窗口）、R3（绝对 request 字段）、R4（tracked 禁区属 A 策略）仍为执行期提醒；非 F1 阻断项；交付仍区分 A 策略禁区与 bridge PROJECT-only。

### 8.3 回归复核（非 F1 主轴，强制保留）

| 项 | 结论 |
| --- | --- |
| exact3 | **通过**：dirty 仅 task + delivery + 本 review；HEAD=`27d42840…`；cached=0；production/tests 无改动 |
| A/B/C 生命周期 | **通过**：A 不存在 / B 授权 mkdir / C 前 existing；失败保留语义未回退 |
| 相对 vs 中央绝对双记录 | **通过**：§9.3 仍仅旁路绝对；不写入 request 字段 |
| 两次 `python -c` | **通过（诚实性）**：§9.9 仍永久定性为 STATIC_ONLY 过程违规、**零验证价值**；本复验不引用为产品证据 |
| 产品 UNRUN / Gate OPEN | **通过**：无 request/root/Qlib 执行；无伪造 READY |

### 8.4 发现分级（F1 复验）

**无新 P0/P1。** 前轮 P1/F1 已按权威 Path 合同闭合。

### 8.5 未运行与边界（强制保留）

| 项 | 状态 |
| --- | --- |
| 本轮 Python / pytest / Ruff / mypy / Qlib / network | **UNRUN** |
| request / controlled root 创建或 probe | **未执行** |
| LOCKED retained | **未读取** |
| actual worker / 真实 Qlib / new root / retained resume / Linux / M3 Gate | **OPEN** |

### 8.6 F1 结论

**F1_REVIEW_PASS**（任务书 §5.2 C 与交付 §9.2 C / §10 将 bridge 描述收敛为：request 相对解析到中央绝对；各 config `artifact_root` 经 `project_stage_root`；唯一解析 `Path` 等于 controlled；无三方 raw-string 相等、无第二套比较器）。可向中央提交 future actual-run package freeze request；**不**关闭 actual worker / Qlib / new root / retained / M3 Gate。
