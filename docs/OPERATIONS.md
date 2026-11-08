# 运维

唯一环境：Windows，`D:\Miniforge3\python.exe`（Python 3.13）。项目根执行：

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:POLARS_MAX_THREADS = '4'
$env:PYTHONUTF8 = '1'
python -m quant --help
python -m quant status
python -m quant gpu-check
```

## 项目协作

2026-11-04 起停用项目级 Concord：无需认领、交接或 inbox 监听；按当前用户指令与工作清单执行。项目客户端的 Concord MCP 已移除，Codex 项目配置显式禁用全局同名入口，并清空本项目继承的 Concord 生命周期 hook。历史协作状态保留在 `artifacts/archive/concord_disabled_20261104/runtime/`，不作为当前任务状态来源。已打开的客户端需重新载入项目配置，清除旧工具和规则缓存。

## 日常命令

D2 结构化数据独立于订单链采集：`QuantitativeTrading-StructuredDaily` 工作日19:00运行 `scripts/run_structured_daily.ps1`，入口 `python -m quant data structured-incremental --with-futures --as-of YYYY-MM-DD --output <新目录>`。9张表使用 `configs/data/structured_sources.toml` 的可得时刻规则，IF/IC/IM只进入月报市场面板。`quant doctor`逐表展示新鲜度和真实检查日数；研报试用权限仍显示受限，不能计成九表完整验收。重试已有采集须显式 `--resume`，保留原始观察时间。

Top15仅观察账户：用户于11-06裁定开户并保留`REJECTED`，入口 `python -m quant paper top15-observation --to YYYY-MM-DD`，配置 `configs/paper/top15_limit_1pct_observation_20261106.toml`。现金初始化从实际建立日开始，不回放旧委托；月末信号、固定1%报价、最多3日尝试，沿用股票账本和原费用，首次正式信号11-30。日更与独立订单链已接入，该账户失败单独记载且不阻断主账户，不推送委托、不占准入名额、`auto_trade=false`。产物在 `artifacts/paper/top15_limit_1pct_observation/`，看板显示仅观察及原结论。`rehearsal/20261106_real_inputs_01/validation.json`记录11-05真实输入强制月末预演与正式文件SHA不变，预演不计正式业绩。

A2·30万同形观察账户：30万元；Top15 40%+512890/511010各30%；股票月末1%预挂最多3日、ETF季度再平衡；`shadow=true`、`auto_trade=false`。首正式信号11-30。冻结降级只读已有同日输入；缺少ETF捕获则报告不可用。入口 `python -m quant paper account-30w-top15 --to YYYY-MM-DD`；12-01盘前 `--notify-due`只发冻结11-30模拟清单供人工演练，不下真钱。当前仅实现/预演，12月真实成交与自然验收尚待发生。

Q10 与影子账户可独立更新：`python -m quant paper order-chain --to YYYY-MM-DD`，只读取冻结预测和账户执行行情，不运行市场背景、分钟补数或月度对比；显式加 `--notify` 才推送。两账户分别记录结果，一个失败仍保留另一个的订单，任一账户失败退出码为 1。运行前确认没有正在更新同一账户的日更进程。原 21:30 日更已启用 `independent_orders=true`：先仅刷新冻结模型的实际因子、生成预测和两账户订单并推送，再处理辅助依赖、分钟补数与背景。只有真实通道成功才记录推送完成，同一订单内容成功后不重复发送。

月末隔离预演：`python -m quant paper rehearse --as-month-end --to YYYY-MM-DD`。复用正式订单构建规则，从早于该日的最近账户快照复制到各账户 `rehearsal/<日期_时间戳>/`，保留正式账户控制开关，只生成、不推送；失败也留下 `rehearsal.json`。使用当日已完成且通过质量检查的冻结前向预测；不生成替代预测。生产快照、净值与最新订单不改，预演状态不计入正式账户。

省略`--to`时，按已有沪深日历选择最近达到数据时间窗口的交易日：21时前以上一日为上界，21时后可用当日；行情与冻结预测仍须实际通过质量检查。保险任务同样使用这个选择，提前运行或延期到周末不会把休市日当作预演信号日；不补拉日历，不用旧日期的成功结果冒充本次完成。

配对月报在账户订单及辅助输入刷新之后，按 `configs/data/q10_forward_return_benchmarks_v1.toml` 续接原三条全收益基准，冻结历史前缀与月度规则保留。独立补齐入口：`python -m quant data forward-benchmarks --end YYYY-MM-DD --output artifacts/research/<新目录>`；只读取已完成交易日的原生行情、成分和公司行动，缺少事实或无法解释的报价缺口不发布成功收据。补记月内对比不算完整月份，也不替代自然调度验收；原失败记录保留。

研究简报复用原日更晚间任务：每月首日21:00后生成上一完整月份，先完成日更与订单，再由 `python -m quant report brief --scheduled --no-notify` 判断是否到期，不新建任务或启用N5。数字来自注册表及结构化表，市场描述使用该月份内有原完成收据的日更观测；成功产物保持不变，LLM每月最多一次尝试，失败和计费仍留收据。产物为 `artifacts/research/brief/<月份>.md`、`.facts.json`、`.narrative.json`、`.scheduler.json`；自动流程不推送消息。非到期日只返回not_due；12-01自然执行未发生前不记验收完成。

运行 `scripts/register_paper_insurance.ps1` 注册两项保险：`QuantitativeTrading-PaperRehearsal` 在 2026-11-27 22:10 预演；`QuantitativeTrading-PaperOrderWatch` 每天 22:30 只读检查，只有月末未就绪才通知。就绪需当日正式状态、最新 Markdown 和与快照一致的订单 CSV，不能只凭旧文件存在。日志与退出码在 `artifacts/paper/insurance_scheduler/`。doctor 首行显示下一调仓日和两账户订单就绪状态。任务首次自然运行前显示 pending，不视为已通过；K1 仍须等待 11-27 与 11-30 实际验收。

个人账户固定Top5/Top50与佣金配对实验：[运行和断点恢复](operations/PERSONAL_ACCOUNT_REPLAY.md)。

含 Q10 的完整日更与其数据可得时间保持一致：21:00 前的触发只记录
`deferred` 和最早可运行时刻，不启动整套日更、不误报失败；由既有21:30触发执行。
因此该配置下17:30不再生成全套模型/账户日更。独立数据更新任务不受影响。

晚间入口在启动时固定目标交易日，日更先执行，健康检查随后记录；跨午夜恢复不会把
昨晚目标改成盘前跳过。补记使用 `python -m quant research daily --to YYYY-MM-DD`，
保留真实生成时间及 `delayed_recording`，不算及时执行证据。
已有采集或账户写入时用原脚本 `-To YYYY-MM-DD -WaitForWriter` 等待自然结束；
等待日志列出实际PID，最多两小时，不停止对方。盘前行情回执按内容日期查找补记目录。
补记等待器使用 `scripts/run_daily_observation_backfill.ps1 -To YYYY-MM-DD`，沿用上述日更入口；
超时和异常均写入终态，不把旧 `queued` 当作活跃恢复。完成需目标日的真实日更回执和同日期
市场背景回执，不能以目录存在或脚本退出0代替；原失败日志保留，完整快测失败仍如实返回。
公告单日超过3000条时分沪、深、北读取，并核对唯一ID并集等于原查询总数；不截断或静默去重。
历史失败记录不改写，等待状态不算完成；21:00后仍检查当日执行输入是否完整。

B16保存报价撮合核心：`python -m quant.execution.etf_quote_paper --input <研究输入.json> --output <新目录>`。
输入须声明 `auto_trade=false` 和 `classification=RESEARCH_ONLY`，包含期初账、固定委托、
带供应商/接收时刻的盘口、交易日历及不早于撤单截止的 `as_of`。输出保存输入、模拟成交、
余单及现金持仓；只消费提交后新鲜报价，盘口容量上限1%，同一委托累计最低佣金。
这是模型撮合，不提交真实委托；B16自动接入及验收边界见 [B16前向模拟](operations/B16_FORWARD.md)。
收盘净值复用 `manual_nav` 核验行情和公司行动。股票ETF默认T+1；黄金/国债ETF
支持T+0，不把所有ETF或港股统一视为同一规则。

市场状态已接到现有日更成功节点及原任务08:30盘前触发，只测算上一完整交易日，结果入口为
`artifacts/daily/market_context/latest.json`，包含日期、覆盖率、状态和报告路径。
重复执行校验并复用已完成产物；失败尝试保留。指标计算失败会出现在日更返回值
`market_context` 中，不撤销既有账户产物，不修改仓位。此处是历史收盘状态接入，
不是完整盘中情绪服务，也没有放开当日收盘数据的发布时间要求。
盘前分支独立读取，不占用账户/因子写入槽；要求上一实际交易日的真实数据日更
完成凭证，或独立核验同日刷新、行情完整性与输入检查的 `market_data_completion`。
后一种情形保留日更及信号监测原有未完成状态，`daily_completion` 留空；原日更与
刷新回执均绑定校验值。前向标签不足及账户状态不阻断行情描述，演练或旧数据模式仍拒绝。
盘中报价入口复核同一凭证，变化或缺失即停止该轮。`effective_date` 标明下一交易日，`available_at`
记录本次实际发布时刻，凭证路径与哈希同时保留；不能仅因过了15点视为可用。
安装脚本保留17:30/21:30触发并增加08:30，夜间仍只产出前日背景，盘前补齐最新背景。

`python -m quant.research.market_state_adaptation --output <新目录>` 只读冻结Q10、
压力反转、ETF固定/动态账户，输出新流动性/情绪等滞后状态下的年度切片、完整连续
事件、现金/交易额/费用、市场beta，并复用Q7月度增量IC。
首次持仓由原持仓与BUY成交交叉确认，剔除其前现金期；之后现金保留，纯空仓
事件标不适用。规模代理无已核实收益指数时留空，禁止用低仓位整手账户替代。
不重跑策略、不按状态挑赢家；固定组合净订单回放及全市场实时字段仍须另行完成。

沪深市场参考池盘中快照：`python -m quant data market-snapshot --output <新目录>`。
复用公共行情传输与标准化存储，分批保留昨收、买一、卖一；范围为上一交易日
观察股票池，不含北交所/ETF，不当作已核实上市全量。`--session` 在交易时段每5分钟
采一轮，盘后退出、单实例锁防重复；原实时行情启动脚本同时启动这一只读伴随进程，
不挤占持仓订阅额度，产物在 `artifacts/realtime/market_snapshots/`。
以每轮 `diagnostic/snapshot.json` 的新鲜覆盖率为准，过期/缺失/无效字段不填造；
同钟点历史基线的生成、缓存及缺失口径见 [盘中基线](data/MARKET_CLOCK_BASELINE.md)。
盘中分类映射尚未实现，与输入不足分开报告；日频状态不变。
这不是连续逐笔报价或订单执行行情，缺失逐项记入 `capture_errors.json`。

Q7之外的已保存电池月度IC可用 `python -m quant research factor-family-states --output <新目录>`
生成新状态的因子/族系年度对照。族内先按月平均，不能把相关因子数量当独立样本；
原始和中性化RankIC分别报告，不冒充Q7 partial IC，不重新筛选或改准入。

固定联合账户：`python -m quant research joint-account --output <新目录>`，配置
`configs/research/joint_q10_etf_v1.toml`，复用冻结Q10意向与ETF目标。联合政策将股票预算
限定到股票持仓；每档根据该新账户实际持仓重算，ETF不被当作股票退出。
只用一个事前资本比例，静态ETF、股票加现金及纯股票对照使用相同日期与资金；
不做全样本实现波动匹配。报告包含年度/月度、连续状态事件、实际资产仓位及成本分解。
这是短历史开发回放，不替代正式收益指数准入、人工延迟验证或既有前向账户。

10万元整手/费用构建实验：`python -m quant research joint-integer --output <新目录>`，
固定规则见 `configs/research/joint_integer_v1.toml`。只复用原Q10候选和预测，
不扫持股数量、费用门槛或股债比例；股票按信号收盘固定净股数，ETF保留原执行口径。
输出逐笔 `loss_trace.parquet`、逐信号损耗、价格/行业偏移及三档成本对照，
对照账户必须与冻结旧净值和成交完全一致。缺价格不补零，约束不可行则记录并持有，
不自动降低限制或修改前向账户；股票实际暴露提升不代表新增alpha。

ETF测量复核：`python -m quant research etf-measurement --output <新目录>`，固定配置
`configs/research/etf_measurement_execution_v1.toml`。复用冻结日线账户，核对现金分红总收益、
资产损益与净值，补充年度/月度及连续压力段，并按已有合格历史机械扩展原规则。
读取现有1/5分钟覆盖，逐窗口保存缺失、量额异常及源冲突；不满足全期覆盖时不生成
冒充完整回测的人工延迟净值。`minute_gaps.csv` 为现有补数流程的明确缺口，不自动新建采集任务。
原分钟流水线在数据刷新后同步复查这些ETF窗口，来源不变则复用结果；入口为
`artifacts/research/minute_pipeline/etf_execution/latest.json`，只读存量数据，不消耗新历史采集额度。
连续执行检验用 `python -m quant research etf-delayed-replay --measurement <测量目录> --output <新目录>`：
数量在信号收盘冻结，极值只用于成交压力；1/3分钟共用首个5分钟最不利价格边界。
遇到真正需要交易的缺失/冲突窗口时保存 `partial_nav` 和首个阻塞订单，不把部分净值当完整结果。
原复查流程另存 `source_window_components.csv`（开盘行、常规首5分钟、含开盘首5分钟）、
`source_first_minutes.csv` 和残余冲突，不改严格覆盖标记。经济压力情景可在上条命令加
`--envelope-config configs/research/etf_envelope_stress_v1.toml`，固定取合格源最大买价/最小卖价，
从初始现金重算；报告命令为 `python -m quant research etf-envelope-report --output <压力目录> --windows <窗口目录>`。
包络不代表延迟后能在竞价成交，也不是所有财富路径的严格下界；真正无效窗口仍不可用。

分钟候选电池通过 `python -m quant research minutes` 执行，搜索定义在
`configs/research/minute_search_v1.toml`。按预注册机制与已核实T+0的标的生成候选，
保存全部候选的三档成本、延迟和最不利5分钟价格结果，不按历史排名自动晋级。
已有分钟更新任务和持续挖掘任务会调用同一入口；断点与逐候选报告在
`artifacts/research/minute_pipeline/`。输入不变复用结果，输入变化新建冻结运行，
中断后仅重跑未完成候选。没有有效样本显示缺失，不把零交易当作零风险策略。
新候选前向起点不早于注册次日，旧历史均为开发资料；市场数据缺失时保留提示，
不靠放宽数据检查制造研究结果。此电池有限，不无限生成同源参数网格，也不调用LLM。

后续独立机制批次通过 `minute_pipeline.toml` 的 `additional_searches` 接入；
当前包含固定隔夜跳空信息电池。每次回放同时输出 `pnl_diagnosis.json/md`，
按保存的成交份额分解区间价格变动、不利成交价与滑点、手续费，逐笔核对净盈亏；
此分解不是零成本账户，也不用于选择历史最优参数。无有效数据的候选保留为空。
日内成本不合算时同步推进低频执行验证：
`python -m quant research etf-execution-stress --output artifacts/research/<新目录>`
读取B16固定历史委托和已覆盖开盘5分钟窗口，报告缺失、容量提示和价格压力差额，
不将不完整窗口诊断当作完整延迟净值或正式策略准入。

ETF 人工延迟账户：初始化 `python -m quant research etf-manual-init`；
运行、报价探测、收盘恢复和证据入口见 [B16前向模拟](operations/B16_FORWARD.md)。
历史 `bootstrap.json` 保留初始化事实，当前进度读取 `service_status.json`、
`daily_status.json` 及逐日成交/对账文件；现金初始化不算策略表现。

| 做什么 | 命令 |
|---|---|
| 日更只读检查 | `python -m quant research daily --check-only` |
| 日更 | `.\scripts\run_daily_observation.ps1` |
| 持续挖因子 | `.\scripts\run_continuous_mining.ps1` |
| 扫描论文/开源 | `python -m quant intel scan`（`--no-extract` 不花 LLM） |
| 发一条通知 | `python -m quant notify test` |
| 排行榜 | `python -m quant report leaderboard` |
| 本地投研看板 | `python -m quant report dashboard --port 8769`；已安装登录任务时自动恢复，不要重复启动 |
| 挖掘状态 | `.\scripts\show_factor_mining_status.ps1` |
| 盘中行情延时小样本复测 | `python -m quant data latency`；只读请求，结果在 `artifacts/realtime/latency_*/`，分开显示冷启动、热调用和供应商时间戳年龄 |
| 分钟策略开发回放 | `python -m quant research intraday-afternoon --output artifacts/research/<新目录>`；冻结配置、输入哈希、逐日质量及三档成本/人工延迟回放，不发实盘订单 |

计划任务安装：`.\scripts\install_daily_observation.ps1`、`.\scripts\register_continuous_mining.ps1`、`.\scripts\register_research_dashboard.ps1`。电脑须开机且用户登录；看板地址 `http://127.0.0.1:8769`。

