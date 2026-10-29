# 测试执行

日更的快测试命令是 `python -m pytest tests -q -m "not slow"`。`quant doctor --record-tests` 将其限制为 600 秒，保留输出日志和退出码；超时或失败都不能记为通过。

`tests/integration/test_m3_*.py` 重建完整 M3 数据、模型、模拟成交及验收链路，统一标记为 `slow`。`tests/full_chain_cases.py` 另列出位于 unit 目录、实际构建或消费完整上游工件链的具体函数；只给这些函数加标记，纯计算、类型、边界和前置拒绝测试继续留在快集合。无筛选的 `python -m pytest tests` 继续执行全部测试，测试函数及断言保持不变。

分类依据保存在 `artifacts/worklog/fast_suite_diagnosis_20261029/attempt_base_stream_1/timing_summary.json`：完整快集合在 600.62 秒超时；评估闭环单例剖析约 100 秒，读取 315 次开发样例 parquet，并多次验证折叠、特征、对齐、模型及预测工件。多次篡改与恢复的评估用例约 218 秒。它们的全链验证保持完整，按慢回归计划运行；分类本身不构成快测试通过证据。

慢回归单独执行：在 M3 相关代码、依赖、解释器或固定工具变化后，用该链路固定的 Windows 解释器 `D:\Miniforge3\envs\m3chain312\python.exe` 运行 `-m pytest tests -m slow --durations=20 --junitxml=<独立测试目录>/slow.xml`。它不在日更中串行执行；安排在没有生产研究写入者的独立测试时段，使用临时数据和产物目录，并保留完整结果。

正式 PAPER 启动的四个完整运行时用例也标为 slow；同模块的 BOM 前置拒绝和路径规则 AST 检查仍在快集合。该启动链沿用既有 base 解释器 `D:\Miniforge3\python.exe`，单独运行 `-m pytest tests/integration/test_paper_formal_bootstrap.py -m slow --junitxml=<独立测试目录>/paper-bootstrap.xml`。M3 慢回归命令用 `--ignore=tests/integration/test_paper_formal_bootstrap.py` 保持各自原运行时约束。PAPER 启动测试的 basetemp 须满足原模块的同卷、实际代码目录外、非系统临时目录约束；隔离源码副本可使用其相邻的临时目录，不 patch 路径权威函数。

快测试通过不代表慢回归通过。未跑完的慢回归保持未验证，不用测试标记、部分通过数或超时回执替代。禁止仅为消除红项而扩大慢测试范围；新增标记应有实测耗时或完整链路重建的依据。
