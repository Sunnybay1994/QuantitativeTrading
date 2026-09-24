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

## 日常命令

含 Q10 的完整日更与其数据可得时间保持一致：21:00 前的触发只记录
`deferred` 和最早可运行时刻，不启动整套日更、不误报失败；由既有21:30触发执行。
因此该配置下17:30不再生成全套模型/账户日更。独立数据更新任务不受影响。
历史失败记录不改写，等待状态不算完成；21:00后仍检查当日执行输入是否完整。

B16保存报价撮合核心：`python -m quant.execution.etf_quote_paper --input <研究输入.json> --output <新目录>`。
输入须声明 `auto_trade=false` 和 `classification=RESEARCH_ONLY`，包含期初账、固定委托、
带供应商/接收时刻的盘口、交易日历及不早于撤单截止的 `as_of`。输出保存输入、模拟成交、
余单及现金持仓；只消费提交后新鲜报价，盘口容量上限1%，同一委托累计最低佣金。
这是模型撮合，不提交真实委托，不代表已接入实时采集或B16定时执行；收盘净值继续使用
既有 `manual_nav` 核验行情和公司行动。股票ETF默认T+1；账本显式配置的黄金/国债ETF
支持T+0，不把所有ETF或港股统一视为同一规则。

市场状态已接到现有日更成功节点及原任务08:30盘前触发，只测算上一完整交易日，结果入口为
`artifacts/daily/market_context/latest.json`，包含日期、覆盖率、状态和报告路径。
重复执行校验并复用已完成产物；失败尝试保留。指标计算失败会出现在日更返回值
`market_context` 中，不撤销既有账户产物，不修改仓位。此处是历史收盘状态接入，
不是完整盘中情绪服务，也没有放开当日收盘数据的发布时间要求。
盘前分支独立读取，不占用账户/因子写入槽；要求上一实际交易日的真实数据日更
完成凭证，拒绝演练或旧数据模式。`effective_date` 标明下一交易日，`available_at`
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
尚无同钟历史成交额基线时，盘中状态仍unknown，收盘状态与盘中指标分开显示。
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

ETF 人工延迟研究现金账户初始化：`python -m quant research etf-manual-init`。
冻结配置为 `configs/research/b16_manual_forward_v1.toml`，账户位于
`artifacts/paper/b16_manual_v1/`。120 秒主账、60 秒影子及三档成本各自隔离；
重复执行不会重置账户。这只是现金初始化，不会发送交易消息、产生模拟成交或
自动接入日更。首期月末信号前还需完成提交后报价撮合、部分成交费用、顺序现金
校验和端到端验收；`bootstrap.json` 明确列出未完成项。不得将现金期零收益用作
策略表现，也不得把现有 B20 开盘成交净值当作人工延迟账户。

| 做什么 | 命令 |
|---|---|
| 日更只读检查 | `python -m quant research daily --check-only` |
| 日更 | `.\scripts\run_daily_observation.ps1` |
| 持续挖因子 | `.\scripts\run_continuous_mining.ps1` |
| 扫描论文/开源 | `python -m quant intel scan`（`--no-extract` 不花 LLM） |
| 发一条通知 | `python -m quant notify test` |
| 排行榜 | `python -m quant report leaderboard` |
| 本地投研看板 | `python -m quant report dashboard --port 8768`；已安装登录任务时自动恢复，不要重复启动 |
| 挖掘状态 | `.\scripts\show_factor_mining_status.ps1` |
| 盘中行情延时小样本复测 | `python -m quant data latency`；只读请求，结果在 `artifacts/realtime/latency_*/`，分开显示冷启动、热调用和供应商时间戳年龄 |
| 分钟策略开发回放 | `python -m quant research intraday-afternoon --output artifacts/research/<新目录>`；冻结配置、输入哈希、逐日质量及三档成本/人工延迟回放，不发实盘订单 |

计划任务安装：`.\scripts\install_daily_observation.ps1`、`.\scripts\register_continuous_mining.ps1`、`.\scripts\register_research_dashboard.ps1`。电脑须开机且用户登录；看板地址 `http://127.0.0.1:8768`。

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

## GPU

默认 CPU。要加速时：`$env:QUANT_DEVICE='auto'` 或改 `configs/runtime.toml`。`python -m quant gpu-check --refresh` 查看本机 OpenCL 是否可用。

## 研究反馈

`python -m quant research feedback` 只读取已保存电池并更新 `artifacts/research/feedback/feedback.json`，不回测、不调用 LLM。持续挖掘下一次进程启动后，每轮结束自动刷新；新周度候选请求读取最近三批反馈及 `configs/research/research_priorities.toml`。已有周度请求、运行批次和 GP 断点保持冻结，因此当前运行进程不会热加载这次代码修改。DeepSeek 原闲时窗口与周/月预算保持有效；反馈异常写入挖掘状态，不阻断已完成的本地研究。

