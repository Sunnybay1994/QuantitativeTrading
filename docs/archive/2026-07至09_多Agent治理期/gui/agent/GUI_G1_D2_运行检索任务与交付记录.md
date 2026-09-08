# GUI G1-D2 研究运行检索任务与交付记录

## 1. 状态、价值与拓扑

- 状态：**VALIDATED / READY_FOR_SAFE_COMMIT**。静态实现、独立初验返工闭环、受控 focused 验证和最终
  文档复核均已完成；当前等待 exact 7 安全提交，尚未合流或退休来源线。
- exact base：`ac57ce9e40dc6731e1106b2fa2398f4013fa19da`
- branch：`codex/gui-g1-d2-run-search`
- worktree：
  `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\gui-g1-d2-run-search`
- owner：GUI 经理负责任务书、范围、最终验收与交接；本地 Luna Worker 的隔离 subagent 负责实现。
- 用户可观察结果：研究员在现有“运行总览”中可按 literal 文字与 caveat 是否存在快速缩小历史运行表，
  不再手工翻找完整 run id；默认不交互时仍显示现有全部 canonical runs。

本任务只改善轻量研究运行的查找，不把只读工作台包装成运行平台。GUI 仍不能发起、恢复、取消研究任务，
也不新增因子/策略注册、M3 viewer、PAPER/LIVE 或任何 orchestration 能力。

## 2. 权威上下文与当前行为

- 协作与安全规则：项目根 [`AGENTS.md`](../../../AGENTS.md) 与
  [`项目多 Agent 分层协作与资源治理规范`](../../governance/项目多Agent分层协作与资源治理规范.md)。
- GUI 长期范围与历史状态：[`GUI 投研工作台路线图`](../roadmaps/GUI_投研工作台路线图.md)。
- 产品、可信度和页面边界：[`GUI 产品与技术设计`](../GUI_产品与技术设计.md)。
- 当前总览在 `src/quant/gui/app.py::_render_overview` 中先展示全 catalog 卡片，再按 conclusion 与
  strategy 筛选表格；数据只来自 `discover_research_runs` 返回的 canonical `ResearchRunSummary`。
- `src/quant/gui/research_runs.py` 是 GUI 唯一文件访问层。G1-D2 的纯筛选不得打开文件、验证 output、读取
  NAV 或建立第二份 manifest parser。
- 当前 AppTest 已覆盖默认空态、详情完整性、严格比较、口径 mismatch 和 output failure；G1-D2 只增加
  总览检索合同及其条件交互证据。

## 3. Exact 7 路径白名单

```text
src/quant/gui/research_runs.py
src/quant/gui/app.py
tests/unit/test_gui_research_runs.py
tests/gui/test_streamlit_app.py
docs/gui/GUI_产品与技术设计.md
docs/gui/roadmaps/GUI_投研工作台路线图.md
docs/gui/agent/GUI_G1_D2_运行检索任务与交付记录.md
```

- GUI 经理当前只写本任务书；实现 Agent 最多写前 6 个路径，本任务书对其只读。
- 实现 Agent 以压缩消息返回交付报告；GUI 经理在实现结束后回填本记录并负责最终 exact 7 提交。
- 独立初验 Agent 对 7 路径全部只读，以压缩消息返回“标准—证据—结论”和新增反例，不新增报告文件。
- 禁止修改 `pyproject.toml`、任何 `__init__.py`、launcher、README、项目级路线图、治理文档、研究合同、
  配置、数据、artifact 或其他共享 SSOT。

## 4. 冻结实现合同

### 4.1 唯一纯筛选函数

在 `quant.gui.research_runs` 增加并通过 `__all__` 导出：

```python
def filter_research_runs(
    runs: Sequence[ResearchRunSummary],
    *,
    conclusions: Collection[str],
    strategies: Collection[str],
    query: str = "",
    caveat_presence: Literal["ALL", "PRESENT", "ABSENT"] = "ALL",
) -> tuple[ResearchRunSummary, ...]:
    ...
```

合同如下：

1. 单次按输入 `runs` 顺序遍历并原序返回；不得排序、去重、分组或改变对象身份。
2. conclusion 与 strategy 继续使用 canonical manifest 值的 exact membership；任一选择集合为空时结果为空。
3. query 只做 `strip().casefold()` 后的 literal substring 匹配，不使用 regex、tokenizer、模糊匹配、别名、
   相似度或分词。
