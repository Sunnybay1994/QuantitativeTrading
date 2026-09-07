# M2 R21 runner 接入任务书

## 1. 状态、目标与权限

2026-09-07，经理只读设计基线为main `b0db271ae47a52d35e639a1d6b30c5fbd8c93a6e`。
状态：`DESIGN_PENDING_REVIEW_AND_PUBLIC_RECEIPT_API`。本文不是实现派发或经济运行授权。
当前只新增本文；上一轮report未提交改动保留，不能混入实现范围。

最终目标是让已开发的Alpha101 #002进入现有classic walk-forward、成本、coverage、冗余及报告链，
产出可审计的本地有效性判断，而不是只增加一个能导入的因子模块。
开发阶段可先完成下面的纯配置与因子组装；在公共receipt接口、运行身份及诊断明细未闭合前，
不得开通真实runner路径或宣称本任务完成。经济trial、数据更新、PAPER/LIVE不在本包授权内。

## 2. 唯一事实来源与当前缺口

- 因子定义和计算：`src/quant/factors/classic_eleventh_batch.py`、既有R21任务/交付/初验。
- 参数与方向：`configs/research/m2_classic_daily_factors_eleventh_batch.toml`，本包只读。
- 接入目标：`src/quant/research/run_classic_factors.py`及其现有测试。
- 公共rank：`src/quant/factors/cross_sectional_rank.py`，不复制或改变。
- 评价方法：`docs/research/投研评价指标与市场状态研究方法.md`。

当前runner没有eleventh catalog校验和组装分支；labels在folds建立之前生成，code identity在较后阶段计算。
主线不存在`quant.research.trial_receipt`。不得从framework worktree借模块、假造其签名或成功返回值。
框架回报的脚本语法STOP不证明receipt产品逻辑失败，也不解除本包经济入口阻断。

## 3. 配置与纯组装合同

配置采用既有TOML完整键集合、值、列表顺序与日期。正式实现前需把该配置blob/raw SHA写入准入记录；
不在本文复制公式或全部参数形成第二SSOT。类型必须严格，尤其bool不得当int，日期不得由字符串猜测。
未知/缺失字段、方向、reference顺序、fold、成本身份、budget或execution状态漂移均先于snapshot读取拒绝。
配置通过仅表示研究合同正确，不表示准许调用经济入口。

组装函数只能消费传入的已验证bars和canonical sessions，不做repository、文件或网络I/O。
同一bars/session身份供以下现有计算消费：

| 输出 | 权威计算 |
| --- | --- |
| alpha101_002 | compute_eleventh_batch_daily_factors |
| alpha101_011 | compute_ninth_batch_daily_factors |
| alpha101_033、alpha101_101、liquidity_20 | compute_classic_daily_factors |
| alpha158_corr20 | compute_second_batch_daily_factors |

不运行无关batch，不复制rank或公式。以候选计算的symbol/date键为基准，保持null，不因reference可用性
预筛成员或改变横截面rank分母。每表键唯一；reference join不能删行或增行；最终canonical排序。
组装exact列序为symbol、trade_date、alpha101_002、alpha101_011、alpha101_033、alpha101_101、
alpha158_corr20、liquidity_20、history_rows；canonical排序键为symbol、trade_date。
history_rows/liquidity_20只来自classic；second仅投影keys+corr20，不带入其余重复列，不产生suffix或覆盖。
schema预期为String、Date、六项Float64、UInt32；history_rows来自classic的cum_count，
须在准入后的最小fixture中验证实际Polars返回符合该预期，任何不一致先STOP，不cast修复或放宽整数族。
这保留了既有history/liquidity筛选需要的列，不重算或改变计数成员。

纯准备阶段只允许直接测试纯校验/组装函数，不将R21加入main可执行配置准入或dispatch。
R21 CLI仍必须在snapshot之前拒绝：snapshot verifier、repository reader、labels、evaluate、publish调用数全部0。
不得以fixture环境或配置合法为由绕过该入口阻断。

## 4. 经济链必须满足的边界

1. 配置、raw config SHA、成本semantic binding、snapshot身份、冻结universe、folds、signal schedule、
   portfolio、horizons及code identity必须在任何未来收益label读取前闭合。
2. 固定方向为配置中的+1，不从验证收益选方向。reference只作诊断，不成为额外trial或候选summary。
3. 公共attempt start必须先于第一次`build_next_open_factor_labels`，不是仅早于evaluate。
   pre-label schedule不能通过读取exit_date或收益label反推；以已知session/calendar与冻结配置构造。
4. receipt缺失能力、创建/复验失败、既有attempt或身份漂移时，label/evaluate/publish全部0-call。
   具体public API、错误与持久化行为只在该模块合流后绑定，禁止在runner重建第二套receipt。
