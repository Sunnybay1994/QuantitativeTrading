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

## 5. 已冻结schedule与剩余待冻结项（未闭合前不得派完整实现）

- 已合流公共receipt API及其Windows验证身份；start/terminal payload、run input顺序与恢复禁止合同。
- 中央已选定R21新schedule身份：strict canonical-session，不再保留eligible-date作为本次可选执行方案。
  权威SH/SZ共同calendar必须独立验证；现有bars日期union不得冒充canonical calendar。
  每fold在任何eligibility筛选前，以首个test canonical session锚定，计划index为0、20、40……；
  S为权威session序列，i为该计划signal在S中的位置，entry=S[i+1]，h20 exit=S[i+21]。
  只排除无完整holding或exit超过test_end的连续尾部，不缩短holding，不因内部hole重新确定相位。
  pre-label已知calendar×eligibility日期网格必须完整显式保留；仅当其与canonical测试日期网格一致时
  才可复用现有builder。内部全市场eligibility缺日STOP；个别证券缺失只进入成员/coverage，不缩日历。
  计划日候选不足冻结数量不得以continue冒充成功，不替补缺失outcome、不跳期、不前填。
  日历identity、fold锚、step、universe、eligibility/date-grid摘要、planned与excluded-tail日期，
  连同config/cost/code必须在收益读取前闭合并绑定attempt start；不借future labels或exit价格可用性反推计划。
  R21须在首次收益读取前注册该新schedule identity并绑定配置；具体序列化/API身份仍随公共receipt准入冻结，
  不由本次文档猜接口。旧batch/旧run不迁移、不重标，跨口径比较另立任务，不观察收益后切换方案。
  必测完整calendar中第21/41位置及相邻位置的全市场eligibility缺日：本身份必须STOP，不移动后续调仓日；
  两个都已压缩的日期结果相等不是PASS。另验单只缺日不缩日历、fold首日不能延后锚定、
  exit恰等test_end保留/超界仅裁连续尾部，内部hole与尾部必须分别判定。
- 完整诊断需求仍以`M2_RESEARCH_R21_Alpha101002量价背离任务书.md`第7节为权威，评价口径引用
  `docs/research/投研评价指标与市场状态研究方法.md`；下表仅登记接入影响，不复制公式或另建SSOT。

| 诊断 | 当前权威来源与可复用部分 | 尚缺合同与当前不可得状态 |
| --- | --- | --- |
| component成员计数 | `classic_eleventh_batch.py`的`long_form`与`ranked`中间关系；`cross_sectional_rank.py`定义rank成员语义 | 公共结果只有symbol/trade_date/alpha101_002，未暴露trace；`TRACE_OUTPUT_NOT_EXPOSED`。建议按date×component区分候选键数、finite值数、rank可定义数；finite成员只有1时rank可定义数不能算1。 |
| 内部6期pair coverage | 同一因子计算的`_pair_count`及窗口完整性 | `TRACE_OUTPUT_NOT_EXPOSED`；建议保留每symbol/date的窗口ready及0..6配对计数，不完整窗口不能伪记为完整窗口的0配对。精确dtype/schema仍待冻结。 |
| null/零方差原因 | 同一计算中的bar存在性、lag、正volume、rank成员及`_u_ss/_r_ss` | `TRACE_OUTPUT_NOT_EXPOSED`；最终null不能反推唯一原因。warmup、缺session/bar、非正volume、rank成员不足、pair不足、单侧/双侧零方差的flags和primary reason优先级待冻。原有负volume、非finite、schema整调用拒绝不能降成局部null。 |
| 与references的RankCorr | `classic_factor_evaluation.py::evaluate_factor_redundancy`的daily成员数/相关系数及summary相关中位数 | 数值计算可复用，但joint-finite筛选后存活日期不是完整计划或对称coverage证明；须另用计划/成员网格识别遗漏日期。 |
| 残差增量 | 目前没有#002对五个references的权威残差API；`max_daily_basic_control.py`是MAX专属控制，不可复制私有回归冒充通用实现 | `NOT_EVALUATED / RESIDUAL_SPEC_UNFROZEN`。rank/raw变量、联合或逐项controls、共同样本、截距、病态矩阵/minimum样本及增量评价身份待裁定；RankCorr不能替代残差要求，不能按测试收益挑controls或新增候选。 |
| 非微盘/Mainboard-VW | `schemas.py`中Bar1d没有市值/板块；DailyBasic1d有市值类契约，但不证明本地覆盖 | `NOT_EVALUATED / POINT_IN_TIME_SIZE_BOARD_INPUT_UNBOUND`。须绑定PIT市值snapshot/join、历史板块和分位点参考总体。Top800/成交额不能冒充非微盘，等权不能冒充VW，流通市值与free-float口径不能互换；新输入另行准入。 |
| 成交额分层 | Bar1d.amount及既有liquidity_20计算可作为候选解释变量；受保护证券级panel可复用评价逻辑 | `DIAGNOSTIC_SPEC_UNFROZEN`。层数/分位点、current或lagged、缺失和ties须事前冻；保持primary排序与持仓不变。已有聚合group_returns不能重建证券分层，成交额代理不能证明冲击成本或容量。 |
| 极端volume变化 | 同一因子计算中的volume变化中间量，不在runner重算另一套特征 | `TRACE_OUTPUT_NOT_EXPOSED / DIAGNOSTIC_SPEC_UNFROZEN`。绝对/有符号阈值或分位点、窗口、成员/ties待冻；全样本primary保留，排除极端值只能独立诊断，不能重排后择优。 |