看板顶部导航分为运行总览、数据获取、策略曲线、模拟账户、研究结果，支持链接直达和浏览器前进/后退。行情覆盖和曲线在首次进入对应页时加载；总览使用独立轻量缓存，不等待研究结果分组。研究结果每页 30 组，搜索、结论筛选及排序作用于全部记录，切页保留筛选。定时刷新仅在当前标签可见时执行：总览/账户 20 秒、结果 60 秒；顶部按钮只刷新当前页。

## 凭据

全部 `*.local.toml` / 环境变量，不进 Git。

| 用途 | 位置 |
|---|---|
| Tushare | `configs/tushare.local.toml` |
| DeepSeek | `DEEPSEEK_API_KEY` 或 `configs/deepseek.local.toml` |
| SMTP | `SMTP_HOST` / `SMTP_FROM` / `SMTP_TO` / `SMTP_PASSWORD` |
| 企微 / 飞书 | `WECOM_WEBHOOK` / `FEISHU_WEBHOOK` |
| 微信 | `WXAUTO_GROUP`，需解锁桌面；可选依赖 `pip install -e ".[wechat]"` |

`configs/notify.toml` 的 `channels` 配好后，日更/挖掘失败会真发消息；未配则写入 `artifacts/notify/outbox.jsonl`。