5. 不改变现有batch配置、方向、schema、输出字节身份和执行路径；新的阻断仅作用于R21身份。
6. 复用既有成本/evaluator/coverage/冗余计算，不把references的无效值变为候选替补，不填未来null outcome。
   h1/h5只诊断，h20主口径及原R21任务要求不得被容易通过的新门禁替代。

## 5. 待冻结项（未闭合前不得派完整实现）

- 已合流公共receipt API及其Windows验证身份；start/terminal payload、run input顺序与恢复禁止合同。
- pre-label schedule的exact terminal holding boundary及与现有label/evaluation日期网格的等价规则。
  必须在读取收益前，以当时已知的calendar×eligibility形成逐日期网格，显式保留全市场eligibility为零的日期。
  当前target builder按筛选后panel中存在的日期排序并每20个日期抽样；内部全市场缺日会压缩日期序列，
  从而可能移动后续调仓日。不得静默把该行为称为每20个完整交易session，也不得让内部缺日隐式改变sampling。
  最终采用既有eligible-date经济身份，还是严格session经济身份，仍须经理/中央在首次收益读取前裁定、
  注册对应identity并绑定配置与日期计划；两者未被本次修订选定，不得观察收益后择优或混用。
  必测完整calendar中第21/41位置及相邻位置全市场eligibility缺日：必须显式STOP，或按事前注册的
  不同identity处理；不得以两个都已压缩的日期结果相等作为PASS。terminal尾部排除与内部缺日分别验证，
  不借未来label/exit价格是否可用来补造pre-label日期计划。
- R21原任务要求的component成员计数、pair coverage、null reason、残差增量、非微盘/Mainboard-VW、
  成交额及极端volume诊断的权威输入、schema、输出位置与不可得状态；因子值列不能冒充这些明细。
- code dependency exact paths、report schema/selection metric、output集合与最终summary字段顺序。
- 在独立worktree冻结exact base/owner。建议branch `codex/m2-r21-runner-integration`；当前未创建。

上述未决项是同一最终接入目标的前置，不是将目标缩减为纯helper或绕开经济验证。

## 6. 最小候选写范围与验证

经理仅本文；未来实现候选仅`src/quant/research/run_classic_factors.py`、
`tests/unit/test_run_classic_eleventh_batch.py`及同名接入交付报告；独立审查只写同名接入初验报告。
是否必须修改既有runner测试须先以实际回归缺口申请，不顺手扩其他batch、config、factor、evaluator或框架模块。

开发fixture必须覆盖：

- 合法config基线通过纯校验；逐字段missing/unknown/type/bool/方向/reference顺序漂移先于data拒绝。
- 对同一可控bars分别调用权威计算，与组装值逐列一致；乱序、缺日、零volume、reference null、重复键。
- 候选symbol/date基数守恒，组装不因reference null损失候选；只调用必要计算且身份参数复用。
- 成本identity不符data0；固定+1不能由验证收益改写；旧batch行为保持。
- 在真实公共API已冻结之后才写receipt编排spy：start durable在label之前；失败label/evaluate/publish0。
- 追加一个独立审查反例：两个reference共同漏同一天时，不得因为交集一致而静默删除候选日期。

验证使用隔离fixture，Windows定向pytest、Ruff --no-cache、mypy指定隔离cache；不得读取真实data、
run产物或消费holdout。exact命令、解释器、临时目录及资源在实现准入后冻结，不能复用已消费evidence root。
没有运行结果时记UNRUN；成功上限是开发接入验证，不是因子有效、promotion、PAPER或LIVE。

## 7. 本轮检查记录

仅进行了当前Git、源码、配置与既有测试文本检查，没有运行Python、测试、经济label或真实data I/O。
本文待独立设计审查；不派实现者猜测第5节，不启动新的通用执行载体，不消耗trial。

独立零写设计初验指出两项需改：组装投影不能留给实现者选择，纯准备不得误开main入口。
本次已补列序/唯一列来源/schema预期及五类I/O与经济调用0-call；原初验历史保留。
schema实际fixture验证仍UNRUN，完整接入的第5节仍未闭合，不将本修订写成实现准入或最终REVIEW_PASS。

本次共享写窗口基线为main `f8238471809915589d7f5a15378edc579f00acf5`。只读源码核对发现：
`run_classic_factors.py`在label构造后按history/liquidity筛选panel；
`classic_factor_evaluation.py`的target builder对panel存在日期取每20项，随后处理terminal边界。
因此全市场内部eligibility缺日可能改变步长，两个同样压缩的计划一致不能证明严格session身份。
本次仅第5节登记收益前待裁定身份及21/41位置反例，不修改实现，不认定已有运行发生了该问题；
没有读取真实数据、运行Python或消费trial，测试仍UNRUN。
