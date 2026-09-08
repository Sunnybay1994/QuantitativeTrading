# M2-SHARED-CROSS-SECTIONAL-RANK 公共边界独立初验报告

> 当前结论：`FINAL_EVIDENCE_REVIEW2_PASS`
>
> 历史实现静态结论：`STATIC_REVIEW_PASS`
>
> 当前严重度：`P0=0 / P1=0 / P2=0`
>
> 本轮资源边界：`STATIC_ONLY / ZERO_EXECUTION / PYTHON0 / STAGE0 / COMMIT0`
>
> 审查者：未参与本任务实现的独立静态 reviewer

## 1. 审查身份与冻结输入

本轮只读审查 worktree：
`F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\framework-m2-shared-cross-sectional-rank`。
fresh 身份为：

- HEAD/exact base：`dfe49df5e8dfd9d929eb8ad196beced1da19715d`；
- branch：`codex/framework-m2-shared-cross-sectional-rank`；
- cached diff：0；
- 审查开始时 dirty scope 仅为 taskbook、production、unit、integration、delivery 五个预期
  untracked 路径；review 路径不存在。

首次实现静态审查的冻结输入逐项复算如下：

| 路径 | bytes | SHA-256 |
|---|---:|---|
| `docs/framework/tasks/M2_SHARED_CROSS_SECTIONAL_RANK公共边界任务书.md` | 15485 | `4e00a49da30fd40aee678d37df84ad61c8f7733f1545abd296c6e48103306650` |
| `src/quant/factors/cross_sectional_rank.py` | 4417 | `686df676bc484d85ea43f8a0c73ab6e22450a8cc0e5beb02ffc0dee88cbee30d` |
| `tests/unit/test_cross_sectional_rank.py` | 7808 | `67d602e4922849e88513e894e5e7133bc4f6567d9b076c6277ebb22266954479` |
| `tests/integration/test_shared_cross_sectional_rank_consumers.py` | 2462 | `589be42a432d847b6e1c3357973510958657f7f7462e5bb8b7e6a046946768c4` |
| `docs/framework/deliveries/M2_SHARED_CROSS_SECTIONAL_RANK公共边界交付报告.md` | 5083 | `697ebb7bed73d660791081a16bb56d4550482f42cc381d2769d7dc917d50bf7b` |

上述输入在形成结论前未发生 identity 漂移。本报告是 reviewer 唯一获准写入路径；其最终 bytes/SHA
由收件 transcript fresh 计算，避免在报告内形成自指 identity。

FINAL_EVIDENCE_REVIEW 收到的新版 delivery identity 为 6394 bytes / SHA-256
`042808d05b92fc7efa084c469fca005242c20dea2b9a91d6c64ab1247edc01b1`。production、unit、
integration 与 taskbook identity 均保持冻结值，没有因 Validation1 发生代码或测试漂移。

## 2. 历史实现静态结论

`STATIC_REVIEW_PASS / P0=0 / P1=0 / P2=0`。

未发现需要返工的生产逻辑、合同、测试、scope 或证据边界问题。该结论只证明冻结 bytes 的静态一致性；
不证明 Polars 表达式已执行，不提升为 Windows 开发验证、Linux/WSL Gate、consumer 迁移、合流或因子
有效性结论。

## 3. 合同—实现—测试映射

### 3.1 rank 数学与分组有效集合

- `_compute_rank` 使用 `value.count().over("signal_date", "component")`，其中 count 只计非 null 值，
  与每个 `signal_date × component` 独立有效集合和 `n` 的定义一致；没有组件共同交集或跨日聚合。
- `rank(method="average").over("signal_date", "component")` 冻结 ascending average-tie rank；归一式为
  `(average_rank - 1.0) / (n - 1)`，未改成 dense/min/max/first/descending 或 percentile bucket。
- `value is null OR n < 2` 明确输出 Float64 null；全相等 `n >= 2` 由 average rank 得到严格 `0.5`。
- unit 覆盖 `n=2`、partial tie、全相等、`n=0/1`、局部 null、组件异构有效集合、交集泄漏反例、
  多日多组件及输入置换。integration 分别提供 R14 单组件、R15 三组件和 R21 两组件中立 fixture。

### 3.2 exact schema、key、canonical order 与输出不变量

- 输入以 exact type、非空、ordered columns 和 exact dtypes 校验；没有隐式 cast、补值或删行。
- null key、duplicate exact key 和非有限非 null value 均在 compute 前 fail closed。
- 输出只选择冻结四列并按 `signal_date, component, symbol` 排序；返回前复核 exact columns/dtypes、
  height、key 1:1、canonical order、无 duplicate、null pattern、finite/range。