## 证据位置

`python -m quant doctor --no-notify` 会在原报告中追加当前工作清单的已观测进度：指定实验的注册表、冻结配置 SHA、三档结果与报告对应关系，R3 条件区间，以及已发布结构化表的实际行数和日期。产物仍在 `artifacts/doctor/`；本节不代替完整验收。11-15 与 12-01 日期未到时不宣告通过，11-27 预演、11-30 及时订单、12-01 月报及费用对应产物仍须逐项核对自然执行证据。

| 问题 | 看哪里 |
|---|---|
| 日更 | `artifacts/daily/sue_v2/`、`artifacts/daily/scheduler/` |
| Q10 前向 | `artifacts/paper/q10_sue_v2/` |
| 持续挖掘 | `artifacts/research/continuous/status.json`、各 `batch_*/digest.md` |
| 情报周报 | `artifacts/intel/<ISO周>/digest.md` |
| 实验数字 | `artifacts/registry/experiments.parquet`、[排行榜](research/排行榜.md) |

## 恢复

持续挖掘会区分失败类别：网络超时/连接错误及 Windows 32/33 文件占用采用指数退避，
默认1小时起、最长24小时，最多8次；未知错误或定义/数据问题保留原3次上限。
达到上限后，数据/因子/研究代码指纹变化可触发一次受控试运行，旧失败记录先归档到
对应批次 `recovery/auto_*.json`；同一代码版本不会反复解除暂停。
这只恢复原断点，不跳过失败批次、不改冻结候选、不放宽数据或准入检查。
状态包含失败类别、重试上限及下一次允许时间；状态文件写入同时处理短暂Windows读锁。
升级不强行重启正在工作的进程，下次调度加载新逻辑。