三类coverage必须分别命名、保留各自分母与日期网格，禁止相互替代：

1. component内部6期pair coverage衡量构造窗口中两rank的共同有效观测；不涉及未来收益。
2. 因子可用率复用`run_classic_factors.py::evaluate_factor_coverage`的eligible_rows/valid_rows及coverage，
   但其现有scheduled_rebalance依赖label后panel/exit_date_20；R21必须先闭合本节收益前严格session计划，
   不直接继承压缩日期或以未来exit可用性定义分母。
3. 未来label配对coverage来自`classic_factor_evaluation.py::evaluate_factor_period`的
   factor_count/paired_count/coverage_numerator/coverage_denominator/coverage_status；只在receipt与经济授权后评价。
   它不能证明内部6期窗口完整，也不能用内部pair_count证明未来label可用。

single-pass trace仅为**建议的最小扩围**：经另行批准才可在eleventh factor及其定向测试增加显式诊断出口，
复用一次计算的中间关系，并保持原三列公共结果及行为不变。不是已批准API，不隐式扩大第6节白名单；
禁止runner复制log/rank算法、重算一套诊断或运行时截取私有locals。诊断网格可包含无bar键，
但不得把这些键加回原因子结果。trace schema、null优先级、残差、PIT size/board、分层和极端阈值未冻结前，
完整R21诊断仍不具备实现准入；字段契约和静态可复用函数均不证明真实数据已具备。
- code dependency exact paths、report schema/selection metric、output集合与最终summary字段顺序。
- 在独立worktree冻结exact base/owner。建议branch `codex/m2-r21-runner-integration`；当前未创建。

上述未决项是同一最终接入目标的前置，不是将目标缩减为纯helper或绕开经济验证。

### 5.1 single-pass trace接口方案（待独立设计审查，非实现授权）

建议在同一factor模块提供`compute_eleventh_batch_daily_factors_with_trace(bars, *, sessions)`，
返回exact三表mapping：`factors`、`component_counts`、`observations`。旧公共函数签名及三列输出不变，
两入口共用一个计算核心；每次公共调用只构造一次特征、调用一次公共rank helper、计算一次相关。
旧入口不必物化诊断表；新入口从同次long_form/ranked/grid投影，不复制rank/correlation或另算公式。
返回类型封装及新增public export仍待独立设计审查，不由本文自动批准生产扩围。

三表列序与dtype方案如下；未标nullable者不得null，全部按所列键稳定升序，禁止运行时学习schema：

