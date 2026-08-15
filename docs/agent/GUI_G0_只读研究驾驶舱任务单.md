# GUI G0 只读研究驾驶舱任务单

## 目标与价值

- 用户可观察结果：研究员可在一个只读页面浏览轻量研究运行，识别结论、关键指标、时间语义、caveat、
  清单异常和输出完整性，并在验证通过后查看 NAV。
- 要解决的问题 / 价值：减少研究员手工找目录、开 JSON、核哈希和拼图表的操作成本，同时不建立第二套
  研究或交易逻辑。
- 明确非目标：不运行研究、不写产物、不扫描 `data/`、不提供 PAPER/LIVE 或任意代码执行能力。

## 现状与权威上下文

- 当前行为：轻量研究由 `quant.research.lightweight_run` 以 no-clobber 方式发布
  `artifacts/research/runs/<run_id>/run.json` 与输出文件，尚无公共 catalog/GUI reader。
- 相关代码与测试：`src/quant/research/lightweight_run.py`、
  `tests/unit/test_lightweight_research_run.py`。
- 适用 SSOT / 项目规则：[`AGENTS.md`](../../AGENTS.md)、
  [`项目实施路线图.md`](../../项目实施路线图.md)、
  [`GUI 投研工作台路线图`](../roadmaps/GUI_投研工作台路线图.md)。

## 成功标准

- [ ] catalog 只读取固定 runs 根目录的直接子目录，返回已验证摘要和结构化问题，不因单个坏条目崩溃。
- [ ] 清单校验覆盖规范 JSON、完整 V1 合同、目录身份与内容身份；不复制或弱化原发布合同。
- [ ] 输出完整性覆盖无链接/重解析点、精确文件集合、字节数和 SHA-256；失败时拒绝 NAV。
- [ ] NAV 投影仅接受 `test_nav.parquet` 的必要列、类型、有限正数和 1.0 成本路径，不重算结论或指标。
- [ ] 默认 UI summary-first、空态/异常态可见，并持续显示只读与无 PAPER/LIVE 权限边界。
- [ ] 缺少 Streamlit 时启动器稳定失败且无安装、写入或后台进程副作用。
- [ ] 改动严格限制在统筹批准的独占新文件白名单。

## 事实、假设与未决问题

- 已确认事实：清单身份为
  `sha256(canonical_json(["lightweight-research-run-id-v1", manifest_without_run_id]))`；发布目录不可覆盖。
- 低影响假设：G0 的“时间排序”使用清单 `data_end`、`hypothesis_id`、`run_id`，不把目录 mtime 解释为
  创建时间。
- 必须确认的高影响问题：Streamlit optional group 已获准写入依赖 SSOT；具体解释器、安装命令和资源窗口仍
  需统筹确认，不得修改 WSL `base`。
- 方案权衡：首包复用 Streamlit 原生 metric/table/line chart，不引入 Plotly；真实交互复杂度证明需要后再增加
  依赖。

## 范围与约束

- 可写文件白名单：见
  [`GUI 投研工作台路线图：文件与文档所有权`](../roadmaps/GUI_投研工作台路线图.md#文件与文档所有权)。
- 只读或禁止路径：根工作树、`data/`、既有 artifacts、核心研究/交易代码、所有共享 SSOT。
- 允许的接口、依赖、配置或数据变更：仅新增 `quant.gui` 包、聚焦测试和 GUI session 文档；当前不变更
  依赖、配置或 Schema。
- 禁止事项：跟随链接、任意路径输入、任意 SQL/shell/import、产物修复、缓存作为权威、长任务、交易动作。
- 模块边界：不得 import 任一 M2 `run_*` 私有 helper，不复制策略、回测或准入逻辑；发起运行留待另行冻结
  公共服务接口。
- 阶段约束：不新增队列、数据库、权限框架或运行编排抽象；公共 orchestration 边界关闭前，GUI 不得获准
  发起运行。性能优化只有在真实 manifest 规模产生可复现瓶颈并完成测量后才能进入任务。

## 冻结接口与失败语义

- `discover_research_runs(artifact_root)`：返回 `ResearchRunCatalog`；runs 根缺失是可展示问题，不抛异常。
- `verify_research_run(run)`：返回 `ResearchRunIntegrity`；失败为稳定 `BLOCKED` 状态和问题码，不读取 NAV。
- 同步完整性校验总量固定上限 128 MiB；超过即 `RUN_OUTPUT_INVALID`，不把无界哈希放入 Streamlit rerun。
- `load_nav_projection(integrity)`：只接受完整性 `VERIFIED`，否则 fail-closed。
- catalog 问题码：`RUNS_ROOT_MISSING`、`RUNS_ROOT_UNSAFE`、`RUN_ENTRY_UNSAFE`、
  `RUN_MANIFEST_INVALID`、`RUN_MANIFEST_NONCANONICAL`、`RUN_ID_MISMATCH`。
- 完整性问题码：`RUN_OUTPUT_INVALID`、`RUN_TREE_MISMATCH`、`RUN_OUTPUT_DIGEST_MISMATCH`。
- NAV 问题码：`NAV_NOT_AVAILABLE`、`NAV_SCHEMA_INVALID`。
- UI 只把通过原 V1 dataclass 重建并通过身份检查的清单称为“清单自洽”；只有精确输出验证通过才称为
  “输出完整性已验证”。二者均不等于 formal 或 PAPER 准入。

## 轻量计划

1. 冻结产品、数据、失败与安全合同 -> 验证：文档路径、白名单和项目 SSOT 一致。
2. 实现 catalog / integrity / NAV 投影 -> 验证：聚焦单元测试覆盖正常与对抗性路径。
3. 实现启动器和薄 Streamlit UI -> 验证：无依赖失败测试、AppTest 条件测试和静态检查。
4. 形成交付记录 -> 验证：Git 范围、命令结果、未验证项与依赖阻塞如实登记。

## 验证与反例

- 聚焦测试：`python -m pytest tests/unit/test_gui_research_runs.py tests/unit/test_gui_launcher.py -q`。
- UI 条件测试：`python -m pytest tests/gui/test_streamlit_app.py -q`；依赖缺失时只能记为跳过/阻塞。
- 静态检查：仅对 `src/quant/gui` 与对应三份测试运行 Ruff/mypy。
- 完整 Gate：本任务不运行全量测试；不宣称项目 Gate 通过。
- 关键反例：运行目录或任一输出中存在 symlink/junction/reparse point；即使目标文件哈希正确，也必须标记
  `BLOCKED`，不得展示 NAV。
- 关键反例：攻击者修改 `run.json` 后重新格式化或保留旧目录名；必须作为非规范清单或身份不匹配展示。
- 关键反例：额外文件、缺少文件、size/hash 漂移、NAV 非有限/非正值；全部 fail-closed。

## 安全、停止和回滚

- 外部状态 / 不可逆风险：无；G0 只读。不得安装依赖、启动常驻服务或修改既有产物。
- 人工开关：共享依赖、根级文档和跨分支合流均保持统筹锁定。
- 停止并升级条件：原 V1 合同与真实产物冲突、需要修改共享 SSOT、需要新增依赖或需要交易写操作。
- 回滚 / 故障处置：所有变更位于独立分支/独占新文件，可删除分支或单独撤销 GUI 提交；不影响根工作树。

## 交付要求

- 交付报告：`docs/agent/GUI_G0_只读研究驾驶舱交付记录.md`。
- 需要独立审查：否。当前外部 Agent 暂停；按项目规则由主 Agent 串行实现并做正常聚焦开发检查，不用内部
  subagent 模拟独立实现/初验。
