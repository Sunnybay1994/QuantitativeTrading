# M3 G1 BENCH-B1B-R4：快照前置短路与 Manifest 版本混合返工任务单

## 1. 返工来源与结论

R3 外部实现的定向测试通过，但随后由未参与实现的全新外部初验会话确认两个生产缺口，初验结论为 FAIL。
本轮必须回到“外部实现 → 全新外部独立复验”，不得在主验阶段直接修补。

## 2. 缺口一：非法期望 snapshot 被前置错误短路

### 现象

`expected_benchmark_source_snapshot_id` 非法时，只要同时出现 benchmark bars 为空、配置 source 不存在、
benchmark 为 `H00300.CSI` 或 Schema 失败，结果中就没有任何 `BENCHMARK_SNAPSHOT_*` ERROR。

### 根因

期望 identity 的格式校验被嵌在 `benchmark == 510300.SH and selected_bench is not None` 分支内；其他独立前置
错误会阻止它执行。

### 应遵循规则与实现边界

- 期望 snapshot 是必填上游身份，其自身格式校验必须在函数入口无条件执行，不能依赖 bars、source、schema
  或 benchmark 是否有效。
- 非法期望只产生一次 `BENCHMARK_SNAPSHOT_INVALID`，不得因后续实际 bars 检查重复同一错误。
- 实际 snapshot 的唯一性/格式以及合法实际与合法期望的 mismatch 仍只在有可消费的合法 selected benchmark
  时检查；不得从非法 bars 提取 identity。
- 错误消息继续脱敏，不包含完整 identity；函数仍返回 issues，不抛契约异常。

### 必测反例

非法 expected 分别与 empty bars、missing source、`H00300.CSI`、Schema validate 抛错组合；每组均包含且只
包含一个由 expected 自身触发的 `BENCHMARK_SNAPSHOT_INVALID`。合法 expected 与这些前置错误组合不得凭空
产生 mismatch。

## 3. 缺口二：v1/v2 manifest 接受错误 mapper version

### 现象

严格字段集合和三 benchmark 身份都合法时，`m3-g1-manifest-v2` 搭配
`m3-g1-tushare-mapper-v1` 仍能被解析为 `G1ManifestV2`。

### 根因

`G1ManifestV2.__post_init__` 锁定三项 benchmark 身份，但 common validator 对 `mapper_version` 只要求非空
字符串。历史 `G1ManifestV1` 同样没有锁定旧 mapper 字面量。

### 应遵循规则与实现边界

- v1 manifest 必须精确接受 `m3-g1-tushare-mapper-v1`；
- v2 manifest 必须精确接受 `m3-g1-tushare-mapper-v2`；
- v1/v2 互换、未知 mapper、空值和非字符串都 fail closed；
- 当前 publish 仍只生成 v2，历史 v1 严格读取仍保留；不得把 v1 静默升级为 v2。
- 版本字面量作为 manifest 历史解释合同可在 `m3_release.py` 内显式定义 v1/v2 常量；不得放宽
  `G1BuildSpec` 的 mapper-v2 合同。

## 4. 白名单

- `src/quant/research/m3/readiness.py`
- `src/quant/data/m3_release.py`
- `tests/unit/test_m3_readiness.py`
- `tests/unit/test_m3_g1_release.py`
- `docs/framework/agent/M3_G1_BENCH-B1B-R4_快照前置短路与Manifest版本混合外部返工交付报告.md`

其他文件全部只读。不得联网、真实 API、正式数据或 publish；保持 LF，不重排整文件。

## 5. 验证与闭环

实现者运行新增定向用例、readiness 全文件、manifest B1B 轻量用例、Ruff、两个生产文件 mypy 与
`git diff --check`；不得机械启动已知分钟级 release candidate fixture。报告记录真实结果，不宣布 B1B/G1
Gate。

实现完成后必须由另一个未参与 R4 实现的全新 `cursor-grok-4.5-high` 会话复验，只写唯一 R4 复验报告，
并增加至少一个组合短路或 mapper 版本类型反例。复验通过后才重新进入 B1B 主验。
