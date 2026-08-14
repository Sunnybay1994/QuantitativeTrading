# M2 DATA R2：Tushare Scoped Clean Snapshot 任务单

日期：2026-08-14（Asia/Shanghai）  
状态：实现、真实首发与 no-clobber 重放完成；待下游显式绑定

## 1. 目标与价值

- 把四类不可变 Tushare bulk raw 中已经由 `scoped_clean_plan` 判定为可用的股票/基金日线，发布为可重放、
  不可覆盖、按内容身份寻址的 clean snapshot。
- 同一发布物保存所有被排除 raw 行的唯一隔离原因，使“可用子集”不能掩盖整批 raw 的质量问题。
- 为策略重跑和 M4 opening facts 提供真实 clean 来源；本任务不生成策略信号、不晋级 `PAPER_CANDIDATE`、
  不启动 PAPER，也不改现有增量 `clean/bar_1d`。

## 2. 权威上下文

- Schema：`src/quant/domain/schemas.py::Bar1dSchema`。
- raw 闭包及分类：`src/quant/data/audit_tushare_bulk_clean.py` 和
  `docs/agent/M2_DATA_R1_Tushare核心历史Raw数据质量审计.md`。
- 数据边界：项目 `AGENTS.md` 第 2、4、5、7 节；轻量/正式两速原则见
  `正式产物身份、数据溯源与可复现性方法论.md` 第 13 节。
- 当前事实：25,941 个请求、41,595,182 行已全字节闭合；顶层整批准入 `BLOCKED`，互斥分类计划
  `READY`。

## 3. 冻结合同

1. 新公开 CLI `quant.data.publish_tushare_bulk_clean` 只从 `data_root` 的只读 ledger 和 raw 派生输入；
   caller 不能传 raw 文件列表、行过滤条件、snapshot ID、输出目录或自报摘要。
2. 发布前必须执行四表全字节 clean admission；只允许顶层 `BLOCKED` 且
   `scoped_clean_plan.status=READY`，以及未来顶层/计划均 `READY` 的情形。ledger 未完成、目录漂移、
   字节漂移、重复 key 或分类未全覆盖一律失败。
3. 输出固定为
   `data/clean/tushare_bulk/snapshots/<snapshot_id>/`；`source_identity` 由 raw snapshot identity、审计合同
   和 clean projection 版本计算，最终 `snapshot_id` 还必须绑定全部输出摘要与行数，caller 均不可指定。
4. clean bar 按 `asset=stock|fund/year=YYYY` 分区；列严格为 `Bar1dSchema`，不复权 OHLC、成交量乘 100、
   成交额乘 1000、对应逐日累计后复权因子、`source=tushare`。每个分区物理顺序为
   `(trade_date,symbol,source)`，业务 key 唯一。
5. `quarantine.parquet` 精确覆盖所有非 `ELIGIBLE` 来源行，字段为 asset、raw dataset、symbol、原始
   trade_date 文本和唯一 reason；不得改写、补零或丢弃异常。
6. `audit.json` 保存本次 canonical v2 审计；`manifest.json` 绑定 raw snapshot、计划计数、每个输出的
   相对路径/行数/日期范围/字节数/SHA-256。manifest 自身 canonical，目录 exact tree。
7. 首次发布在唯一 owned temp 目录完成全部写入、fsync、Schema/摘要/readback 验证后再 rename；目标已存在
   时只能完整验真并返回 `reused=true`。任何差异 no-clobber 失败；失败只清理本次 owned temp。
8. 发布完成后再次执行 raw 全字节 admission，raw snapshot identity 必须与发布前完全相同。
9. 稳定公开错误为 `TUSHARE_BULK_CLEAN_PUBLISH_INVALID`，不得泄露 token、raw 内容或内部异常图。

## 4. 范围

- 允许新增：`src/quant/data/publish_tushare_bulk_clean.py`、对应 unit test。
- 允许最小修改：`src/quant/data/audit_tushare_bulk_clean.py`（仅复用确定的请求路径/分类合同）、README、
  本任务单及完成后的数据审计/路线状态。
- 禁止修改：raw 文件、SQLite ledger、现有 `clean/bar_1d`、策略产物、M3/M4 formal 模块、配置业务值。
- 不新增依赖；使用现有 DuckDB、Polars、Pandera 和标准库。

## 5. 验证与反例

- 小 fixture：股票/基金各含可用、缺因子、特殊代码、空值/OHLC 异常；输出计数必须与审计逐项一致。
- 重跑同内容返回 `reused=true`；篡改任一 partition/quarantine/audit/manifest、增删文件均拒绝。
- ledger 未完成、raw bytes 漂移、重复 factor 导致 join 放大、目标目录预占或 symlink 均 fail closed。
- 聚焦 pytest、Ruff、mypy、cold import、diff-check；随后对真实四表执行一次发布和完整 verifier。

## 6. 安全、停止与回滚

- 首次真实运行只写全新 snapshot 目录；不改变任何现有 clean selector，因此失败或放弃不会影响当前研究。
- temp 必须位于固定 snapshots parent，名称含唯一 nonce；清理前验证仍在该 parent 且为本次 owned root。
- 若预计内存必须一次装载全量 1,900 万行、需要覆盖现有 clean、需要伪造 audit/capability、或输出计数
  不能与审计精确相等，立即停止并重新设计。
- 主 Agent 模式按普通开发规范执行测试和静态检查，不另建内部“独立初验”阶段。

## 7. 交付结果

- 新增 `quant.data.publish_tushare_bulk_clean`，snapshot identity 同时绑定 raw audit、projection、输出行数和
  全部文件 SHA；公开 verifier 拒绝单文件篡改、extra/missing tree 和 identity 漂移。
- fixture 覆盖股票/基金可用行、OHLC/特殊代码/缺因子隔离、全 `READY` 空 quarantine、重放、输出篡改、
  raw 漂移和稳定错误。
- 真实首发：snapshot `b79a7b5e66dee0ae439c030078414157ca6c1f3b6ce7fbe5e36ff3910c1089d2`，
  manifest SHA `5c7fec856eb11b742831a15e3c098e39de80f6100511c5717d0c8b77565cbe30`；17,766,134
  股票行、1,399,311 基金行、2,088,304 隔离行。
- 同一 raw 第二次运行返回 `reused=true`，identity、manifest SHA 与行数完全一致；两次 stderr 为空，无 temp
  残留，现有 `clean/bar_1d`、策略、M3/M4 和配置均未修改。