4. 可搜索文本仅为：`run_id`、`hypothesis_id`、`strategy_name`、`strategy_version`，以及
   `f"{strategy_name} {strategy_version}"`。不得搜索 hypothesis 正文、caveat 内容、路径、digest、metric、
   input/output 或 NAV。
5. 空白 query 在其他筛选条件通过时匹配全部。
6. `PRESENT` 只表示 `manifest.caveats` 非空；`ABSENT` 只表示为空；`ALL` 不按 caveat 过滤。不得解释
   caveat 内容、严重度或研究结论。
7. 非法 `caveat_presence` 必须立即抛出 `ValueError`，不得静默回退。
8. 函数只消费已重建的 dataclass；不得访问 `run_root`、打开/枚举/hash 文件，调用 output verifier、加载
   NAV、读取报告、重新解析 `run.json` 或缓存结果。

若现有类型、dataclass 或 UI 事实使该合同无法最小实现，Agent 必须 STOP 并回报证据，不得改签名或新增
适配器、配置、索引、数据库。

### 4.2 “运行总览”交互

- 保留现有 conclusion 与 strategy sidebar multiselect 的标签、默认值和语义。
- 在 sidebar 增加一个 `搜索运行` text input，`max_chars=128`；默认空字符串。
- 增加一个 `Caveat` 单选控件，机器值严格为 `ALL / PRESENT / ABSENT`，用户标签分别为
  `全部 / 仅有 caveat / 仅无 caveat`；默认 `ALL`。
- `_render_overview` 只调用上述纯函数，不复制第二份筛选逻辑。
- 顶部 6 张卡片继续统计完整 canonical catalog，不能随筛选改变。运行表上方显示明确的
  `当前显示 X / Y 个运行；顶部卡片统计全部 canonical runs。`，避免把全局卡片误读为筛选结果。
- 默认 query 为空、caveat 为 `ALL` 时，表格行、列和 catalog 顺序必须与当前版本完全一致。
- 无匹配时继续使用清晰 empty state；筛选变化不得影响详情页、比较页或已有 page navigation。
- 不使用 `st.session_state`、cache、query parameter、上传、任意路径、下载或隐藏状态。

### 4.3 失败语义与安全边界

- catalog issue、manifest identity、输出完整性、NAV 和严格比较的既有错误码与顺序全部不变。
- 筛选不产生新的业务状态，不得把“匹配/无匹配”解释为优先级、质量、准入或研究结论。
- 总览筛选期间不得出现 spinner、hash、output/NAV 校验或长任务；任何这样的调用均视为合同破坏。
- 不读取 `data/`、真实凭据、外部网络或不可变 artifact 内容；AppTest 只使用临时 fixture。
- 不新增依赖、兼容 helper、缓存/索引、后台任务或性能抽象。真实瓶颈出现前不优化。

## 5. 成功标准

- [ ] 纯函数严格满足第 4.1 节，并保持输入对象与顺序。
- [ ] 默认总览与当前可观察行为兼容；新增控件少而明确，筛选计数口径可见。
- [ ] literal search 分别命中 run id prefix、hypothesis id、strategy name、version 和 name+version；大小写
  不敏感，空白 query 等价于空 query。
- [ ] caveat `ALL/PRESENT/ABSENT` 与 conclusion、strategy、query 可组合，空结果明确。
- [ ] 单元测试和 AppTest 使用 fail-on-call seam 证明筛选不触发 output verifier、comparison verifier、
  NAV projection 或文件读取。
- [ ] 现有详情、比较、D1 关系诊断合同不变；无新增依赖或 shared SSOT 修改。
- [ ] 最终 tracked/untracked/cached 集合精确为第 3 节 7 路径，无临时产物。

## 6. 测试与关键反例

### 6.1 纯逻辑测试

至少覆盖：

