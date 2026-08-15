# M2 PIT 财务质量因子首批假设卡

日期：2026-08-15
状态：研究合同与四因子纯函数已实现；首跑前置闭包实现中；真实 `report_type` 仍未冻结
晋级上限：`RESEARCH_ONLY`；本假设卡不生成 `PAPER_CANDIDATE`、不启动 PAPER

## 1. 目标与范围

上传的因子调研材料把 ROE、ROA、现金利润和应计质量列为经典盈利/质量机制，同时反复提醒公告时点、
财务口径、修订、行业可比性和金融企业专属模型问题。本批不复刻仍标注为“摘要级、需复核原页”的复杂
回归或残差因子，而是先建立四个公式透明、可以由利润表、资产负债表和现金流量表交叉重建的基线。

本假设卡只冻结经济公式、PIT 选择规则和否证条件。源字段的实际类型、单位、覆盖、重复业务键和异常分布
必须以即将采集的真实 raw 为准；这些证据完成前，不新增财务 clean Schema 或生产因子实现。

参考输入：

- [`00_因子体系与评估框架.md`](../quant_factor_research_v2/00_因子体系与评估框架.md)；
- [`04_QIML_2024/03_三月.md`](../quant_factor_research_v2/04_QIML_2024/03_三月.md) 的规模调整 ROE 与盈利质量讨论；
- [`04_QIML_2024/05_五月.md`](../quant_factor_research_v2/04_QIML_2024/05_五月.md) 的应计、毛利和复合质量讨论；
- Tushare 官方[利润表](https://tushare.pro/document/2?doc_id=33)、
  [资产负债表](https://tushare.pro/document/2?doc_id=36)、
  [现金流量表](https://tushare.pro/document/2?doc_id=44)和
  [财务指标](https://tushare.pro/document/2?doc_id=79)字段说明。

## 2. 首批四个候选

记：

- `NI_parent_TTM`：截至报告期、按第 4 节重建的最近四个单季度 `n_income_attr_p` 之和；
- `NI_total_TTM`：最近四个单季度 `n_income` 之和；
- `OCF_TTM`：最近四个单季度 `n_cashflow_act` 之和；
- `AVG_PARENT_EQUITY`：`(本期末 total_hldr_eqy_exc_min_int + 四季度前期末值) / 2`；
- `AVG_TOTAL_ASSETS`：`(本期末 total_assets + 四季度前期末值) / 2`。

| 因子 | Canonical 公式 | 初始方向 | 有效值条件 |
|---|---|---|---|
| `pit_roe_ttm` | `NI_parent_TTM / AVG_PARENT_EQUITY` | 高值优先 | 四个单季利润齐全；期初、期末母公司权益均有限且平均值大于 0 |
| `pit_roa_ttm` | `NI_total_TTM / AVG_TOTAL_ASSETS` | 高值优先 | 四个单季利润齐全；期初、期末总资产均有限且平均值大于 0 |
| `pit_cash_profit_quality_ttm` | `OCF_TTM / NI_total_TTM` | 高值优先 | OCF 和利润四季齐全，且 `NI_total_TTM > 0`；亏损或零利润记 null，不把比率符号反转当高质量 |
| `pit_total_accruals_ttm` | `(NI_total_TTM - OCF_TTM) / AVG_TOTAL_ASSETS` | 低值优先 | OCF、利润和资产齐全，平均总资产大于 0 |

所有比率必须由同一 `ts_code`、同一公司口径、同一 `as_of` 可知版本的报表组成。跨表单位不一致、
报告期缺口或口径无法证明一致时返回 null 并计入 coverage 原因，不做猜测性换算或填充。

`fina_indicator` 中的 `roe/roa/roe_yearly/roa_yearly/ocf_to_profit/grossprofit_margin` 等供应商指标仅用于
覆盖率和数量级交叉核验，不是上述因子的公式 SSOT。若供应商指标与重建值系统性不一致，应先定位口径，
不得为贴合供应商值而事后修改候选公式。

## 3. 适用证券与行业边界

- 首批只纳入 `comp_type == 1` 的一般工商业公司；银行、保险、证券分别对应 `2/3/4`，全部排除；
- `fina_indicator` 本身没有足够的公司类型身份时，必须与同报告期正式报表的 `comp_type` 闭合；无法闭合则不入样本；
- 地产、强周期和重大资产重组公司暂不单独删除，但必须在结果中报告行业暴露、极值和稳定性，不能把
  行业轮动误写成普适质量溢价；
- 金融行业后续另建专属假设卡，使用资本充足率、资产质量、利差、偿付能力等可比指标，不复用本批公式。

## 4. 累计流量、单季和 TTM

资产、权益等资产负债表字段是报告期末存量，不做季度相减。利润表和现金流量表字段按累计流量处理：

1. 一季度单季值等于当年一季度累计值；
2. 二季度单季值等于半年累计值减同一 `as_of` 下可知的一季度累计值；
3. 三季度单季值等于前三季度累计值减同一 `as_of` 下可知的半年累计值；
4. 四季度单季值等于年度累计值减同一 `as_of` 下可知的前三季度累计值；
5. TTM 等于连续四个已闭合单季值之和；缺任一期、跨公司口径或相减后出现无法解释的修订冲突均记 null。

首批 canonical 输入只使用合并口径累计报表，不混用母公司报表或供应商单季表。真实 raw 到位后先确认
`report_type` 分布并冻结允许集合；在此之前版本化配置必须保持 `UNFROZEN` 与空集合，runner 在读取
snapshot 或创建 artifact 目录前停止。研究函数只消费已冻结的显式允许 tuple，不硬编码某个数值代码。
历史修订可以使前期累计值
发生变化；每个 `as_of` 必须用当时已知版本重建，不能用今天下载到的“最新一版”回填过去。

## 5. Point-in-Time 与修订链

### 5.1 可知日期

- 利润表、资产负债表、现金流量表优先使用有效 `f_ann_date`，缺失时回退 `ann_date`；
- `fina_indicator` 使用其 `ann_date`；
- 两个公告字段同时存在但顺序或含义冲突时，首轮 clean 采用较晚日期作为保守可知日期，并把冲突计入质量报告；
- 由于只有日期没有发布时间，某报告在 `available_date` 当日不能用于当日收盘信号。它最早在严格晚于
  `available_date` 的首个交易日收盘进入 `as_of`，再于下一开市日开盘执行。

### 5.2 版本选择

raw 必须保留所有版本，不覆盖修订。对每个信号 `as_of`：

1. 只考虑可知日期早于该信号知识截止日的行；
2. 按 `ts_code + end_date + 合并/公司口径` 建立修订链；
3. 选择截至该时点最新的可知版本；
4. `update_flag` 只作为修订证据和质量字段，不能直接解释成“历史上应选最新行”；
5. 同一业务键、同一可知日期存在经济字段不同的多行时，不按文件顺序或内容 hash 任意决胜，必须 quarantine；
6. 任何后续公告只能从其自身可知日期起改变因子，不能重写更早日期的研究截面。

## 6. 评估与否证协议

- 信号遵守 `as_of` 收盘到下一开市日开盘，输出 `target_weight`；
- 使用与日频经典因子相同的冻结 walk-forward 折和 0.5x/1x/2x 成本压力；
- 每个因子报告 coverage、因缺失链/非金融过滤/分母非法/冲突 quarantine 导致的 null 占比；覆盖率以
  独立预注册的完整信号日历为分母，缺失日期补零且不得顺延，每日有效证券至少 100、日期覆盖率中位数
  至少 80%（恰好 80% 通过，低于即拒绝），并直接参与最终研究结论；
- 训练/验证期确定方向、winsorization 和组合方式，测试期只打开一次；
- 同时报告与规模、行业、`daily_basic` 价值代理和既有价量因子的相关性与增量 RankIC；
- 不可覆盖 `run.json` 必须绑定 bar、财务 clean snapshot、公式版本、PIT selector、股票池、fold、成本和代码身份。

出现任一项即保持 `REJECTED` 或数据阻断：

- 真实 raw 无法证明公告日期、修订链、季度闭合或公司类型；
- 关键 coverage 主要依赖回填、最新修订回看或跨口径拼接；
- 三折方向不稳、测试期方向反转或分组不单调；
- 信息主要是行业、规模或既有价值因子的重复暴露；
- 1x 无可复现净收益，或 2x 成本后经济意义消失；
- 看到测试结果后才改变公告滞后、累计转单季、亏损处理、行业排除或阈值。

即使四个候选有正证据，本批最多进入 `RESEARCH_ONLY`。历史行业分类、完整证券池 PIT、统一市场事件
回放和冻结后前向观察没有关闭前，不得晋级 PAPER。

## 7. 实现前置条件与后续批次

实现前必须依次完成：

1. 当前财务 regular writer 自然退出，避免并发写 ledger；
2. 重新探测 `income_vip/balancesheet_vip/cashflow_vip/fina_indicator_vip`；
3. 用代表季度核对全市场证券覆盖、行数上限、字段、重复业务键和修订样本；
4. 决定采用按报告期 VIP 方案，或已修正的逐证券五年窗口 regular fallback；
5. 用冻结 plan-report、当前 canonical instrument inventory 和现有 catalog/chunk/request-id 逻辑重构完整
   request 集合，确认四表集合等价、零 incomplete/active lease 后，发布不可覆盖财务 clean snapshot；
6. 在 `quant.factors` 中实现纯函数，并由同一个 PIT repository 提供截至 `as_of` 的窄数据视图。

其中 PIT 修订选择的纯函数已由 `quant.data.financial_pit` 实现，累计转单季、连续四季 TTM 与本卡四个
canonical 公式已由 `quant.factors.pit_quality` 实现；首批 raw 到 PIT factor 的纯内存标准化与窄投影由
`quant.data.financial_clean` 实现。研究侧 `quant.research.pit_quality_research` 已实现交易所月末信号日和
稀疏 PIT 横截面：同日公告严格不可见、下一交易日才进入；最新利润表报告期发生经济冲突时，证券不会
静默退回旧报告期。四模块合计 28 项定向测试覆盖 Schema drift、非法数值显式隔离、
同日不可见、较晚公告日、修订、同日经济冲突、输入逆序、完整重复、手算 TTM、利润缺季、现金缺季独立
覆盖、金融公司过滤、亏损分母和重复业务键。这些函数都不读取
共享目录，也不把 partial raw 升级为 clean。其余前置条件仍保持开放，尤其是全量字段类型、报表类型允许
集合、公告日覆盖、raw Schema drift 和不可覆盖 clean snapshot；纯函数通过不代表财务数据已经可用于回测。

现有 planner 的 2026-08-15 plan-report 只保存 inventory count，不保存当时成员字节或 request-set digest。
首跑采用显式 `RECONSTRUCTED_CURRENT_INVENTORY_V1` 来源模型：绑定当前 instrument 的物理与逻辑摘要并
重构精确 request 集合，但不得把它描述为恢复了 planner 当时的成员字节。下一次启动任何新 bulk plan/writer
前，planner 必须原生持久化 inventory 与 request-set digest。

终态发布与读取代码已经完成 fixture 闭环，但尚无真实财务 snapshot id。真实 walk-forward 只能消费
`verify_tushare_financial_snapshot` 验真的 snapshot，并通过 bounded repository 一次读取所需报告期修订
历史，再由月末信号构造器生成 `as_of` 横截面；禁止因 publisher 已实现而绕过 `COLLECTING` 门禁或直接
读取 partial raw。

规模调整 ROE、Dechow–Dichev 应计质量、毛利率同比、盈利稳定性和复合质量属于第二批。调研文档对其中
多项只提供摘要或推断方向，必须先复核原页、确认真实字段和第一批基线结果，不能在第一批测试集上继续
扩搜索空间。