- `normalized_rank == 0.0` 分支把负零规范化为 Float64 正零。unit 明确检查输出 identity、range、finite、
  key 1:1、置换稳定及零符号。

### 3.3 stable total error precedence 与公共异常表面

- `_validate_input` 严格按 TYPE → SCHEMA → KEY_NULL → DUPLICATE_KEY → NON_FINITE 执行；每一类使用
  全 frame 聚合判断，不依赖首个坏行或输入遍历顺序。
- 三组 compound-invalid unit 分别锁定 SCHEMA、KEY_NULL、DUPLICATE_KEY 胜出，并枚举行置换；
  `_assert_error` 逐字断言 `exc.args == (CODE,)`、`str(exc) == CODE` 和无路径泄漏。
- compute 只在输入全部通过后进入。compute/output 阶段的非公共 `Exception` 被收敛为 exact
  `CROSS_SECTIONAL_RANK_INTERNAL_INVARIANT`；既保留自身 exact invariant，也不捕获 `BaseException`。
- 任一失败均通过异常终止，没有 partial frame、empty placeholder 或外部写入表面。

### 3.4 公共边界与 consumer 隔离

- production 只 import Polars；没有 data/repository/runner/label/economic/trial/network、文件读写、
  consumer import 或可变全局状态。
- 公共 identity 仅为 `quant.factors.cross_sectional_rank.rank_cross_sectional_components`；没有修改
  facade、R14/R15/R21 consumer、Schema、config、data 或 research worktree。
- integration 只从冻结 fully-qualified module import，同一 helper 接受三个 consumer 的中立长表，
  未复制或 import 因子公式。consumer 仍必须等待公共 helper 合流后分别迁移。

## 4. reviewer 独立对抗反例

实现者现有测试未使用以下精确 fixture：同一日、同一 component 的四个有效值按 symbol canonical 顺序为
`[1.0, 1.0, 1.0, 9.0]`。

- frozen average ranks 应为 `[2.0, 2.0, 2.0, 4.0]`；
- frozen normalized ranks 应为 `[1/3, 1/3, 1/3, 1.0]`；
- dense/min rank 会给前三项 `0.0`，错误 percentile/dense 分母也不会得到 `1/3`。

静态代入当前实现：`rank(method="average")` 给三重 tie 平均名次 2，非 null count 给 `n=4`，现有
`(average_rank - 1) / (n - 1)` 因而得到 `1/3`；反例静态通过。该证明不替代未来真实 Polars runtime test。

## 5. scope、diff 与文本卫生

在写入本报告前：

- actual implementation exact4 为 production、unit、integration、delivery；taskbook 只读；
- review 写入后构成任务书冻结的 future exact5；没有第六个业务路径；
- `git diff --cached --name-status` 为空；没有 stage/commit/merge/rebase；
- taskbook、production、unit、integration、delivery 均为 strict UTF-8、no BOM、LF-only、CR0、NUL0、
  trailing whitespace 0、single EOF LF；三条代码/测试路径最大行长分别为 85/93/86，均不超过 100。

由于业务文件均为 untracked，普通 `git diff --check` 不能单独证明其 hygiene；本轮使用逐文件 bytes/text
检查，未把空洞 diff 结果当作证据。报告写入后的 final status、exact scope、review bytes/SHA 和 hygiene
由收件 transcript 再次核验。

## 6. 首次实现静态审查时的验证边界

首次实现静态审查没有运行 Python、pytest、Ruff、mypy、cold import、真实数据、网络、runner、trial 或
economic I/O，因此当时状态为：

- focused unit/integration：`UNRUN`；
- Ruff/mypy/cold import：`UNRUN`；
- Windows development validation：`UNRUN`；
- Linux/WSL Miniforge `base` Gate：`UNRUN / OPEN`；
- consumer migration、merge、factor/economic validity：`NOT PERFORMED`。

该历史边界已被第 7 节收到的 Windows Validation1 保存证据部分更新；即使 Windows 绿色，也不能替代
合流候选上的 Linux/WSL Gate。

## 7. 首轮 FINAL_EVIDENCE_REVIEW 历史

### 7.1 首轮结论

`FINAL_EVIDENCE_REVIEW_FAIL / P0=0 / P1=1 / P2=0`。