`python -m quant research batch-diagnosis --run <已完成批次目录> --run <另一批次目录> --output <新目录>` 复算保存的训练/电池分数、统计失败与成本敏感性，不重新回测。第9批的最弱组目标与总体训练IC分别解释；已观察历史不是独立测试。

N4增量检验仅向分组与回归传递键、标签、候选及已准入控制列；其余原库列仍由最大相关性检验使用，不删控制、不变更缺失掩码或门槛。合成宽表等值和内存对照位于 `artifacts/maintenance/n4_projection_20260920/`，合成测量不代表生产提速。

`python -m quant research reversal-readiness --output <新目录>` 按 `configs/research/pressure_reversal_v1.toml` 抽查量价反转输入，保存实际刷新配置、行业源哈希与机器报告。只检查输入，不读未来收益、不入队、不回放账户；抽样月份与表达式文本去重不能替代完整历史覆盖和信号等价检查，量价代理不能证明没有消息影响。

追加 `--full-history` 检查完整历史并保存逐年断点、月末信号及原电池股票池；中断后用同一输出目录加 `--resume`，源输入或完成文件变化会拒绝混用。输入足够月份不是有效IC月份，未来标签覆盖仍由正式电池检验。两候选及三个控制已由09-20第12批N1受理，来源标为`registered_battery`，受理不等于评估完成。`artifacts/research/pressure_reversal_full_history_20260919_02/queue_submission.json`保留检查与入队凭据；096/097两个旧因子因共同有效样本不足仍无法判定等价，不据此宣称新机制或复用成本回放。

看板策略曲线下提供年/月指标、基准选择、资金标注、策略说明和 HTML 报告下载。下载使用当前策略、日期筛选、成本档与表格所选基准。自动生成的模型报告链接到 `periods/`，月度明细按年拆分；空仓初始化期排除，不把部分年/月当完整期间。资金回放入口拒绝 10 万、100 万以外或重复档位；修改后的 R8 配置必须使用新输出目录，不能接续旧多资金档运行。

看板“当前流水线 → 重启投研 / 从断点恢复”触发现有 Windows ContinuousMining 计划任务，运行中不重复启动，不强杀进程、不清空断点、不重置失败计数。仍遵守日更避让与写入互斥；“已请求”不等于已运行，须看实际进程和批次状态。控制接口仅接受本地同源、带页面令牌的 POST。

每日观察的 `complete` 表示流程执行完成，影子滑点 `partial` 则表示报价窗口仍有缺口；看板会显示具体数量与处理事项。影子价格不是实际成交，缺失数据不能按零滑点处理，也不是下单通知。

日更 `forward_tracking.tdx_recovery_root` 启用本地ETF量额恢复：仅处理已完成交易日的保存订单，按开盘5/15/30分钟分别校验连续分钟、量额隐含价及至少80%的跨源分钟收盘价；仅采用从最短窗口起连续通过的范围，失败保留缺口。全天质量另行记录，不将窗口通过视为整天合格。通过后原始快照保存在当次 `forward_tracking/raw_tdx/`，逐日来源和失败原因见 `minute_recovery.json`，不改共享分钟库、不联网、不覆盖历史报告。影子价格仍不是实际成交。

恢复证据可用 `python -m quant research recovery-audit --file-baseline <恢复前文件哈希清单.json> --output <新报告.json>` 比对。输出分别记录文件内容、修改时间及读取中变化；文件相同不能单独证明自动续跑或排除相同内容重写，需另查新进程与同批次后续产物。不带 `--file-baseline` 时保留历史调度与净值日期核查。

09-19自动化优化：新冻结配置启用 `prepare_month_inputs=true`，N3首次建批时复用月度输入补齐；恢复旧批次不会重新冻结执行快照。N5按当前调度日期检查到期月份，保留旧跳过记录；准入只能采用同截止日的完整月度参考表。若旧批次已达失败上限，新到期月份只有一次恢复机会，仍失败则继续保留上限，不无限重试。

新冻结配置的 `slice_checkpoint_seconds=180` 在硬截止前预留收尾时间。GP代际、年度/成本档账户及N4候选边界可主动让出时间片，退出码75记录为可恢复，不累加失败；已有冻结批次保留原时间片规则。单个计算单元超过预留时间时仍由原硬截止保护，不保证任意位置零重算。

日更 `model/refresh_progress.json` 原子记录输入子步骤、时间和分钟请求计数；失败次数与完成请求数分别展示，更新时间不证明进程存活。看板并发处理请求，状态刷新合并并发请求，缓存时间和刷新失败可见。

新电池的 `pipeline_config.json` 记录 `benchmark_reuse=true`；跨批基准缓存按目标、会话日期、执行数据内容、费用和回放代码校验，仅复用完整三档成本结果。缓存索引在电池集合的 `benchmark_cache/`，每批 `benchmarks/benchmark_reuse.json` 记录来源及节省数量；损坏/不匹配缓存不命中，旧冻结流水线不切换模式。代码改动或输入变更可能导致保守失效，不能把测试复用数当作生产节省量。