- `factors`：symbol=String、trade_date=Date、alpha101_002=Float64(nullable)。键与旧结果exact相同，
  仅实际输入bar keys；完整grid中的无bar行不能新增factor键。新旧结果列序/dtype/值/null/正零必须一致。
- `component_counts`：trade_date=Date、component=String、grid_symbols=UInt32、finite_values=UInt32、
  ranked_values=UInt32；键trade_date/component，component仅volume_change、intraday_return。
  每日两个component都保留；grid_symbols是输入symbol×calendar网格数，不是eligibility证券数。
  finite_values来自同次long_form，ranked_values来自同次ranked；n<2时ranked_values=0，
  n>=2时ranked_values=finite_values，即使全部ties也如此。
- `observations`：symbol=String、trade_date=Date、bar_present=Boolean、volume_change=Float64(nullable)、
  intraday_return=Float64(nullable)、volume_rank=Float64(nullable)、return_rank=Float64(nullable)、
  window_ready=Boolean、pair_count=Int64(nullable)、volume_ss=Float64(nullable)、return_ss=Float64(nullable)、
  alpha101_002=Float64(nullable)、primary_reason=String，随后追加下表列（顺序不变）。
  键symbol/trade_date，覆盖输入symbols×完整sessions。feature/rank/ss均投影自同次中间关系；
  有bar键上的因子值必须与factors逐值相同。正零归一仅用于factors与observations的alpha101_002，
  不另算一份相关值；其他中间列忠实投影，不额外修改零的符号、clamp或重算。

| 追加列（顺序） | dtype/null | 逐行触发定义 |
| --- | --- | --- |
| session_index | UInt32/non-null | 传入sessions的零基位置，每symbol相同calendar，不按有bar日期编号。 |
| current_bar_missing | Boolean/non-null | 当前grid未匹配bar即true；与bar_present互补。 |
| lag1_bar_missing | Boolean/nullable | index<1为null，否则前一canonical位置未匹配bar为true。 |
| lag2_bar_missing | Boolean/nullable | index<2为null，否则前两canonical位置未匹配bar为true。 |
| current_volume_zero | Boolean/nullable | 当前bar缺失为null，否则volume==0；null不得填0。 |
| lag2_volume_zero | Boolean/nullable | index<2或lag2 bar缺失为null，否则lag2 volume==0。 |
| volume_rank_members_lt2 | Boolean/non-null | 同date volume_change的finite_values<2，不等价于本symbol值缺失。 |
| return_rank_members_lt2 | Boolean/non-null | 同date intraday_return的finite_values<2，不等价于本symbol值缺失。 |

原计算的volume_change实际依赖current与lag1 bar存在，以及current/lag2 volume为正；lag2缺bar自然不可用。
lag1 volume为0但bar存在不额外使当前volume_change失效，不得增加该限制。负volume、非法schema及非finite
仍沿原入口拒绝边界处理，不转成局部zero flag。rank的null同时取决于本值和该component成员数，
单看members_lt2不能反推全部null原因。flags是逐行事实、可并存，不构造第二套窗口归因算法。

终点i的相关窗口exact为完整calendar的[i-5,i]；i<5时window_ready=false且pair_count=null，
其后window_ready=true、pair_count在0..6。窗口ready不代表构造预热完成：窗口中volume_change可能回看至i-7，
所以index5/6仍不足8个session。缺bar不压缩窗口，不对仅有bar的子表滚动。
PAIR_INCOMPLETE可从窗口内逐行flags解释，不能用终点flags冒充整窗口唯一原因。

primary_reason按以下顺序拟定，独立审查前不能用于运行：

1. 当前bar缺失：MISSING_CURRENT_BAR。
2. 否则session_index<7：WARMUP_LT8_SESSIONS。
3. 否则pair_count!=6：PAIR_INCOMPLETE。
4. 否则两ss均<=0：BOTH_VARIANCES_NONPOSITIVE。
5. 否则volume_ss<=0：VOLUME_VARIANCE_NONPOSITIVE。
6. 否则return_ss<=0：RETURN_VARIANCE_NONPOSITIVE。
7. 否则VALID；须与当前bar存在且最终因子非null、finite严格等价，并通过原正零归一后再核对。