历史 `STATIC_REVIEW_PASS` 继续有效：生产逻辑、unit、integration 和独立对抗反例没有发现静态问题。
Windows Validation1 的阶段输出也形成了可核验的绿色证据，但 final scope/resource 现场没有闭合，当前不能
签发最终 evidence PASS。

### 7.2 Validation1 evidence root、hash 与 exit

只读核验 evidence root：
`artifacts/agent_runs/m2-shared-cross-sectional-rank-windows-validation1-20260902T130000Z`。
该根含 exact19 文件：六组 stdout/stderr/exit 加一份 `summary.log`，无缺件。

| 阶段 | stdout 结果 | bytes / SHA-256 | exit |
|---|---|---|---|
| focused unit | `12 passed in 2.10s` | 101 / `749b9cfcca00ceb6d66adc80b2dc8dfbb6b8b5a93f59205be7da53b402241eea` | exact `0\n` |
| focused integration | `3 passed in 1.75s` | 100 / `e866805c1e524fecead47d5f1d08f3dc401557033fea4811e89730ad1d2b258f` | exact `0\n` |
| Ruff exact3 | `All checks passed!` | 20 / `a4443afdcfb6d7363adb285762515ccf7cf50473b1a05c20c1a50f6bed4d26b0` | exact `0\n` |
| mypy production | `Success: no issues found in 1 source file` | 43 / `8e63ae22e8213e327a5e9cbd584067681681bd8ef7f25c869877887ccdcfc4ff` | exact `0\n` |
| cold import | `COLD_IMPORT_PASS` | 18 / `f2fa5abb3a94f7638617a512fe5f805721df611e0918049ef9780a23a332da3b` | exact `0\n` |
| exact6 scope | 六条冻结路径 | 393 / `c9e020e4ffdcc157944e5ddded4fcd0b823ef314322bc5a3ed564a597637b618` | exact `0\n` |

