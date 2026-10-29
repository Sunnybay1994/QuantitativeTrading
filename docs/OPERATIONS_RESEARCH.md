# 研究反馈与挖掘运行

[返回运维入口](OPERATIONS.md#研究反馈)

冻结GP输入的 checksum、文件消失或源清单变化归为 `frozen_inputs_invalidated`，
不按网络瞬断重试，也不作为因子经济失败。`N2/frozen_input_failure.json` 记录清单哈希，
原输入、种群与适应度检查点原地保留；代码变化不自动放行。
恢复原字节后，下一次调度逐一核对原清单及其源文件再续跑；仅更新清单哈希不能恢复。
目录清单变化或无法恢复原字节须另核实，并以独立批次承接稳定输入，不改写原批结果。
证据绑定的 `input_invalidation.json` 将输入失效批次从续跑队列移出，原汇总不改成完成，
也不进入零通过率统计。下一自然调度创建独立新批，不接续其种群或适应度。
新GP上下文需要分钟输入时，将首次选中的Bao/TDX五分钟文件及缺失范围固定到
`full_context/minute_inputs/`；同盘使用硬链接，跨盘复制，恢复时核对快照内容哈希。
采集器原子替换及新增文件不会改变该快照；快照损坏直接报错，不从新行情补写。
该读取政策进入计算契约，旧缓存不能通过重写输入身份迁入新契约。

后续独立GP批次使用 `published_terminal_boundary_v1`：训练和N3均保留已发布终端边界，
新增横截面节点由同一全市场读取路径计算，训练回执保存实际终端表达式的值。
旧批次不热切换。经核实的计算路径缺陷由证据哈希绑定的 `N2/computation_invalidation.json`
标为 `INVALID_COMPUTATION`，下一自然边界只跳过该GP阶段及其产物，原候选电池继续。
这不计作策略失败；原检查点和指标保留，独立新批次不移植原种群或适应度。

已有候选排队时，后续时间片优先完成原N3电池及N4准入，再续跑N2，避免GP长任务
持续占满时间片。到期月度前置工作仍优先；当前活跃进程不热切换顺序。
GP在非空电池完成后新产出的候选保留到原processing队列，由下一独立批次受理，
不把它们插进已完成电池，也不改写其冻结结果。每次实际顺序写在汇总的step_order中。

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


## 临时采集窗口与启动探针

`artifacts/research/continuous/data_window.json` 的 `starts_at`、`expires_at` 限定临时采集窗口，时长须大于零且不超过四小时；只影响后续启动，不终止活跃进程。窗口开始前缩短研究时间片，窗口内让路，到期后恢复原调度。

`powershell -NoProfile -File scripts/run_continuous_mining.ps1 -CheckOnly` 只读取窗口和进程状态，不启动研究、采集或通知，不创建运行目录或改写调度回执。