先确认 Python 进程已结束。持续挖掘自动从 GP 种群与 `N4/admission_progress.json` 恢复。不要删断点、不要改冻结配置冒充同一次 run。日更与挖掘互斥，工作日 17:20/21:20 挖掘让路。

分钟/ BaoStock 补采与持续挖掘互斥写 clean bar：对方在跑时调度记 `deferred` 不失败；冻结源变化时保留原上下文和断点，按下述输入失效流程处理，不能重钉后沿用原适应度。

## GPU

默认 CPU。要加速时：`$env:QUANT_DEVICE='auto'` 或改 `configs/runtime.toml`。`python -m quant gpu-check --refresh` 查看本机 OpenCL 是否可用。

## 研究反馈

详见[研究反馈与挖掘运行](OPERATIONS_RESEARCH.md)。

## 数据获取看板与手动同步

本地看板 `http://127.0.0.1:8769/#dataAcquisition` 按来源、K线级别列出实际 Parquet 记录日期边界和去重标的数。扫描在后台运行，缓存每五分钟增量检查；页面显示统计时间、扫描进度及读取失败数，也可手动刷新。当前统计包含 TDX、Futu、已有公开源分钟、当前 Tushare 日线快照与日更分区，不计复权因子表。日期边界不证明逐交易日连续完整。

