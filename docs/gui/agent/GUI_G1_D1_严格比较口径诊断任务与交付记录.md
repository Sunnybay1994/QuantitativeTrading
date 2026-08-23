# GUI G1-D1 严格比较口径诊断任务与交付记录

## 1. 状态与拓扑

- 冻结基线：`2a376100a50fb0ad5040048e4ba2aae8c974ace9`
- 分支：`codex/gui-g1-d1-comparison-diagnostics`
- 独立 worktree：
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\gui-g1-d1-comparison-diagnostics`
- owner：GUI session；根工作树及中央 SSOT 保持只读。
- 当前状态：**开发检查、真实 Probe A 与统筹冻结的 Probe B 等价派生反例均已通过，G1-D1 验收闭合，可形成
  exact 7 路径安全提交**。
- 当前证据边界：Windows Streamlit AppTest、定向 pytest/Ruff/mypy、真实 3-run mismatch probe，以及一次
  `DERIVED_REAL_BYTES_OUTPUT_FAIL` 已形成证据。真实 catalog 仍不存在“同口径但既存 output 失败”组合；
  等价反例是 canonical 字节的隔离副本篡改，不是既存坏 run。未运行 browser、全量回归或 WSL Gate，不得
  扩大表述。

历史 G0、G1 和 G0-C4 证据继续由
[`docs/gui/roadmaps/GUI_投研工作台路线图.md`](../roadmaps/GUI_投研工作台路线图.md) 记录；它们不是 G1-D1
代码和页面已经验证的替代证据。

## 2. 目标

当研究员显式选择 2–4 个 lightweight runs，现有严格比较因已发布合同字段不兼容而精确返回
`COMPARISON_CONTRACT_MISMATCH` 时，增加最小只读关系诊断，使研究员知道哪些机器合同字段与第一项选择
相同或不同，同时保持比较、输出完整性和 NAV 的全部 fail-closed 语义。

本包不解释字段原值或业务含义，不寻找“更接近”的运行，不改变严格比较结论。用户选择第一项只是关系展示
参照，不获得 baseline、benchmark、winner、推荐或准入语义。

## 3. Exact 7 路径白名单

```text
src/quant/gui/research_runs.py
src/quant/gui/app.py
tests/unit/test_gui_research_runs.py
tests/gui/test_streamlit_app.py
docs/gui/GUI_产品与技术设计.md
docs/gui/roadmaps/GUI_投研工作台路线图.md
docs/gui/agent/GUI_G1_D1_严格比较口径诊断任务与交付记录.md
```

禁止修改或新增白名单外路径。本次文档冻结仅修改后 3 个文档路径；后续静态实现只可使用前 4 个代码/测试
路径。`README.md`、`项目实施路线图.md`、`pyproject.toml`、`docs/README.md`、领域 Schema/枚举、配置及既有
不可变 artifact 全部锁定。

## 4. 范围

### 4.1 适用入口

- 继续复用现有 G1 “运行比较”页和研究员选择顺序；
- 继续只接收当前 canonical catalog 中的 2–4 个唯一 `ResearchRunSummary`；
- 先调用现有严格 verifier；只有返回的 issue code 精确等于
  `COMPARISON_CONTRACT_MISMATCH` 才构造并展示诊断；
- 选择变化后旧诊断立即失效，研究员必须重新触发严格比较。

### 4.2 关系投影

内部 diagnosis 直接遍历 `_comparison_contract` 返回映射，对当前 14 字段机器合同生成全量关系。字段的唯一
机器清单保留在该函数，产品职责分组见
[`GUI_产品与技术设计.md`](../GUI_产品与技术设计.md#51-g1-严格比较合同)；本任务记录不复制第二份清单。

内部关系的列严格保持用户选择顺序：

- 第一项的全部 14 字段均为 `REFERENCE`；
- 其余项与第一项使用现有 Python exact equality，逐字段只产生 `SAME` 或 `DIFFERENT`；
- `REFERENCE` 只说明关系参照，不能显示或暗示 baseline、benchmark、winner、推荐、优先级或准入身份；

UI 不固定展示 14 行，只渲染内部全量关系中至少含一个非参照 `DIFFERENT` 的字段行；全为 `SAME` 的字段
行不显示。每个保留行只显示 run identity、字段名和 `REFERENCE` / `SAME` / `DIFFERENT`；禁止显示字段
原值、repr、长度、元素、首个差异、摘要、hash/digest、规范化值或可反推出原值的派生内容。

diagnose 与 verifier 必须调用同一 `_comparison_contract`；不得在 helper、UI 或测试辅助生产路径复制另一份
字段集合，不得根据 detail 字符串重新解析字段语义。

### 4.3 错误与失败顺序兼容

保留现有顺序：

1. 选择数量必须为 2–4 且 run id 唯一，否则 `COMPARISON_SELECTION_INVALID`；
2. 对共享 14 字段做 exact 比较；存在差异时返回 `COMPARISON_CONTRACT_MISMATCH`；
3. 只有合同一致后才检查所选运行声明输出合计上限；
4. 只有继续通过后才逐 run 校验 identity、精确输出树、size 与 SHA-256；
5. 只有全部 run 验证后才允许 manifest 证据，随后另行受限读取 NAV。

合同 mismatch 时必须保持：

- issue entry 为 `comparison`；
- detail 仍是现有按字段名排序的 mismatch 字段集合语义；
- comparison 状态为 `BLOCKED` 且 `integrities=()`；
- 不读取、打开或哈希任何 output，不加载 NAV；
- 诊断 helper 不替换 verifier 的 issue，不新增“可忽略”或 warning 状态。

`COMPARISON_OUTPUT_LIMIT`、`COMPARISON_RUN_UNVERIFIED`、`COMPARISON_NAV_UNAVAILABLE`、
`COMPARISON_NAV_LIMIT` 以及任何其他错误码均不得显示合同关系表。

## 5. 明确非目标

- 不放宽、配置或建立第二套比较合同；
- 不展示合同字段原值、结构摘要、长度、digest 或具体差异；
- 不展示部分逐 run metric、output evidence 或 NAV；
- 不计算业务指标、差值、相似度、兼容度、排名、均值、胜负或准入；
- 不自动分组、聚类、增删选择，不寻找、推荐或一键采用兼容子集；
- 不排序或归一化 `candidate_symbols`、`folds`、`cost_multipliers`、metric names 或 `inputs`；
- 不读取 `report.json` 或其他报告补齐解释；
- 不发起研究运行，不接 JobSpec、worker、数据库、M3、PAPER/LIVE 或交易能力；
- 不增加依赖、缓存、catalog 数据库、任意路径、上传 manifest 或外部写副作用。

## 6. 验收合同

### 6.1 定向测试必须覆盖

1. 非法选择的 diagnosis 与 verifier 保持既有 `COMPARISON_SELECTION_INVALID` 语义；
2. 合同一致而策略、配置、代码、seed 或 metric 数值不同时，内部关系仍全部为 `REFERENCE` / `SAME`，
   verifier 既有成功路径不变；
3. 参数化合同 mismatch 时，diagnosis 与 verifier 返回相同错误码、entry 和 detail 字段集合，且 fail-on-call
   seam 证明不进入 output verifier；
4. 3-run 多字段 mismatch 保持用户选择顺序和 `_comparison_contract` 字段顺序，第一项只为 `REFERENCE`，
   其余项只为 `SAME` / `DIFFERENT`；
5. 合同一致但一个合成 fixture 输出被篡改时，diagnosis 不能冒充完整性证据，verifier 仍精确返回
   `COMPARISON_RUN_UNVERIFIED`；
6. AppTest 证明 only-exact-mismatch 条件渲染、关系表列顺序与 relation-only 内容；output failure 不出现诊断
   面板，也不解锁部分 metric/NAV。

### 6.2 实际执行的验收命令

项目统筹释放 CPU8–11 后，在唯一 Windows venv 中用 BelowNormal/`0xF00` carrier 串行执行：

```text
python -m pytest tests/unit/test_gui_research_runs.py tests/gui/test_streamlit_app.py -q --basetemp artifacts/test_tmp/gui-g1-d1-basetemp -p no:cacheprovider
python -m pytest tests/gui/test_streamlit_app.py -q --basetemp artifacts/test_tmp/gui-g1-d1-basetemp -p no:cacheprovider
ruff check src/quant/gui/research_runs.py src/quant/gui/app.py tests/unit/test_gui_research_runs.py tests/gui/test_streamlit_app.py
mypy src/quant/gui/research_runs.py src/quant/gui/app.py
git diff --check 2a376100a50fb0ad5040048e4ba2aae8c974ace9 -- src/quant/gui/research_runs.py src/quant/gui/app.py tests/unit/test_gui_research_runs.py tests/gui/test_streamlit_app.py docs/gui/GUI_产品与技术设计.md docs/gui/roadmaps/GUI_投研工作台路线图.md docs/gui/agent/GUI_G1_D1_严格比较口径诊断任务与交付记录.md
```

统筹在代码验证前、GUI session 在首次文档回填后均执行 diff-check，无错误，只有 LF→CRLF 提示。pytest 后
已精确删除 basetemp。浏览器验证不属于本包要求且未执行；不能用历史 C4 browser smoke 代替本轮证据。

### 6.3 真实 immutable artifacts probe 与 live-fixture 可用性扫描

Probe A 和 Probe B 的 live-fixture 扫描只能在 CPU 队列释放后，对运维指定的真实 artifact root 做只读
操作；不得写、修补或重新发布 canonical artifact。实际执行时必须把选中的完整 run id、catalog 快照数量、
命令/脚本入口和结果补回本记录。

#### Probe A：真实 3-run 合同 mismatch

从当时 canonical catalog 按 run id 确定顺序选择第一个满足严格 verifier 精确返回
`COMPARISON_CONTRACT_MISMATCH` 的真实 3-run 组合，并断言：

- comparison 为 `BLOCKED`、`integrities=()`，issue entry 为 `comparison`；
- detail mismatch 字段集合与 diagnosis 中至少含一个 `DIFFERENT` 的字段行集合一致；内部 diagnosis 仍
  覆盖全部 14 字段；
- 内部第一项全为 `REFERENCE`，第二、三项只含 `SAME` / `DIFFERENT`，且每个 mismatch 字段行至少有一个
  `DIFFERENT`；
- 投影中不存在任何合同原值、逐 run metric、output evidence 或 NAV；
- 此路径不打开或哈希三个运行的 output。

如果当时真实 catalog 不存在 mismatch 组合，结果必须记为 `BLOCKED_BY_FIXTURE_AVAILABILITY`，不得改造真实
artifact 或用合成 fixture 冒充该 probe。

#### Probe B：真实静态口径一致但 output fail

从同一 catalog 按 run id 确定顺序选择第一个 diagnosis 合同一致、但现有严格 verifier 因至少一个运行的
既存 output 完整性问题返回 `COMPARISON_RUN_UNVERIFIED` 的真实 2-run 组合，并断言：

- diagnosis 覆盖全部 14 字段且仅含 `REFERENCE` / `SAME`，但不产生 `VERIFIED` 声明；
- verifier 保持 `BLOCKED`、`integrities=()` 与原有 underlying output issue detail；
- UI 条件不满足，不显示合同关系诊断，也不显示逐 run metric 或 NAV；
- probe 不篡改、修复、复制或重新发布任何真实 artifact。

如果没有这种既存的真实组合，必须如实记录 `BLOCKED_BY_FIXTURE_AVAILABILITY`；合成 output-tamper 单元测试
只能证明纯逻辑，不能冒充真实 probe，也不得为了制造失败而修改 immutable artifact。

### 6.4 统筹冻结的 Probe B 等价验收

live fixture 不存在后，统筹另行冻结一次 `DERIVED_REAL_BYTES_OUTPUT_FAIL`，以解除无限 fixture 阻塞而不
降低失败语义强度：固定同一真实可比较组内两个 fresh `VERIFIED` run，把 canonical 目录逐文件复制到当前
worktree 的唯一 ignored 临时 artifact root，只在第二个副本的一个 manifest 声明 output 末尾翻转 1 byte，
且保持 `run.json` 原字节。随后必须重新 discover/diagnose/compare 并证明：

- 全部 14 字段仍为 `REFERENCE/SAME`，`contract_compatible=true`；
- verifier 精确返回 `COMPARISON_RUN_UNVERIFIED`，underlying issue 为 output digest mismatch；
- comparison 不暴露部分 integrity，NAV 保持 `BLOCKED/frame=None`，且不具备 mismatch 面板条件；
- canonical 源目录前后逐文件 SHA-256 映射完全相同；
- 临时 artifact root、目标 PID tree 与精确 `0xF00` 占用全部清零。

该反例只能记录为“真实 canonical 字节派生的隔离篡改反例”，不能称为既存坏 run、修复后的 run 或重新发布
产物；29 个真实候选全部 `VERIFIED` 与 live-fixture unavailable 事实必须继续保留。

## 7. 资源与环境执行记录

- 统筹确认 MAX 完全释放且 `0xF00=0` 后，正式把 CPU8–11 转交本任务；所有短任务均为唯一进程树、
  BelowNormal、affinity `0xF00`，Polars/OMP/BLAS 等线程变量均不超过 2。受保护的 Normal/`0xFFF` Tushare
  finance writer 与本槽位按统筹合同共存，GUI 未读取其秘密命令行，也未修改或终止它。
- 唯一 venv 为 `F:\AI_Coding\QuantitativeTrading\artifacts\dev_envs\gui-g1-d1-win-py313`，使用
  `D:\Miniforge3\python.exe -m venv --system-site-packages` 创建；Python `3.13.13`、Streamlit `1.61.1`，
  editable import 精确指向本 worktree，`pip check` 为 `No broken requirements found.`。借用 system site
  packages 不证明独立依赖闭包，也不替代 WSL Gate。
- 首次 venv 子进程 PID 16872 已 exit 0 且环境完整创建，但 PowerShell `DataReceivedEventHandler` 因后台线程
  无 Runspace 报错。确认 PID/F00 零残留后，后续 carrier 改用 .NET `ReadToEndAsync()` 同步取得异步输出和
  真实退出码；没有创建第二个环境或并发重试。
- 第一次 mypy 进程树自然结束，但外层 30 秒 yield 丢失终态输出；确认 `0xF00=0` 后只做一次同命令可观测
  重跑并取得 exit 0。该基础设施证据缺口没有被冒充为首次通过。
- ignored basetemp 固定为 `artifacts/test_tmp/gui-g1-d1-basetemp`。结束时唯一 venv、basetemp、目标 PID tree、
  `0xF00` 进程和 18501 listener 均为 0；未启动 browser 或外部 Agent，也未修改真实 artifact。
- 等价 Probe B 未重建 venv，使用 `D:\Miniforge3\python.exe` base 加当前 worktree `PYTHONPATH`，仅 import
  `quant.gui.research_runs` 纯逻辑；PID 21820 为唯一 BelowNormal/`0xF00` 进程，数值线程变量均为 2，exit 0、
  stderr 0。ignored 临时根
  `artifacts/test_tmp/gui-g1-d1-derived-output-fail` 及其空父目录在进程结束后均已精确删除。

## 8. 验证记录

| 项目 | 当前状态 | 结果/证据 |
| --- | --- | --- |
| 环境与依赖 | PASS | Python `3.13.13`、Streamlit `1.61.1`；editable `[gui]` 指向当前 worktree；`pip check` 无 broken requirements |
| focused unit + GUI pytest | PASS_WITH_SKIP | `24 passed, 1 skipped, 5 warnings in 16.28s`；唯一 skip 是既有 Windows symlink 权限反例，不是 AppTest |
| Streamlit AppTest | PASS | 独立运行 `5 passed, 0 skipped, 5 warnings in 15.10s`；5 条均为 `importlib.metadata` DeprecationWarning，stderr 0 |
| Ruff | PASS | `All checks passed!`，覆盖 4 个批准 Python 路径 |
| mypy | PASS | 可观测重跑 `Success: no issues found in 2 source files`，stderr 0 |
| 真实 Probe A | PASS | catalog 37 runs / 0 issue；真实 3-run mismatch、14 字段关系和 output-verifier-before-hash seam 闭合 |
| 真实 Probe B live fixture | BLOCKED_BY_FIXTURE_AVAILABILITY | 4 个同口径组大小 `23/2/2/2`；29 个候选 run 全部 `VERIFIED`，不存在既存 output failure |
| Probe B 等价派生反例 | PASS | 两个 fresh `VERIFIED` canonical run 的隔离逐文件副本；14 字段全 `REFERENCE/SAME`，翻转 `report.json` 末字节后精确 `COMPARISON_RUN_UNVERIFIED`，无部分 integrity/NAV |
| 浏览器 functional smoke | NOT_RUN_CURRENT_SCOPE | 本包不要求；AppTest 已证明条件渲染，未发现要求扩大到 browser 的 UI 异常 |
| 资源清理 | PASS | env、basetemp、目标 PID tree、`0xF00` 和 18501 listener 均为 0 |

### 8.1 Probe A 真实证据

- artifact root：`F:\AI_Coding\QuantitativeTrading\artifacts`；catalog `37` runs、`0` issue；
- 选择顺序：`0361fa0a0e59964fac0dbc5d926e3ca64524a9c19209b6ec840c6e5e305e7e90`、
  `03e6131b4617291043cb0a05d9c4a09e4558fae7968855ebc76e9bcd4fb4dd0b`、
  `05606a6502cf23f2c3c6cfa69d81147eb2ee8260e99c6e637c7a6ed9741b4015`；
- mismatch 字段为 `data_start`、`data_end`、`universe_name`、`universe_frozen_as_of`、
  `candidate_symbols`、`folds`、`selection_metric`、`aggregate_metric_names`、`inputs`；每行关系均为
  `REFERENCE/SAME/DIFFERENT`；
- comparison 精确返回 `BLOCKED / COMPARISON_CONTRACT_MISMATCH / entry=comparison`，detail 为上述字段名
  排序集合；fail-on-call seam 证明 output verifier 未调用，未投影任何合同原值。

### 8.2 Probe B live fixture 可用性

同一真实 catalog 中按共享合同形成 4 个可比较组，大小分别为 `23/2/2/2`。逐 run 最多校验一次，共检查
29 个候选，全部输出 `VERIFIED`，所以无法构造真实的 `COMPARISON_RUN_UNVERIFIED` 组合。实现已有合成
output-tamper 单元测试和 AppTest，但它们不能冒充既存坏 run；该 live-fixture 结论仍为
`BLOCKED_BY_FIXTURE_AVAILABILITY`，没有因等价验收而改写。

### 8.3 `DERIVED_REAL_BYTES_OUTPUT_FAIL` 等价证据

- source 选择顺序：`36b3dd9172811956d005b5c14e28b22168e19c54fbbcbe642430285a16e52e91`、
  `03e6131b4617291043cb0a05d9c4a09e4558fae7968855ebc76e9bcd4fb4dd0b`；fresh verify 分别检查 4、5 个
  manifest output，均为 `VERIFIED`；
- 临时 artifact root 为 ignored
  `artifacts/test_tmp/gui-g1-d1-derived-output-fail`，副本位于其 canonical
  `research/runs/<run_id>` 结构；逐文件复制前后两份 `run.json` 与源字节一致；
- 仅翻转第二个副本 `report.json` 末尾 1 byte，文件大小与 manifest 声明保持一致；重新 discovery 得到 2
  runs / 0 issue，14 字段全部为 `REFERENCE/SAME` 且 `contract_compatible=true`；
- comparison 精确返回 `BLOCKED / COMPARISON_RUN_UNVERIFIED`，entry 为第二个 source id，detail 保留
  `RUN_OUTPUT_DIGEST_MISMATCH`；`integrities=()`，NAV 为 `BLOCKED/frame=None`，mismatch 面板条件为 false，
  未投影 metric；
- 两个 canonical 源目录前后逐文件 SHA-256 映射完全相等：首个 5 files、第二个 6 files；其中 `run.json`
  SHA-256 分别为 `0da90d7245fcd8d174cb43fa0d47b359957f75da8f22ac58e5731ad05307e3c7`、
  `68ef910447db27b4a082ad1d614992a484dd478cc66715248f25b94075b5e2bf`；
- PID 21820 exit 0、stderr 0；临时 root/父目录、目标 PID 与精确 `0xF00` 占用均为 0。该证据是**真实
  canonical 字节派生的隔离篡改反例**，不是既存坏 run，且没有写入 canonical artifact。

## 9. 安全提交、合流与删除退出条件

### 安全提交

只有全部必要定向验证和两个真实 probe 实际完成、结果如实回填、basetemp/进程/端口无残留，并确认：

```text
git diff --cached --name-only
```

精确等于第 3 节 7 路径集合时，才允许形成 G1-D1 安全提交。真实 Probe B live fixture 仍为
`BLOCKED_BY_FIXTURE_AVAILABILITY`；统筹冻结的等价路径已由一次 `DERIVED_REAL_BYTES_OUTPUT_FAIL` 实际通过，
因此在 cached diff 精确闭合后允许形成安全提交。这不把隔离派生反例写成既存坏 run，也不降低 canonical
artifact 的不可变要求。

### 合流

GUI session 只向项目统筹回报 commit SHA、父提交、exact changed paths、实际验证结果和残余风险。由统筹在
独立 integration 分支做冲突审计与合流；本 session 不写根 writer checkout、不直接合流、不修改中央 SSOT，
也不宣布项目 Gate 完成。

### Worktree 删除

仅当统筹确认 G1-D1 提交已进入目标集成历史、分支无未提交改动、ignored basetemp、Python/GUI 进程、验证
环境和端口均无本包残留、路线图继续保留历史证据与开放债项，并由统筹明确批准退出后，才能删除
`gui-g1-d1-comparison-diagnostics` worktree。未满足任一条件时保持原位，不移动目录、不做根级清理。