`configs/research/gp_predictive_priority_v2.toml` 已接入后续新批次，一次后恢复原默认搜索；当前冻结批次不改。候选须实际引用清单中的机制终端，按三组最弱方向调整IC排序，每选一个候选重建剩余最高值的0.001带，再比较相关性及复杂度。此规则同时用于父代、精英与最终输出；报告分别展示主指标及相关性，不虚构单一适应度。原电池、三档成本及准入门槛不变，三组均属训练，已观察历史仅作开发证据。

机制清单在 `configs/research/gp_predictive_priority_v2_inputs/manifest.json`，来源按哈希分片冻结。`python -m quant research predictive-inputs --manifest configs/research/gp_predictive_priority_v2_inputs/manifest.json --output <新目录>` 只准备和校验训练输入，不启动搜索。当前配方复用 `artifacts/research/gp_predictive_priority_v2_preflight_20260919/`；须保留其中 `prepared_inputs.json` 和其列出的全部文件。新N2复制冻结数据，恢复时核对数据、标签、控制、分组、表达式及目标，变化则拒绝混用；日线预热值和行业亦纳入断点指纹。完整历史覆盖见 `artifacts/research/gp_predictive_priority_v2_inputs_20260919/`，真实复制/恢复及测试见 `artifacts/maintenance/gp_predictive_priority_20260919/`。旧财务分区缺少逐分区原始快照沿革，当前刷新配置仅作背景，不冒充历史修订版本审计；冻结缓存不是对历史PIT准确性的独立证明。

预测优先搜索完成后保存 `candidate_freeze.json`：记录实际UTC时间、候选表达式/方向及源文件哈希；相同结果恢复沿用原时间，来源变化报错。第12批的实际冻结凭据另存于 `artifacts/research/predictive_priority_batch12_20260920/`，现有N2产物不改写。日更配置的 `[candidate_forward]` 已接入这20个候选，首个合格信号日由交易日历判定为2026-09-21；从此日期的17点后、下一交易日9:30前保存当时可见的原始信号。错过开盘的补跑明确标记 `missed_window`，不冒充前向证据；日更其他账户仍独立执行。

每次日更的 `candidate_forward/` 保存输入切片、原始值、同日合格股票池、冻结方向、刷新及财务披露记录和文件哈希，沿用既有原始terminal与电池股票池，不增加抓取、交易或准入门槛。缺失和非有限值不填零，财务未解决披露仍保留；输入质量通过不证明全部财务修订完整。`captured` 仅表示按时留存信号，尚不是收益或准入结论。日更已接入 `candidate_scoring/`：从配置 roots 读取同日最早完整捕获，核验哈希、时间和固定测量口径；当日捕获失败也继续评分既有记录。仅月末信号的下一开盘至次月末下一开盘标签成熟后计算 raw/neutral RankIC，缺失价格不跳日、不填零。保存端点价格、标签、分数和配置；pending 表示尚未成熟，错误进入每日提示。当前20候选尚无前向捕获；本地日历首个月末9/30，持有10/8至11/2，不能提前宣称收益。验证见 `artifacts/maintenance/forward_scoring_delivery_20260920/`；历史数值对照仍见 `artifacts/maintenance/candidate_forward_20260920/`。

看板已验证的净值分组缓存保存在 `artifacts/reports/dashboard/result_groups.json`，包括版本、注册表键及所有来源文件身份、大小、修改时间。服务重启可复用；来源变化、缺失或缓存损坏触发完整重算，写缓存失败不阻断已核验结果。此为已完成且不应改写的报告派生缓存，不用于回测或准入；首次无缓存全量核验仍较慢，后续状态刷新仍展示真实缓存时间。

## 数据获取看板与手动同步

本地看板 `http://127.0.0.1:8768/#dataAcquisition` 按来源、K线级别列出实际 Parquet 记录日期边界和去重标的数。扫描在后台运行，缓存每五分钟增量检查；页面显示统计时间、扫描进度及读取失败数，也可手动刷新。当前统计包含 TDX、Futu、已有公开源分钟、当前 Tushare 日线快照与日更分区，不计复权因子表。日期边界不证明逐交易日连续完整。

展开“1 分钟标的列表”可搜索代码/名称/来源、筛选和导出 CSV。“已补齐计划年份”仅表示从已探测 Futu 最早年份到配置结束年份均有非空年度分区；尚未核验逐日缺口。最新日期单独显示，允许由 TDX 等近期源补足。

“手动同步”调用已有 Windows 任务：近期分钟、Futu 历史、原有日更或盘中行情；组合选项触发前三项。运行中任务不重复启动，缺失/禁用任务显示失败。原有日更包含模型与模拟账本更新，保留写入互斥；Futu 历史保留额度和时间预算；`auto_trade=false`。请求提交不表示采集完成，任务状态、下次触发时间和采集进度分别展示。按钮仅接受本地同源带令牌的固定任务操作。

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
