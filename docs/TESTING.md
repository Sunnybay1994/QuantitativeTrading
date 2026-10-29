# 测试执行

日更的快测试命令是 `python -m pytest tests -q -m "not slow"`。`quant doctor --record-tests` 将其限制为 600 秒，保留输出日志和退出码；超时或失败都不能记为通过。

`tests/integration/test_m3_*.py` 重建完整 M3 数据、模型、模拟成交及验收链路，统一标记为 `slow`。`tests/full_chain_cases.py` 另列出位于 unit 目录、实际构建或消费完整上游工件链的具体函数；只给这些函数加标记，纯计算、类型、边界和前置拒绝测试继续留在快集合。无筛选的 `python -m pytest tests` 继续执行全部测试，测试函数及断言保持不变。

分类依据保存在 `artifacts/worklog/fast_suite_diagnosis_20261029/attempt_base_stream_1/timing_summary.json`：完整快集合在 600.62 秒超时；评估闭环单例剖析约 100 秒，读取 315 次开发样例 parquet，并多次验证折叠、特征、对齐、模型及预测工件。多次篡改与恢复的评估用例约 218 秒。它们的全链验证保持完整，按慢回归计划运行；分类本身不构成快测试通过证据。

慢回归单独执行：在 M3 相关代码、依赖、解释器或固定工具变化后，用该链路固定的 Windows 解释器 `D:\Miniforge3\envs\m3chain312\python.exe` 运行 `-m pytest tests -m slow --durations=20 --junitxml=<独立测试目录>/slow.xml`。它不在日更中串行执行；安排在没有生产研究写入者的独立测试时段，使用临时数据和产物目录，并保留完整结果。

正式 PAPER 启动的四个完整运行时用例也标为 slow；同模块的 BOM 前置拒绝和路径规则 AST 检查仍在快集合。该启动链沿用既有 base 解释器 `D:\Miniforge3\python.exe`，单独运行 `-m pytest tests/integration/test_paper_formal_bootstrap.py -m slow --junitxml=<独立测试目录>/paper-bootstrap.xml`。M3 慢回归命令加入 `--ignore=tests/integration/test_paper_formal_bootstrap.py --ignore=tests/unit/test_m3_g1_candidate.py --ignore=tests/unit/test_m3_g1_candidate_actions.py --ignore=tests/unit/test_m3_g1_workflow.py --ignore=tests/unit/test_m3_reference_contracts.py`，这些文件各自使用本页的 base 命令，保持原有组件运行时。PAPER 启动测试的 basetemp 须满足原模块的同卷、实际代码目录外、非系统临时目录约束；隔离源码副本可使用其相邻的临时目录，不 patch 路径权威函数。

快测试通过不代表慢回归通过。未跑完的慢回归保持未验证，不用测试标记、部分通过数或超时回执替代。禁止仅为消除红项而扩大慢测试范围；新增标记应有实测耗时或完整链路重建的依据。

G1 构造器与审计的单元测试读取 `tests/fixtures/g1_candidate` 中由真实构建器生成的纯合成固定表；保留 300 只标的、14 张表和全部输入回执。加载器逐文件核对摘要，并调用真实 `G1Candidate` 构造器复核表、回执、必需键和主身份；不 mock 校验器，也不在运行时缓存构建结果。重新签名的篡改表仍须被真实身份验证拒绝。

完整构建及重建验证仍在 `test_m3_g1_candidate.py` / `test_m3_g1_candidate_actions.py` 中，以函数名逐项标记为 slow；前置拒绝测试继续留在快集合。用既有 base 解释器单独执行 `python -m pytest tests/unit/test_m3_g1_candidate.py tests/unit/test_m3_g1_candidate_actions.py -m slow --junitxml=<独立目录>/g1-build.xml`。其中正向构建回归会从全部原始合成响应重建，并与固定候选逐表、逐回执和身份对比。

需要更新固定表时，显式运行 `python -m tests.support.build_g1_candidate_fixture --output artifacts/tmp/g1-new`，选择尚不存在的新目录，审阅与固定表的差异后再提交。普通测试不会自动重建或更新基准；`manifest.json` 保存生成耗时、种群数、源摘要与文件摘要。此数据仅为测试夹具，不是生产采集或研究结果。

正式模型、预测、目标、回测计划和研究汇总的测试，有些会通过跨模块 `_context` 重建特征、折叠、对齐、模型及各级回执。`tests/full_chain_cases.py` 按函数名补齐这些完整链路，并保留单独的 ICIR 数学、排序、类型、发布锁及原生 LightGBM 小样本测试。G1 的 INDEX→HISTORY 持久化断点续跑回归也单独列出；其他 G1 前置校验不因此被排除。

