# M2 PIT R1 首跑前置闭包任务与交付记录

状态：实现与正常开发检查完成；待统筹合流；禁止发布财务 snapshot 或启动真实 PIT 试验

## 1. 目标与位置

本包只关闭首个 PIT 财务质量因子试验之前的四个 fail-closed 缺口：

1. 财务 raw 审计与 clean publisher 必须绑定现有 planner 产生的冻结 plan-report，不能把“ledger 当前已有的行全部完成”误当成“计划集合完整完成”；
2. PIT 因子有效覆盖率必须参与最终研究结论；
3. `run.json` 的代码身份必须覆盖所有实际影响 snapshot 与 PIT 结果的生产文件；
4. 真实 `report_type` 分布尚未审计时，版本化配置保持 `UNFROZEN` 与空集合，runner 必须在任何 artifact 目录创建前停止。

本包不新增因子、不改变公式或方向、不读取未完成 raw、不发布 clean snapshot、不执行真实回测，也不产生
`PAPER_CANDIDATE`。最高后续结论仍是 `RESEARCH_ONLY`。

- base：`c2c88418f4e4d2a5d195775cc3eb25d181a1e7c4`
- branch：`codex/m2-pit-first-run-prereq`
- worktree：`artifacts/dev_worktrees/m2-pit-first-run-prereq`
- owner：策略开发 session

## 2. 权威来源

- planner：`src/quant/data/tushare_bulk.py`
- deterministic request identity 与 ledger：`src/quant/data/tushare_bulk_ingest.py`
- 财务 raw 审计：`src/quant/data/audit_tushare_financials.py`
- 财务 snapshot 发布：`src/quant/data/publish_tushare_financials.py`
- PIT runner 与研究构造：`src/quant/research/run_pit_quality_factors.py`、
  `src/quant/research/pit_quality_research.py`
- 研究阈值与允许口径：`configs/research/m2_pit_quality_factors.toml`
- 研究语义：`docs/research/M2_PIT财务质量因子首批假设卡.md`

不得在本报告复制 Schema 字段、研究公式或长期阈值 SSOT。

## 3. 冻结契约

### 3.1 plan-report 闭包

`audit_tushare_financials` 与 `publish_tushare_financial_snapshot` 的 public API 必须显式接收
`plan_report_path` 与 `catalog_path`。审计每次调用都 fresh 读取两者、当前 canonical clean instrument 与只读
ledger，并验证：

- plan-report 是 canonical JSON、schema 精确、文件名摘要前缀与内容一致；
- catalog 由现有 public loader 读取，版本与 SHA-256 与 plan-report 精确相等；
- plan 中四个 endpoint 唯一、ACCESSIBLE、无 blocker、`api_name == dataset`，每个
  `estimated_requests` 为正整数；
- provenance 模型显式记为 `RECONSTRUCTED_CURRENT_INVENTORY_V1`：以 plan `as_of`、catalog 和当前
  clean instrument 重构 request 集合；不得宣称恢复或证明 2026-08-15 planner 当时读取的原始成员字节；
- 当前 instrument 的 relative file set、size、物理 SHA-256 与股票成员逻辑摘要在审计前后稳定；拒绝
  link/reparse/alias；真实批次股票数必须为 5,537，且与 plan-report 库存和每 endpoint 预计数一致；
- 复用现有 catalog/chunk/request-id 纯逻辑重构四表 request 集合；ledger 中 catalog、endpoint、参数与
  deterministic `request_id` 必须和重构集合精确一致；
- 每个 endpoint 的 ledger 行数精确等于 plan，零 missing、duplicate、extra、incomplete、
  `FAILED`、`SPLIT_REQUIRED`，且没有 active lease；
- snapshot 只投影该重构集合；plan 内容 SHA、catalog SHA/version、permission-report SHA、计划
  `as_of`、当前 instrument 物理/逻辑摘要、重构 request-set 摘要、显式来源局限与各 endpoint 计数写入
  审计和 snapshot manifest，并参与 snapshot/source identity；
- 发布前后重新执行完整 plan-bound byte audit，结果逐字段一致。

禁止靠人工计数、调用者自报 digest、当前 ledger 行数非零或“所有已有行已完成”替代上述闭包。
现有 plan-report 只有 inventory count，不含当时 inventory/request-set digest；这是明确保留的来源局限，
不能在报告中包装成旧计划原生拥有的身份。下一次启动任何新的 bulk plan/writer 前，planner 必须原生持久化
inventory 与 request-set digest；该债登记到 M2 roadmap，本包不修改或重启当前 planner/ingest/writer。

### 3.2 PIT coverage gate

有效覆盖率以独立预注册的 `signal_dates × factor` 完整网格为分母；缺失日期补零，不允许把实际有信号的日期
反推为预注册日，也不允许顺延。每个预注册信号日每个因子的有效证券数必须至少
`minimum_signal_symbols = 100`，每个因子的日期覆盖率中位数必须至少
`minimum_median_signal_coverage = 0.80`。`0.799...` 拒绝，`0.80` 通过。任一门禁失败时该因子
`research_status = REJECTED`，并最终影响 run conclusion。

### 3.3 code identity