六个 stderr 均为 0 bytes / SHA-256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`；六个 exit 均为 2 bytes、
SHA-256 `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`。`summary.log`
为 103 bytes / SHA-256 `e7eec3e779bf9152673f07663e950fdb66b5ccc17874109ec2f21c7a61c417b7`，
逐项记录六个 exit 0 和 `VALIDATION1_PASS`。上述 hashes、bytes、文本和 exit 与新版 delivery 一致。

### 7.3 final scope、diff、process 与 resource 现场

- `git status --porcelain` 的可见 dirty path 正好为 taskbook + production/unit/integration/delivery/review
  六条；`06_scope.stdout.log` 也逐字列出这六条。
- cached diff 为 0；当前 ordinary `git diff --check` 无输出。由于六条业务路径均为 untracked，普通
  diff-check 本身是空洞证据；本 reviewer 对 exact6 逐文件检查，均为 strict UTF-8、no BOM、LF-only、
  CR0、NUL0、trailing whitespace 0、single EOF LF。
- current live snapshot 为 Python/pythonw 进程 0、processor affinity exact `0xF00` residue 0。
- Linux/WSL Miniforge `base` 仍为 `UNRUN / OPEN`；证据没有宣称 consumer 迁移、合流、项目 Gate 或
  rank 经济有效。

### 7.4 P1：ignored Ruff cache 使 exact scope/resource closure 失实

- 现象：worktree 根存在 ignored `.ruff_cache/`，其中含 `.gitignore`、`CACHEDIR.TAG` 和
  `0.15.22/` 下三个 cache 文件；因此 final filesystem scope 不只有 exact6，cache/resource 也未清零。
- 根因：Ruff 阶段产生或遗留了默认 cache，但 final cleanup/scope 只核了 Git-visible paths、指定
  temp/basetemp、进程和 affinity；ignored cache 不会出现在 `git status`、ordinary `git diff --check`
  或当前 `06_scope.stdout.log` 中。
- 应遵循规则：任务书第 6.2 节明确“不允许临时仓库目录、cache 或第六个业务路径”；final scope 必须同时
  查 Git-visible 与 ignored/temp/cache 现场，`RESOURCE_RELEASE` 只能在全部残留关闭后声明。
- 最小复现：只读检查 worktree 根可见 `.ruff_cache`；目录创建/写入时间为
  `2026-09-02T11:05:38+08:00`，当前含 5 个文件，故 `cache0` 为假。
- 新增验证：在获授权的返工链清理该 exact cache 后，增加 ignored-aware residue 检查；至少显式断言
  `.ruff_cache`、`.pytest_cache`、`.mypy_cache`、`__pycache__`、basetemp 和任务专属 temp 全部不存在，
  并把非空检查输出及 exit 固化到 evidence root。
- 通过条件：同一 worktree 下 `.ruff_cache` 不存在；ignored-aware residue 检查 exit 0；fresh exact6、
  cached0、direct hygiene、Python/pythonw0、`0xF00` residue0 仍成立；delivery 撤销或重新证明
  `RESOURCE_RELEASE` 后，由同一 reviewer 复核。reviewer 不越权清理现场。

### 7.5 证据边界

本轮只读取冻结文件、evidence bytes/hash/exit 和 current live metadata，没有运行 Python、pytest、Ruff、
mypy、cold import、数据、网络或任何业务验证。Windows 阶段绿色结果是已保存证据的复核结论，不是本轮
重跑；Linux/WSL Gate 保持 OPEN。

## 8. FINAL_EVIDENCE_REVIEW2

### 8.1 当前结论

`FINAL_EVIDENCE_REVIEW2_PASS / P0=0 / P1=0 / P2=0`。

首轮 final evidence review 的 P1 finding 历史完整保留在第 7 节；本轮只判定其冻结通过条件是否已由
fresh 现场满足，不删除、不降级或改写原 FAIL。生产实现静态审查和 Windows Validation1 阶段结果继续有效。

### 8.2 新版 delivery 与冻结产品身份

本轮收到 delivery 7399 bytes / SHA-256
`c4d179ebecc839e2da39e30874190ee52256447520ee82c16d5c70f374b60bc4`。该版本永久记录首轮 review
12227 bytes / SHA-256 `bd4907c5ccfd75f824894d5a7c9790b33d4a14f879f4d771ce7bf47874e968c3` 及 P1
finding，并明确清理只针对 worktree-root `.ruff_cache`，未重跑产品验证、未删除 retained evidence。

冻结产品身份 fresh 复算仍为：

- production：4417 bytes / `686df676bc484d85ea43f8a0c73ab6e22450a8cc0e5beb02ffc0dee88cbee30d`；
- unit：7808 bytes / `67d602e4922849e88513e894e5e7133bc4f6567d9b076c6277ebb22266954479`；
- integration：2462 bytes / `589be42a432d847b6e1c3357973510958657f7f7462e5bb8b7e6a046946768c4`。

因此清理没有改变生产或测试冻结 bytes。

### 8.3 原 P1 关闭证据

fresh ignored-aware 全树只读扫描结果：

| residue 类别 | count |
|---|---:|
| `.ruff_cache` | 0 |
| `.pytest_cache` | 0 |
| `.mypy_cache` | 0 |
| `__pycache__` | 0 |
| basetemp / task-specific Validation1 temp | 0 |

`.ruff_cache` 已按精确目标删除，不存在扩大清理；首轮记录的其他 cache/temp 类也继续为 0。由此第 7.4 节
要求的 cache0/ignored-aware residue 条件已经满足，原 P1 关闭。

### 8.4 evidence retention、scope、diff、process 与 resource

- Validation1 evidence root 仍存在 exact19 文件；六个 stdout、六个 exact0 stderr、六个 exact `0\n`
  exit 与 `summary.log` 的 bytes/SHA 均逐项保持第 7.2 节冻结值，未被清理或改写。
- `git status --porcelain` 的可见 dirty scope 仍为 taskbook + production/unit/integration/delivery/review
  exact6；cached0；ordinary `git diff --check` 无输出。
- 对 exact6 的 direct non-vacuous hygiene 检查为 strict UTF-8、no BOM、LF-only、CR0、NUL0、
  trailing whitespace 0、single EOF LF。ordinary diff-check 不单独承担 untracked hygiene 证明。
- current live snapshot：Python/pythonw=0，processor affinity exact `0xF00` residue=0，四类 cache、
  basetemp 和 task temp residue=0；据此 `RESOURCE_RELEASE` 当前有 fresh 闭合证据。

### 8.5 最终证据边界

本轮为零执行复核：没有运行 Python、pytest、Ruff、mypy、cold import、数据、网络、runner、trial 或
economic I/O；仅只读检查 frozen bytes/hash、保存的 exit/log 和 current filesystem/process metadata。

当前 PASS 的上限是冻结实现的独立静态 review、已保存 Windows Validation1 证据及其资源清理闭包。
Linux/WSL Miniforge `base` 仍为 `UNRUN / OPEN`；consumer 未迁移、未 merge、未关闭项目 Gate，也没有
rank 经济有效性结论。
