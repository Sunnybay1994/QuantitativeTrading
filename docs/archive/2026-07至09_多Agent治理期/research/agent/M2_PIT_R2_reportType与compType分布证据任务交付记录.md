# M2 PIT R2 report_type 与 comp_type 分布证据任务交付记录

> 状态：静态实现与定向开发检查完成；待安全提交；未读取 partial raw；未冻结允许集
> owner：策略开发 session
> branch：`codex/m2-pit-r2-dimension-audit`
> worktree：`artifacts/dev_worktrees/m2-pit-r2-dimension-audit`
> exact base：`086cae9cb12a17c2af695d2cf9a1bd8e8e6bdffe`

## 1. 目标与价值

M2 PIT R1 已把当前 clean instrument inventory、原 plan report、catalog、重构 request set、ledger 和 raw
字节收口到同一个 `RECONSTRUCTED_CURRENT_INVENTORY_V1` audit。本 R2 在这个同一闭包内增加
`report_type`、`comp_type` 以及二者组合的 canonical 行数分布，使 writer 自然终态后能用
可重现证据冻结 PIT 允许的 `report_type` 集合，而不是猜测为单一值。

用户可观察结果：完整 audit JSON 中每个财务表都带有稳定排序、可交叉复算的维度计数；
任何空值、空白、非数字代码、非正整数计数、排序漂移或边际不守恒都禁止 snapshot 发布。

## 2. 明确非目标

- 不读取 writer 正在生成的 partial raw；
- 不在本包中选择、猜测或修改 `allowed_report_types`；
- 不修改 PIT config、runner、factor、Schema、repository、facade 或依赖；
- 不发布 financial snapshot，不运行 PIT，不启动或重启采集 writer；
- 不将当前 inventory 重构冒充为 planner 当时的成员字节证明。

## 3. 权威输入与来源边界

维度分布必须在现有 public `audit_tushare_financials(...)` 中计算，并继承 R1 全部前后验真：

1. exact plan report 与 catalog；
2. canonical current instrument inventory 的 physical file set 和 logical frame digest；
3. 使用现有 planner/request-id 纯逻辑重构的 exact request set；
4. ledger 集合等价、零 active lease 和全部 COMPLETE；
5. raw metadata/row/optional byte closure；
6. audit 返回前再次 fresh 读取 plan、ledger 和 lease。

`PROVENANCE_MODEL` 仍为 `RECONSTRUCTED_CURRENT_INVENTORY_V1`，`PROVENANCE_LIMITATION` 字节不改。

## 4. 冻结输出合同

audit schema 因可观察 JSON 形状变化升为 `tushare-financial-raw-audit-v3`。每个 dataset 的
`quality` 新增：

- `invalid_report_type_rows: int`；
- `invalid_comp_type_rows: int`；
- `report_type_counts: list[{"value": str, "rows": int}]`；
- `comp_type_counts: list[{"value": str, "rows": int}]`；
- `report_type_comp_type_counts: list[{"report_type": str, "comp_type": str, "rows": int}]`。

三张 statement 表 `balancesheet/cashflow/income` 的规则：

1. value 必须精确是非空 ASCII `0-9` 字符串，不做 trim、Unicode digit 接受或隐式映射；
2. 单维列表按 `value` 升序，pair 列表按 `(report_type, comp_type)` 升序；
3. 每个 `rows` 是正整数，不输出零行 bucket；
4. READY 边界下两个单维合计和 pair 合计都精确等于 `raw_rows == eligible_rows`；
5. pair 按两个维度分别汇总后，必须精确等于两个单维列表。

`fina_indicator` 不含这两个源字段，三份列表必须显式为空，两个 invalid 计数必须为 0；
不伪造维度。

### 4.1 官方字段语义（解释层，不代替真实分布）

Tushare 官方 A 股[利润表](https://tushare.pro/document/2?doc_id=33)、
[资产负债表](https://tushare.pro/document/2?doc_id=36) 和
[现金流量表](https://tushare.pro/document/2?doc_id=44) 使用同一组字段语义：

- `comp_type=1/2/3/4` 分别表示一般工商业、银行、保险、证券；
- `report_type=1` 是最新合并报表，`2/3` 是单季/调整单季合并表，`4/5` 是调整后/调整前合并报表，
  `6—12` 是母公司及其单季、调整和调整前变体。

上述语义只用于解释真实 audit 计数。R2 不因官方列举了 1—12 就猜测本地数据实际包含全部代码，
也不在看到分布前把 `1` 预先写入允许集。

## 5. 失败语义

- statement 表的 `report_type`/`comp_type` 为 null、空白或非数字时，audit 以稳定
  blocking code 标记 `BLOCKED`；
- publisher 仅接受 schema v3 且三份计数表的类型、顺序、合计和边际交叉复算全部成立的
  READY audit；
- 任何异常继续通过现有 public stable error 脱敏，不暴露路径、SQL 或内部异常图；
- 存在旧 schema snapshot 时不做隐式升级，按现有 verifier fail-closed。

## 6. 反例与普通开发检查

必测反例：

- 多个 report/comp 组合的列表顺序与两路 marginal 复算；
- 空白和非数字代码阻断 READY；
- 数量单改、pair 增删换序、marginal 与 pair 不守恒时 publisher 在 snapshot 目录创建前拒绝；
- `fina_indicator` 伪造非空维度时拒绝；
- R1 plan/current-inventory/request-set/ledger 闭包测试保持通过。

CPU8—11 由统筹正式转交后，已按唯一实例、BelowNormal、affinity `0xF00`、数值线程不超过 2 的
资源边界，顺序完成 focused pytest → Ruff → mypy → cold import。这些是主 Agent 串行开发反馈，
不另起“独立初验”。

## 7. 精确白名单

1. `src/quant/data/audit_tushare_financials.py`
2. `src/quant/data/publish_tushare_financials.py`
3. `tests/unit/test_audit_tushare_financials.py`
4. `tests/unit/test_publish_tushare_financials.py`
5. `docs/research/agent/M2_PIT_R2_reportType与compType分布证据任务交付记录.md`
6. `docs/research/roadmaps/M2_策略与因子库并行建设路线图.md` 的本包 exact hunk

## 8. 真实数据后续顺序

1. writer 自然终态，ledger 零 incomplete/failed/split/active lease；
2. 在 integration 使用 plan report/catalog 运行唯一 `--verify-bytes` audit，记录 READY 和真实维度分布；
3. 另建极窄 config-freeze 包，只按该不可变证据选择非空允许集；
4. 重跑字节 audit，发布不可覆盖 financial snapshot，再运行唯一 PIT 质量因子试验。

## 9. 交付记录

- 实现路径精确为白名单中的 5/6：两份 production、audit unit test、任务交付记录和 M2 session 路线图；
  `tests/unit/test_publish_tushare_financials.py` 无需修改，既有 public publisher 测试入口由 audit test
  增补 hostile audit 反例复用。
- focused pytest：`18 passed in 16.83s`。
- Ruff：两份 production 与两份相关 test 全绿；mypy：两份 production 全绿。
- cold import：两个公共模块均从本 worktree 的 `src` 精确导入。
- 测试与 mypy 独立临时目录、worktree `.pytest_cache` 已精确清理；本轮结束时无 `0xF00` Python
  残留，既有 finance writer 的 priority/affinity 未被修改。
- 安全提交 SHA 以本记录所在 Git 提交和统筹回报为准，避免文档自引用产生第二个仅改 SHA 的提交。
- 仍待：writer 终态的真实 5,537 证券、4×44,296 request、字节 audit 和维度分布证据。