展开“1 分钟标的列表”可搜索代码/名称/来源、筛选和导出 CSV。“已补齐计划年份”仅表示从已探测 Futu 最早年份到配置结束年份均有非空年度分区；尚未核验逐日缺口。最新日期单独显示，允许由 TDX 等近期源补足。

“手动同步”调用已有 Windows 任务：近期分钟、Futu 历史、原有日更或盘中行情；组合选项触发前三项。运行中任务不重复启动，缺失/禁用任务显示失败。原有日更包含模型与模拟账本更新，保留写入互斥。Futu 历史任务把约 100 标的滚动额度**全部**用于全市场缺年回填（尽早起点、从早到晚下载，不预留额度；当日/近期分钟不走 Futu 历史接口，见 [MINUTE_REFRESH.md](data/MINUTE_REFRESH.md)）；仍受单轮时间预算约束；`auto_trade=false`。请求提交不表示采集完成，任务状态、下次触发时间和采集进度分别展示。按钮仅接受本地同源带令牌的固定任务操作。

覆盖缓存与验证：`artifacts/dashboard_data/inventory.json`、`file_index.json`、`tests.xml`、`validation.json`；缓存为派生统计，不覆盖 raw。

## 研究流水线补充说明

研究反馈：`python -m quant research feedback` 汇总已完成电池的失败、家族、衰减与基准缺口；下一次持续调度自动更新，新周度候选使用该反馈。研究目标与准入门槛分开，详见 [研究协议](RESEARCH_PROTOCOL.md)。