微负ss不得伪称精确零或clamp；VALID不能仅凭方差predicate跳过旧函数最终有限性检查。
共同计算核心及legacy入口保持原错误顺序：先投影原bar keys，再执行原最终因子有限性检查及正零归一；
不得将全grid诊断检查放入共同入口。普通null与有限微负ss忠实保留，微负按NONPOSITIVE解释，
不将预热或pair不足所致普通null当异常。非finite中间态、pair_count=6但ss为null等不可解释状态，
以及reason与最终值矛盾，仅由trace分支专属拒绝，整个新入口不返回partial三表。
该专属拒绝即使只由无bar grid行触发，也不得反向扩大legacy入口的拒绝范围。
这是已明确的两入口诊断严格度差异，不授权改变旧计算数值或错误顺序；未运行fixture不声称兼容性已获证明。

另补测试专属故障注入：以缺bar fixture或calendar末尾超集为基础，仅使无bar grid行的ss异常，
原bar结果保持不变；legacy结果和拒绝行为须不变，trace依上述专属规则拒绝且无partial三表。
该反例检验检查的作用域，不表示正常输入已发现该数值bug，也不允许在生产新增注入入口。

必测新旧入口输出恒等及一次rank调用；乱序输入结果不变；无bar grid行不新增factor键；
index0/1未定义lag为null而非已知缺失；index5/6窗口ready但warmup；lag1缺bar使下一位置feature null；
lag1 bar存在但volume0且两端正值不能误加过滤；窗口旧位置缺pair而当前flags正常不能误标VALID；
单成员rank null与多成员全ties rank有效/方差非正分开；零值须比较符号位，两个入口均正零。
负volume、nonfinite及schema拒绝回归不减弱，不能只用新旧入口共享同一错误实现的相等断言代替独立oracle。
本方案不解决残差、PIT市值/板块、分层阈值或经济执行权限，完整接入目标保持不变。

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

2026-09-08中央在main `f52b5792546f709a46bee5941ba65fbaf5bd4b7c` 的exact1写窗口采纳严格session方案。
本次仅更新第5节及本记录，前述“待裁定”是历史状态，现由严格canonical-session新身份裁定替代。
公共receipt API、完整接入其他明细及独立实现准入仍未闭合；本裁定不授权data读取、labels、evaluate、publish
或trial，不改变旧batch。测试、真实日历/eligibility网格核验仍UNRUN，不把设计裁定写成运行验证通过。

2026-09-08基于main `fb24263911a7773cc844de73d14625d91d13b740`，在中央exact1窗口仅补第5节诊断影响矩阵
和本记录。只读核对factor/rank、runner/evaluator、MAX专属控制及schema权威来源，区分可复用输出、
未暴露trace和未冻结经济设计；三类coverage不可互证。single-pass trace保留为另行扩围建议，
不修改第6节候选白名单、不批准新增接口。残差/PIT市值板块/分层阈值仍未冻结，完整接入仍未完成。
本次仅文档diff、引用存在性与字节卫生检查；Python、测试、data/labels/evaluate/publish及trial均未执行。

2026-09-08中央复核main `129de5c5aa3487bb457b41188c7c94ee672d3cc9` 后授exact1文档窗口。
新增5.1三表及逐行flags方案，源码证据为eleventh的lag1 presence条件、最终finite检查和正零归一；
既有missing-lag1与first-value-session-eight测试只作文本映射，未重跑。接口仍待独立设计审查，
第6节runner-only候选范围不自动扩大；新增中间态检查与旧入口拒绝范围的潜在冲突必须回审查。
仅文档静态检查，无生产/测试实现、Python、数据、trial或ETF派发；历史设计及STOP边界均保留。