1. 默认全部选择 + 空/纯空白 query + `ALL` 返回原 tuple 等值、原序、同对象；
2. case-insensitive literal 分别命中每个允许字段及组合的 `strategy_name strategy_version`；
3. query 不匹配 hypothesis 正文、caveat 文本、config path、digest 或 metric；
4. `PRESENT` 与 `ABSENT` 精确区分 caveat tuple 是否为空，`ALL` 保持两者；
5. conclusion、strategy、query、caveat 四类条件联合取交集；空选择与无匹配返回空 tuple；
6. 非法 caveat mode 抛 `ValueError`；
7. fail-on-call / fail-on-file-access seam 证明函数没有 output、NAV 或文件 IO。

### 6.2 Streamlit AppTest

至少覆盖：

1. 默认控件值保持全部 rows，顶部卡片仍是全 catalog，计数说明可见；
2. literal search 和 caveat 三态产生预期表格行且保持 catalog 顺序；
3. 组合筛选无匹配时显示 empty state，无 exception；
4. 在 verifier/NAV 入口被替换为 fail-on-call 的情况下，反复修改总览筛选仍无调用；
5. 现有 5 条 AppTest 继续通过。AppTest 必须实际执行、不得以缺 Streamlit 的 skip 冒充通过；若当前环境
   无依赖，STOP 并向根 Agent 申请受控反馈环境，不自行安装或重建环境。

### 6.3 冻结命令

获得根 Agent 串行 Python 槽后，使用唯一实例、BelowNormal、affinity `0xF00`、数值线程不超过 2，依次运行：

```text
python -m pytest tests/unit/test_gui_research_runs.py tests/gui/test_streamlit_app.py -q --basetemp artifacts/test_tmp/gui-g1-d2-basetemp -p no:cacheprovider
ruff check src/quant/gui/research_runs.py src/quant/gui/app.py tests/unit/test_gui_research_runs.py tests/gui/test_streamlit_app.py
mypy src/quant/gui/research_runs.py src/quant/gui/app.py
git diff --check -- src/quant/gui/research_runs.py src/quant/gui/app.py tests/unit/test_gui_research_runs.py tests/gui/test_streamlit_app.py docs/gui/GUI_产品与技术设计.md docs/gui/roadmaps/GUI_投研工作台路线图.md docs/gui/agent/GUI_G1_D2_运行检索任务与交付记录.md
```

- 无依赖、renderer、图表或启动路径变化，本包不重复 browser smoke。
- 不运行全量 pytest、真实 artifact probe、WSL Gate、网络或性能测试。
- basetemp 必须位于本 worktree ignored `artifacts/` 下；结束后精确清理。不得使用用户 TEMP。

## 7. Agent 职责与执行顺序

1. GUI 经理冻结本任务书，不写生产实现。
2. 只有收到根 Agent 明确的 Luna 通道恢复/启动通知后，才向本地 Luna Worker 下发任务；Worker 必须为本
   任务开启新的隔离 subagent。当前不得向异常中的 Luna 追加消息或创建第二实现者。
3. 实现 subagent 只写第 3 节前 6 路径，先静态实现并返回压缩交付报告；未获 Python 槽时不得测试。
4. 根 Agent 下发串行资源窗口后，执行 Agent 才按第 6.3 节运行检查并清理精确临时目录。
5. 另一未参与实现的新外部 Agent/独立上下文对 7 路径只读初验，新增至少一个实现者未使用的反例；不写
   生产、测试或新报告文件。
6. 初验不通过时，GUI 经理按“现象—根因—规则—最小复现—新增测试—通过条件”形成返工，回原实现
   Agent；返工后由独立初验 Agent 复验。
7. GUI 经理完成最终合同、范围、文档和 cached exact 7 验收，再形成安全提交；不自行合入 integration。

## 8. STOP、回滚与交付

以下任一情况立即停止扩大实现并回报：

- 需要第 3 节之外的文件、依赖、配置、公共接口或 shared SSOT；
- 需要 import 私有 parser、M2 `run_*`、M3、worker、数据库、队列或 orchestration；
- current code 无法保持既有 filter/default/order/error 语义；
- AppTest 无法实际运行，或筛选触发 output/NAV/文件读取；
- 发现与 frozen base 不一致的其他未提交改动、Luna 双实例或资源槽冲突。

实现未提交前可用精确 patch 反向恢复本包文件；禁止 `git reset --hard`、覆盖其他任务改动或清理 broad
目录。最终交付只回报：source SHA、parent/base、exact 7 paths、实际命令/结果、未验证项和资源残留。

