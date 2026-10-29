# 测试执行

日更的快测试命令是 `python -m pytest tests -q -m "not slow"`。`quant doctor --record-tests` 将其限制为 600 秒，保留输出日志和退出码；超时或失败都不能记为通过。

`tests/integration/test_m3_*.py` 重建完整 M3 数据、模型、模拟成交及验收链路，统一标记为 `slow`。普通 M3 单元测试仍在快集合中。无筛选的 `python -m pytest tests` 继续执行全部测试。

慢回归单独执行：在 M3 相关代码、依赖、解释器或固定工具变化后，用该链路固定的 Windows 解释器 `D:\Miniforge3\envs\m3chain312\python.exe` 运行 `-m pytest tests -m slow --durations=20 --junitxml=<独立测试目录>/slow.xml`。它不在日更中串行执行；安排在没有生产研究写入者的独立测试时段，使用临时数据和产物目录，并保留完整结果。

快测试通过不代表慢回归通过。未跑完的慢回归保持未验证，不用测试标记、部分通过数或超时回执替代。禁止仅为消除红项而扩大慢测试范围；新增标记应有实测耗时或完整链路重建的依据。