新建因子评估流水线在成本回放前核对全历史排序、缺失位置及方向，对同批次等价信号复用完成的回放，独立统计检验与准入结论保留。流水线报告记录复用数量与节省的版本×成本回放数，因子目录的 `reuse.json` 保留来源和文件校验。中断后从原目录恢复；旧批次沿用原执行方式。

已注册的一轮跨股票样本搜索见 `configs/research/gp_cross_stock_v1.toml`：当前未完成批次之后，调度只创建一个采用三组各300只股票的新批次，以最弱组IC评分；恢复时使用原样本及冻结目标。三组都用于训练，历史对照不冒充独立验证；正式准入仍走原电池与三档成本。

## 09-19 优化工作计划与验收记录


按下表顺序交付；不打断冻结批次和日更。测试通过只证明对应行为，跨月、时间片、登录和实际成交仍分别等待生产证据。

|顺序|工作|验收条件|状态|
|---|---|---|---|
|1|跨月输入与月度衔接|新批次补齐当月执行/基准输入；恢复按当前日期触发月度任务，已冻结输入不漂移；准入读取同截止日完整参考表|代码与回归完成；8月输入实查无缺项，10月跨月生产验证待到期|
|2|时间片平稳收尾|截止前停止领取新计算单元，保留年度/代际断点；正常让出时间片不累计为计算失败，硬超时保护保留|年度/成本档、GP代际及N4候选边界已接入；中断续跑与一次跑完一致性测试通过；新批次生产跨片待观察|
|3|日更分步进度|展示当前数据子步骤、最近进展和等待原因；失败不显示为完成|已接入输入子步骤与分钟请求计数，失败保留；下次日更生产展示待观察|
|4|跨批基准复用|只有目标、区间、执行输入和费用完全相同时复用完整结果；输入变化失效，部分结果不复用|内容校验与回归完成；生产13–17批记录复用30组基准回放，另去重省12组成本回放；凭据见 `artifacts/maintenance/forward_scoring_delivery_20260920/production_reuse.json`，未测壁钟提速|
|5|看板响应|慢状态刷新不阻塞健康检查；并发请求只启动一次刷新，明确缓存时间|并发刷新及净值分组持久缓存已部署；重启后首个状态请求9.185秒、并发健康0.041秒，552条分组注释一致；无缓存完整核验仍约44秒。32项回归通过，证据 `artifacts/maintenance/dashboard_cold_start_20260919/`|
|6|预测优先搜索与前向留存|冻结机制与停止条件，预测优先、近似时比较相关性；已见历史仅作开发证据，不改准入门槛|第12批1392试验、25定义：2准入/23拒绝；诊断见 `artifacts/research/batch12_diagnosis_20260920/`。冻结留存及成熟月度评分已接入日更，验证见 `artifacts/maintenance/forward_scoring_delivery_20260920/`。首个合格日9/21；月末标签最早11/2成熟，前向收益与组合增益待验证|
|7|准入计算内存|增量检验只搬运所需列，数值、缺失掩码及恢复行为不变；全部参考相关性仍计算|入口投影及39项回归通过，证据 `artifacts/maintenance/n4_projection_20260920/`；生产提速待观察|