## 9. 交付与验收记录（待回填）

### 实现 Agent

- 状态：`DELIVERED`。
- Worker / 隔离 subagent：Luna Worker 路由的唯一实现者
  `01a02f39-2b92-7910-8508-9c02aac9e267`。该实现者在新版 Dispatcher 协议前已经启动；根 Agent 通过
  `ROOT_ADOPTED_ACK` 验真 task、agent、base、branch、worktree 与唯一写者身份后，仅对本历史现场接受
  best-effort 消息通道。该例外不适用于新任务。
- 修改：新增 `filter_research_runs` 及总览 query/caveat 控件，补充纯逻辑、AppTest 和两份 GUI 文档；始终
  限于批准的前 6 路径，本文档由 GUI 经理持有且实现者未修改。
- 静态返工：GUI 经理首轮核对要求修正 active topology、补空 strategy 与默认控件断言；独立初验随后发现
  默认顺序测试错误地使用排序后的 run id，并增加“非法 caveat + 双空选择”、重复同对象输入和显式读取
  seam 反例。原实现者按最小范围返工，未改公共合同或扩大文件集合。
- 验证：受控 Windows 反馈环使用 Python `3.13.13`、Streamlit `1.62.0`；`pip check` 通过，
  `quant.gui` 精确来自本 worktree。combined focused pytest 为 `35 passed, 1 skipped`，唯一 skip 是 Windows
  无法创建 symlink 的既有平台反例；随后 AppTest-only 等价验收为 `9 passed, 0 skipped`。Ruff 四路径通过，
  mypy 两个生产文件通过，exact 7 `git diff --check` 通过。
- 证据边界：首轮安装 carrier 的最终 payload 丢失后未盲重试；后续环境 postcondition 通过且恢复轮安装
  exit 0。首次 mypy carrier 证据不可恢复后，根 Agent 只批准一次 Windows base 的可观察最窄恢复并取得
  exit 0。未运行 browser、cold import、真实 artifacts、全量 pytest 或 WSL Gate。
- 清理：受控 env、basetemp、本任务临时父目录、目标 PID tree 与 `0xF00` 占用均已清零；未触碰
  `artifacts/test_tmp` 下其他任务目录。

### 独立初验

- 状态：`REVIEW_PASS`。
- 独立 reviewer：`01a03198-bc81-70c1-8c5c-6793d6988dbe`，与实现者不同，exact 7 全部只读且未运行
  Python。新任务 mapping 的 schema metadata 曾有一次 SHA 抄写错误；根 Agent 采用 append-only correction
  绑定原 mapping、错误 metadata 与 `correction_final=true` 后恢复采信，未覆盖原审计文件或创建第二 reviewer。
- 首验：`REVIEW_FAIL`，指出默认顺序 oracle、文件读取 seam 与新增对抗性反例覆盖不足；任务书尚未回填属于
  GUI 经理职责，不要求实现者越权修改。
- 复验：上述返工全部闭合，结论为 `REVIEW_PASS / severity NONE`。reviewer 新增的未落测试反例是
  `query="fixture.*"` 必须按 literal 非匹配处理；实现使用 `in` substring，静态满足该反例。剩余风险只包括
  当时尚未运行的 Python 检查，现已由后续受控验证关闭。

### GUI 经理最终验收

- 状态：`READY_FOR_SAFE_COMMIT`。
- 合同：纯函数字段白名单、casefold literal、caveat 三态、非法模式优先失败、原序/重复对象 identity、
  空选择、无新增 IO/verifier/NAV/hash，以及总览默认/KPI/空态语义均已由代码、测试和独立复验闭合。
- 范围：当前 worktree 为批准 branch/base，6 个 tracked 修改 + 本任务书 1 个 untracked，cached 为 0，
  白名单外 dirty 为 0。
- 最终文档复核：同一独立 reviewer 对 exact 7、两份 GUI 文档、本文记录、尾随空白与本地相对链接只读
  复核，结论为 `FINAL_DOC_REVIEW_PASS`；未发现范围或证据表述问题，未重复运行 Python。
- 待完成：精确缓存 exact 7、形成 source 安全提交并向根 Agent 申请合流。integration 回归、archive tag、
  worktree/branch 退休均由根 Agent 后续执行，当前不得写成完成。