2026-09-08同一独立reviewer给出DESIGN_REVIEW_NEEDS_CLARIFICATION（P0=0/P1=0/P2=1）：
指出trace检查及正零规范作用域不够明确；未发现确定算法矛盾。中央在main
`636cf4fff98b9bda3d4d35c475cd4210a8db00e7`授exact1窗口，本次仅澄清5.1及本历史，
保留原P2结论，补专属拒绝与故障注入反例；提交后交同reviewer零写复验。
本次仅静态hygiene/diff检查，未实施trace、运行Python/测试、读取data或消费trial。

## 8. SinglePassTrace最小实现准入

2026-09-08同一独立设计reviewer复验DESIGN_REVIEW_PASS / P0=0 / P1=0 / P2=0，关闭唯一P2；
该结论是设计审查，不是运行验证。实现完整引用5.1三表、flags、专属拒绝及兼容性合同，不复制公式。
统筹冻结base `eba75446b6a8dbcb1c3d3f9cffbadbb0b5a2f64a`，branch `codex/m2-r21-single-pass-trace`，
source `F:\AI_Coding\QuantitativeTrading\artifacts\dev_worktrees\m2-r21-single-pass-trace`。
这是第6节之外单独批准的窄factor trace包，不授权完整runner接入或宣称R21最终目标完成。

经理先仅提交本文；随后Luna Worker 3（01a03730-623a-7fd3-b4c4-6f3ad99c97c5）创建唯一隔离实现subagent。
实现只写并可提交exact3：

- `src/quant/factors/classic_eleventh_batch.py`
- `tests/unit/test_classic_eleventh_batch.py`
- `docs/research/deliveries/M2_R21_SinglePassTrace交付报告.md`

原独立审查上下文另仅写`docs/research/reviews/M2_R21_SinglePassTrace独立初验报告.md`；实现者不得写review。
同模块公共导出允许；不修改__init__、runner、receipt、labels、rank helper、配置或其他路径。
不借用或替换ETF实现者，不创建第二现场；主线只读。任务书提交后实现阶段只读。

允许source cwd内Windows fixture-only定向验证，解释器固定`D:\Miniforge3\python.exe`，
单进程，`POLARS_MAX_THREADS=2`、`OMP_NUM_THREADS=1`。原生命令顺序：

1. `D:\Miniforge3\python.exe -m pytest -q tests/unit/test_classic_eleventh_batch.py -p no:cacheprovider --basetemp=artifacts/agent_runs/m2-r21-single-pass-trace/pytest-<fresh-attempt>`
2. `D:\Miniforge3\python.exe -m ruff check --no-cache src/quant/factors/classic_eleventh_batch.py tests/unit/test_classic_eleventh_batch.py`
3. `D:\Miniforge3\python.exe -m mypy --cache-dir artifacts/agent_runs/m2-r21-single-pass-trace/mypy src/quant/factors/classic_eleventh_batch.py`

fresh-attempt是每次不重复的验证标识，禁止复用已占用pytest目录；日志/产物/cache仅在source内
`artifacts/agent_runs/m2-r21-single-pass-trace`，设置`PYTHONDONTWRITEBYTECODE=1`避免源码目录cache。
保留原生stdout/stderr/exit并在delivery记录命令、环境、代码身份及实际结果，失败证据保留不覆盖。
缺依赖如实STOP，不安装或换解释器；禁止xdist/全量测试/网络/真实data/既有run读取/trial/交易。
反例及行为验证遵守5.1，保留已有手算oracle，不以共享核心自比较替代独立预期。
Windows结果不冒充Linux Gate或经济有效性。交付后实现者退出，由原独立上下文审查及经理领域验收，
再向统筹提交source SHA与证据；Worker不得合流、退休或删除现场。

## 9. SinglePassTrace REWORK1 与新验证准入

2026-09-08原独立初验为REVIEW_FAIL / P0=0 / P1=2 / P2=0，详见
[原审查报告](../reviews/M2_R21_SinglePassTrace独立初验报告.md)。报告6918 bytes，
SHA256为`5d05d6bb119c29c8c523777893a9263617ed0966d6ba64dc4e0fb0db855f6a1f`。
审查输入HEAD为`085e04488ba1d25bfdb1e3ef497efa148b9e8511`；保留implementation
`6fd05834cca189df50b9fa2542df5da56f73e023`及后续delivery提交，不重写历史。