边界审计位于 `artifacts/worklog/formal_chain_boundaries_20261029/`：逐函数记录构建依赖和源摘要，收集清单核对默认用例及参数不变。正式工件链沿用上文 M3 固定解释器慢回归命令；G1 工作流用既有 base 解释器单独运行 `python -m pytest tests/unit/test_m3_g1_workflow.py -m slow --junitxml=<独立目录>/g1-workflow.xml`。两者均使用独立源码/临时产物目录，并在没有生产研究写入者的时段执行。标记与收集审计不代表这些回归已全部通过。

跨源参考核对测试使用 `tests/fixtures/g1_reference_candidate` 的固定合成 G1 表；共享 factory/fixture 仍保留在 `test_m3_reference.py`，原核对用例拆到 `test_m3_reference_contracts.py` 与 `test_m3_reference_reconcile.py`。参考样本的真实核对、容差、稳定摘要和零 IO 断言不变。新增的 `test_reference_fixed_candidate_matches_fresh_full_builder` 用原始合成响应重新构建并对比全部表、输入回执与身份，沿用 base 解释器执行 `python -m pytest tests/unit/test_m3_reference_contracts.py -m slow --junitxml=<独立目录>/reference-g1.xml`。

参考固定表的显式生成命令为 `python -m tests.support.build_g1_candidate_fixture --kind reference --output artifacts/tmp/reference-new`，输出目录必须尚不存在。普通核对测试仍调用真实候选构造器校验，固定表不会自动更新；输入 factory 或构建器变化时须执行上述完整重建对比。

正式 G7E/G7F 模拟和三档回测的 `_case` / `_formal_case` 会通过 `_fresh_context` 重建完整目标、模型和预测上游；这些闭环按具体函数进入 M3 慢回归。净值投影、成本缩放、残余意图计数、卖出价格取整及严格上下文类型测试继续留在快集合。质量门完整源码发布、恢复和失败回滚也进入 M3 慢回归，独立导入隔离和环境清理仍为快测试。

G1 发布模块中实际调用 `prepare_g1_release`、`publish_g1_release` 或依赖完整 `prepared` 夹具的测试单列慢回归，仍保留真实候选重建、跨源核对、发布、篡改和原子写入验证。使用既有 base 解释器运行 `python -m pytest tests/unit/test_m3_g1_release.py -m slow --junitxml=<独立目录>/g1-release.xml`；上文 M3 慢回归命令另加入 `--ignore=tests/unit/test_m3_g1_release.py`。不调用完整发布链的输入、列锁、严格 manifest、原生文件系统能力和无重命名回退测试继续留在快集合。依赖审计和默认收集范围对照位于 `artifacts/worklog/remaining_chain_boundaries_20261029/`；本次分类不代表慢回归已经通过。

G1 工作流的完整 INDEX 持久化后复用，以及 INDEX→HISTORY→REFERENCE→PREPARE→PUBLISH 五阶段发布并检查闭环，与既有 HISTORY 断点续跑一起按函数名进入 base 慢回归命令。即使供应商响应是合成的，这些用例仍执行真实请求规划、回执落盘和重建核验；原用例及断言保留。新鲜状态检查、缺少 INDEX 的前置拒绝和连接器字段契约继续留在快集合。审计与线程资源实测保存在 `artifacts/worklog/workflow_runtime_20261029/`。

同模块中先成功物化 INDEX，再破坏回执、添加额外文件、检查预算边界、核对状态闭环或继续部分 CNINFO 历史采集的用例，也按具体函数进入上述 base 慢回归。它们不是物化前的输入拒绝测试：成功的阶段调用必须先完成持久化。仅在预期拒绝上下文调用阶段入口的早期校验继续留在快集合。逐函数原始调用、源摘要及全部默认用例/参数的对照见 `artifacts/worklog/g1_staged_integration_20261030/`；未执行的慢回归保持未验证。

正式 G8 回测阶段及正式追踪阶段的部分用例通过 `_case` 或模块夹具，传递调用 G7F 正式回测和正式目标的构建夹具，并生成真实回测、评估及回执。这些按函数名进入既有 M3 固定解释器慢回归；结果类型、冷导入和使用轻量合成评估的开发接口兼容性检查继续留在快集合。传递路径和逐函数源码复核见 `artifacts/worklog/formal_transitive_audit_20261030/`。该静态审计只追踪直接调用、测试模块别名和 fixture 依赖，不把它当作完整动态调用图；默认用例及断言不变。
