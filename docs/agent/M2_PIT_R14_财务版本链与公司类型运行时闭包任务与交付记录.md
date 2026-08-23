# M2 PIT R14 财务版本链与公司类型运行时闭包任务与交付记录

日期：2026-08-23
owner：策略开发 session
状态：实现与定向开发检查完成，等待统筹合流
晋级边界：本包只关闭 `M2-EVAL-STOP-001` 的 PIT version/comp-type runtime 项；不启动真实 PIT，
不改变任何历史 immutable run 的结论。

## 1. 冻结现场与范围

- exact base：`8ebb9bdf85adf1fae0fe1a6732250540e4a661b8`；
- branch：`codex/m2-pit-r14-version-chain`；
- worktree：`artifacts/dev_worktrees/m2-pit-r14-version-chain`；
- 允许写入的 exact 7 路径：
  1. `src/quant/data/financial_pit.py`；
  2. `src/quant/research/pit_quality_research.py`；
  3. `tests/unit/test_financial_pit.py`；
  4. `tests/unit/test_pit_quality_research.py`；
  5. `docs/research/M2_PIT财务质量因子首批假设卡.md`；
  6. 本记录；
  7. `docs/roadmaps/M2_策略与因子库并行建设路线图.md` 的本包状态 exact hunk。

未修改 config、runner、Schema、publisher、repository、facade、`__init__.py` 或 shared SSOT；未读取
partial raw/ledger，未扰动财务 writer，未运行真实数据或全量测试。

## 2. 冻结合同

1. 利润表与现金流量表必须先过滤 frozen `report_type` 与 `comp_type == 1`，再做 latest selection；
2. 每个证券/报告类型从信号时点可知的最新报告期开始，向前解析五个连续季度节点；
3. 锚点严格要求 `available_date < as_of`；前驱节点只能选择
   `available_date <= successor.available_date` 的最新无歧义版本；
4. 一季度累计值直接等于一季度单季值，无需前季累计相减；其它季度仍依赖其精确前季累计节点；
5. 后发的前季修订不能改写已经发布的后继累计报告；链缺失、同日经济冲突或日期链不闭合时
   fail-closed，不能退回更早 endpoint，也不能以第 K+1 个版本替补；
6. 资产负债表为存量口径，不做累计相减，但同样在 latest 前过滤 frozen `report_type` 与
   `comp_type == 1`；
7. `LATEST_REVISION_CONFLICT` 保留为锚点冲突兼容证据；前驱冲突使用
   `REVISION_CHAIN_CONFLICT`，研究 eligibility 将依赖该链的因子标为 `QUARANTINED`；纯断链标为
   `MISSING_CHAIN`。

## 3. 实现结果

- 新增 PIT-quality 专用数据选择入口，通用 `select_financial_revisions_as_of` 的签名和既有调用保持不变；
- 对 raw 字符串日期和 clean `Date` 日期统一建立内部季度坐标；最新非季度 endpoint 不会被静默跳过；
- 流量表以向量化的季度请求/cutoff 链选择五个节点，输入行顺序不影响结果；
- 冲突节点只保留 canonical quarantine 证据，不产生经济值，但其公共 cutoff 仍允许继续识别其余绑定节点，
  以维持“只隔离依赖该数据集的因子”而不制造旧 endpoint 回退；
- 研究层在构造 factor diagnostics 前已经拿到过滤后的版本链，不再在因子计算后补做 report-type 过滤。

## 4. 反例与返工记录

### 4.1 首轮：raw 日期与冲突隔离

- 现象：首轮 focused 为 `18 passed, 5 failed`；四个 direct selector 反例被统一错误码拒绝，现金表锚点
  冲突还使两个仅依赖利润/资产的因子变成 `MISSING_CHAIN`；
- 根因：链坐标直接对 raw 字符串 `end_date` 使用日期运算；冲突深度又被当成整组不存在，丢失了其余已绑定
  节点，破坏现有按数据集隔离的 eligibility 语义；
- 应遵循规则：raw/clean 双合同必须显式归一到内部日期；冲突值不可入选，但不能让无关因子失去可计算输入；
- 最小复现：raw 六季度链；现金最新期同日两个不同经济值；
- 修正：统一 `_period_end`；冲突深度以公共 cutoff 继续链解析、但不选择冲突经济值；只有五个深度均解析后
  才保留链内其它节点；
- 通过条件：前季后发修订不改变结果，冲突链无替补，现金冲突只隔离现金依赖因子。

### 4.2 第二轮：canonical 冲突证据与兼容名称

- 现象：失败反例复跑先为 `4 passed, 1 failed`，原因是研究投影把两条冲突经济行 canonical 去重成一条；
  完整 focused 随后为 `23 passed, 1 failed`，原因是锚点冲突名称从既有
  `LATEST_REVISION_CONFLICT` 漂移为新名称；
- 根因：测试误把 data 层的两条经济版本行数等同于 research 层 canonical 证据行数；实现又未区分锚点与
  前驱冲突；
- 应遵循规则：研究 quarantine 投影按业务身份去重；既有锚点冲突合同保持兼容，新名称只描述前驱链冲突；
- 新增测试：分别锁定锚点 `LATEST_REVISION_CONFLICT` 与前驱 `REVISION_CHAIN_CONFLICT`；
- 通过条件：两种冲突均 fail-closed，旧证据字段不漂移，前驱冲突不得回退。

## 5. 开发检查证据

| 检查 | 结果 |
| --- | --- |
| focused `test_financial_pit.py + test_pit_quality_research.py` | `24 passed in 3.92s` |
| Ruff：2 个生产文件 + 2 个测试文件 | `All checks passed!` |
| mypy：2 个生产文件 | `Success: no issues found in 2 source files` |
| cold import：`quant.data.financial_pit`、`quant.research.pit_quality_research` | PASS，两个 `__file__` 均精确来自 R14 worktree |
| 范围、cached diff 与 whitespace | PASS，exact 7 路径，`git diff --check` 无错误 |

所有 Python 检查均要求唯一实例、BelowNormal、affinity `0xF00`、数值线程不超过 2；测试临时目录在提交前
精确清理。Windows 定向反馈不表述为 WSL Gate。

## 6. 未关闭项与交接

- C 对称 redundancy coverage、20 日分组单调门禁、singleton report type、固定方向与 trial registry 留给 R3；
- writer terminal、plan-bound bytes/dimension、audit-v4、financial snapshot 和唯一真实 PIT run 均未执行；
- 统筹应先执行 merge-tree/no-ff 合流，再 archive-first 退休本来源线；本 session 不自行合流或删除 worktree。