### 9.1 现象、根因与最小返工

1. 批准证据根当前仅有mypy缓存，没有原生stdout/stderr/exit或所述三个pytest attempt目录。
   这是验证留存合同缺口，不证明历史未执行，也不能独立证明所报23pass、Ruff/mypy通过或导入路径。
   原报告作为历史保留；delivery追加更正，明确旧验证不可独立核验，禁止补造旧日志、退出码或SHA。
2. 测试只有数值相等/equals/approx，没有§5.1要求的零值符号位检查。以原审查报告的非退化零相关
   六期rank矩阵为独立数学oracle，经真实bars和公共rank路径生成零值；不得mock rank绕过构造。
   legacy、trace.factors、trace.observations均须先断言目标值非null且等于零，再用
   `math.copysign(1.0, value) == 1.0`或等价位检查逐项证明正零，不能让空的零值集合导致vacuum PASS。
   保留完整独立rank矩阵预期和既有手算oracle；生产不变，不以放宽容差修fixture。
3. 补齐已冻结trace乱序三表恒等及独立的非finite中间态、pair_count=6但ss=null拒绝反例。
   沿既有测试注入边界，不新增生产注入接口；旧入口拒绝域、原bar结果及普通null语义不变，
   trace异常不能返回partial mapping。有限异常ss单一反例不能代替上述不同分支。

以上均由原Worker 3恢复同一原实现subagent；禁止第二实现链。实现唯一可写：
`tests/unit/test_classic_eleventh_batch.py`及`docs/research/deliveries/M2_R21_SinglePassTrace交付报告.md`。
production、公共rank、配置、taskbook、roadmap及review在实现阶段只读。若反例证明必须改production，
先STOP提交最小反例申请扩围，不自行修公式。经理本轮仅追加本文并提交本文及原review。

### 9.2 fixture-only 定向复验

统筹同时批准本轮定向复验，不要求先再走一次静态交付。沿用§8的解释器、三个产品命令顺序、
单进程和线程上限；不得变更测试范围、安装依赖或运行经济入口。新证据根唯一为source内
`artifacts/agent_runs/m2-r21-single-pass-trace-rework1/`，旧根及缓存全部保留，不清理或覆盖。
每次尝试在新根内用独立未占用子目录，pytest basetemp及mypy cache均指向该次目录内；
pytest仍禁cacheprovider、Ruff仍--no-cache，PYTHONDONTWRITEBYTECODE=1。

在产品阶段前保存实际argv、cwd、解释器身份、生产/测试bytes与SHA，环境仅记录白名单
POLARS_MAX_THREADS、OMP_NUM_THREADS、PYTHONDONTWRITEBYTECODE、PYTHONPATH。
PYTHONPATH明确指向当前source/src；只做本模块冷导入，保存实际module.__file__，验证它解析到
当前source的冻结生产文件，不能仅凭环境声明推断。不得输出完整环境、凭据或加载真实数据。
导入身份不符即停止产品阶段，不能把main的结果计入本轮。

各阶段真实stdout、stderr、原生exit分别在该次目录新建留存；未运行阶段标UNRUN。
结果引用实际代码身份与attempt，失败不覆盖；修测试后需新的attempt。新运行不是旧证据恢复，
delivery必须把历史不可核验与新可核验结果分开。证据采集采用最小原生命令方式，不新建通用carrier框架。
本节不授权真实data、网络、ETF、receipt、labels、evaluate、publish、trial、PAPER或LIVE。

通过条件：两项P1及既冻反例的测试闭合，§8三项产品验证有独立可读取的原生证据及worktree导入身份；
同一原独立审查上下文复验，只写原review追加历史。通过上限仅Windows development validation；
未获统筹合流，不合并或退休source，完整R21接入及经济有效性继续未完成。
