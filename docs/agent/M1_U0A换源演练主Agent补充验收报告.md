# M1-U0A 换源演练主 Agent 补充验收报告

日期：2026-07-18  
结论：**路线图的 mock 换源演练代码证据通过；不等于 M1 里程碑整体通过**

## 1. 验收边界

本报告只补充验收《项目实施路线图》M1 验收标准第 4 项：

> 换源演练：新增一个 mock 连接器，不改 clean 层以下任何代码即可接入。

本轮不修改生产代码、测试、README、路线图、交接文件或 M4 文件，不调用网络/API，也不写项目 raw、clean
或业务 artifacts。验证只使用 pytest 临时目录，并关闭 pytest、Ruff 和 mypy 的项目缓存写入。

## 2. 证据映射

`tests/integration/test_bar_pipeline.py` 已包含仅用于测试的换源适配：

- `FixtureConnector(BaseConnector)` 实现统一原始数据连接器接口，来源固定为 `fixture`；
- `FixtureMapper(AkshareBarMapper)` 只提供与连接器一致的 `fixture` 来源标识，复用既有标准字段映射；
- `build_pipeline()` 将上述适配注入既有 `BarUpdatePipeline`，下游继续使用生产实现的 `RawStore`、
  `CleanBarStore`、质量门禁和 `BarQuery`，没有为 mock 来源新增或修改任何生产下游分支。

关键可观察行为由现有集成测试覆盖：

1. `test_pipeline_archives_raw_and_upserts_clean_idempotently` 连续执行同一批次两次，确认 raw snapshot 身份相同、
   raw metadata 保留 `source=fixture`、质量门禁通过，clean 只保留 4 个业务键；
2. `test_bad_batch_keeps_raw_but_does_not_write_clean` 注入非法 OHLC，确认 raw 保留、失败质量报告落盘、clean
   零写入，mock 来源没有绕过既有失败语义；
3. `test_duckdb_returns_recent_observations_per_symbol` 直接用既有 `BarQuery` 读取 mock 来源发布的标准 clean；
4. `test_duckdb_filters_recent_bars_by_point_in_time_universe` 以 `source=fixture` 运行既有 PIT universe 查询，
   证明来源切换后查询层无需生产代码特判。

因此当前证据证明的是：新增 `BaseConnector` 子类及匹配 mapper 后，既有 raw → mapper → Schema/质量门禁 →
clean → DuckDB 路径可以接入新来源，且幂等与 fail-closed 行为保持不变。

## 3. 实际验证

WSL Miniforge `base`（Linux/Gate 权威环境）：

```text
/home/mabw/miniforge3/bin/conda run -n base python -B -m pytest \
  tests/integration/test_bar_pipeline.py -q -p no:cacheprovider
10 passed, 341 warnings in 3.39s

/home/mabw/miniforge3/bin/conda run -n base ruff check --no-cache \
  src/quant/data/base.py src/quant/data/pipeline.py tests/integration/test_bar_pipeline.py
All checks passed!

/home/mabw/miniforge3/bin/conda run -n base mypy --no-incremental \
  src/quant/data/base.py src/quant/data/pipeline.py
Success: no issues found in 2 source files
```

Windows 原生 Miniforge `base` 快速反馈环：

```text
D:\Miniforge3\python.exe -B -m pytest tests/integration/test_bar_pipeline.py -q -p no:cacheprovider
10 passed, 341 warnings in 54.31s

D:\Miniforge3\python.exe -m ruff check --no-cache src/quant/data/base.py src/quant/data/pipeline.py tests/integration/test_bar_pipeline.py
All checks passed!

D:\Miniforge3\python.exe -m mypy --no-incremental src/quant/data/base.py src/quant/data/pipeline.py
Success: no issues found in 2 source files
```

两平台的 341 条 warning 均来自 Pandera 调用 Polars `concat(how="horizontal")` 的既存弃用提示，本轮没有新增
warning 或修改相关依赖。

## 4. Gate 结论与剩余边界

本轮证据足以关闭路线图 M1 验收标准第 4 项的 **mock 换源演练实现/验证缺口**：新来源适配位于测试边界，
生产 clean 下游没有修改，双平台定向测试及静态检查均通过。

本结论不证明任一真实外部数据源的授权、可用性、字段稳定性、限频或数据质量，也不关闭：

- 31 只 HK ETF 的合规 Instrument 来源；
- `02983.HK` 的 2026-07-10 行情缺口及 HK60 精确日期 Gate；
- 港股真实复权收益链；
- 连续 5 个真实交易日无人干预运行；
- M1 里程碑整体 Gate。

上述真实来源与运营证据必须按各自任务和权威合同独立验收，不能用本次 fixture 绿测替代。