`_CODE_PATHS` 必须纳入所有实际影响三份 snapshot 验真/投影与 PIT 结果的既有生产文件，至少包括 bulk、
daily-basic、financial audit/publisher/repository/clean/PIT、因子、标签、评估、runner 与发布边界。
只扩展路径集合，不复制这些模块的实现。

### 3.4 report_type 停止条件

配置新增显式冻结状态和允许 tuple/list。当前必须是 `UNFROZEN` 与空集合；runner 在读取 snapshot、raw、
创建 artifact 目录或执行因子计算前稳定拒绝。研究函数不再硬编码 `"1"`，只接受 runner 传入的已冻结、
非空、唯一、canonical string tuple。

只有财务 writer 自然终态、plan-bound byte audit READY 后，另一次只读分布审计才可决定允许集合；不得在
本包猜测 `1`，也不得从未来研究结果反向修改口径。

## 4. 稳定失败与反例

- 错 plan schema、非 canonical JSON、路径/文件名 digest 漂移、catalog/plan 混配：审计稳定拒绝；
- 少一条计划 request、同数量换入非计划 request、重复参数、错误 endpoint、篡改 request ID：不得 READY；
- 任一 PENDING/RUNNING/RETRYABLE/FAILED/SPLIT_REQUIRED 或 active lease：不得 READY/发布；
- plan-bound 审计后 ledger、plan、catalog 或 raw 发生变化：发布前后对照失败且无最终 snapshot；
- coverage 79.9%、缺一预注册日期、任一日少于 100、target 日期顺延：对应因子 REJECTED；
- coverage 恰 80% 且每日均至少 100：只通过 coverage 门禁，不能绕过其余统计/冗余/成本门禁；
- `report_type_state = UNFROZEN`、空集合、重复/乱序/未知值：在 artifact 目录创建前拒绝；
- caller row order、ledger row order、plan dataset row order不改变 canonical 结果；重复 dataset 拒绝。

## 5. 精确白名单

1. `src/quant/data/audit_tushare_financials.py`
2. `src/quant/data/publish_tushare_financials.py`
3. `src/quant/research/run_pit_quality_factors.py`
4. `src/quant/research/pit_quality_research.py`
5. `configs/research/m2_pit_quality_factors.toml`
6. `tests/unit/test_audit_tushare_financials.py`
7. `tests/unit/test_publish_tushare_financials.py`
8. `tests/unit/test_run_pit_quality_factors.py`
9. `tests/unit/test_pit_quality_research.py`
10. `docs/research/M2_PIT财务质量因子首批假设卡.md`
11. `docs/research/roadmaps/M2_策略与因子库并行建设路线图.md` 的本包 exact hunk
12. 本文件

禁止修改任何 `__init__.py`、Schema、repository、bulk planner、README、`pyproject.toml`、共享发布器或项目级
SSOT；禁止新增 runner、publisher、依赖或跨 runner helper。

## 6. 验证与运行边界

本包当前已获 CPU8–11 串行资源槽，FWD 在统筹队列中等待。按唯一实例、BelowNormal、affinity `0xF00`、
数值线程不超过 2 的顺序执行：

1. 财务 audit/publisher focused tests；
2. PIT research/runner focused tests；
3. 定向 Ruff、mypy、py_compile 与 TOML 解析；
4. scoped diff/check。

本包无论测试是否绿色都不读取 partial raw、不发布 snapshot、不启动真实 PIT run。真实分布审计、口径冻结、
snapshot 发布与唯一 RESEARCH_ONLY 试验属于后续自然节点。

## 7. 交付记录

本包在 12 路径白名单内完成：

- 财务 audit/publisher 改为显式 plan/catalog 输入，采用
  `RECONSTRUCTED_CURRENT_INVENTORY_V1`，绑定当前 instrument 物理/逻辑摘要、重构 request set、ledger
  精确集合、active lease 与发布前后稳定性；snapshot manifest 同步携带来源模型、局限和闭包身份；
- PIT runner 将完整预注册信号日历的逐日 100 证券与 80% 中位 coverage 直接接入结论；
- `report_type` 从研究函数硬编码改为版本化允许集合；当前配置保持 `UNFROZEN`/空集合并在 snapshot 读取和
  artifact 创建前拒绝；
- PIT code identity 补入实际参与财务 snapshot 与 request 重构的生产模块。

正常开发检查（Windows Miniforge，唯一实例、BelowNormal、affinity `0xF00`、数值线程不超过 2）：

- focused pytest：首轮发现并修正 `allowed_report_types` 私有透传遗漏；最终 `32 passed`；
- 定向 Ruff：PASS；
- 定向 mypy：`Success: no issues found in 4 source files`；
- 四个生产文件 `py_compile`：PASS；
- cold import + TOML 解析：`M2_PIT_R1_COLD_TOML_PASS`；
- scoped `git diff --check`：PASS（仅 Windows LF/CRLF 提示）。

未读取 partial raw、未发布 financial snapshot、未启动真实 PIT、未启动或重启 writer。真实批次 5,537 股票、
每 endpoint 44,296 请求、`report_type/comp_type` 分布以及最终 READY 仍须在 writer 自然终态后用本闭包只读
确认；在此之前配置保持 fail-closed。本记录不把当前 inventory 重构描述为 planner-time 原始成员证明。

安全提交 SHA 与 integration merge-tree 由提交后状态及统筹记录绑定，避免在提交内容中制造自引用摘要。