首批优化208项测试见 `artifacts/maintenance/automation_optimization_20260919/`；并行推进137项测试及5定义隔离摄取见 `artifacts/maintenance/parallel_delivery_20260919/verification.json`。运行说明同步 `docs/OPERATIONS.md`；第11批完整结束，新开关仅用于后续批次。测试节省量不能算作生产收益或准入证据。

## 分钟策略自动研究

`python -m quant research minutes` 按 `configs/research/minute_pipeline.toml` 执行已注册策略。既有分钟补数任务结束后、持续挖掘领取新时间片前会自动调用；不另建调度任务，不启动重复因子批次。机器须开机且原计划任务可运行；恢复后从下一次原任务调用接续。

当前接入黄金ETF午后趋势原型。先冻结配置、1m/5m数据、日历和代码哈希，再完成逐日质量、跨频率核对、三档成本和两档人工延迟回放。数据或代码不变且产物完整则复用；变化则创建新快照。中断只重做未完成的小回放，已完成策略跳过；不覆盖旧尝试。运行文件锁防止两个入口同时回放。

状态 `artifacts/research/minute_pipeline/status.json`；汇总 `report.md`，每个策略有独立冻结输入、质量CSV和逐日回放。`complete`只表示运行完成，另看 `data_stale`、连续有效交易日及 `attention`。缺失不填零，不自动调参、晋级、发送交易信号或改变模拟账户。连续数据、收益指数基准、退出容量与独立前向仍须验证。分钟研究失败记录状态和日志，不阻断原因子挖掘；补数失败仍保留原退出码。

`python -m quant research mechanisms --output artifacts/research/<新目录>` 消费已受理压力反转电池与B13/B16/B48冻结产物，复算逐折交易换手、共同日期相关性和B20最新账户对账。保留原准入判定；扣除初始建仓的换手仅作解释，不拼接折间收益。分钟自动报告另输出 `quality_issues.csv`、`diagnosis.json`，定位非正成交量、量额隐含价、时段与跨频率问题，并按人工延迟统计退出容量警告；不自动放宽校验。

`python -m quant research allocation-attribution --output <新目录>` 执行已冻结的B16动态规则与起点前固定权重连续账户对照（10万元、三档成本）；`python -m quant research mechanism-detail --allocation <该回放目录> --output <新目录>` 输出反转失效拆解、财务机制已保存前向覆盖、同日期Q10降仓解释性基线及年/月指标。降仓基线不是合并订单账户，不计未模拟的再平衡成本；历史对照不改原B16拒绝和B20前向终点。
