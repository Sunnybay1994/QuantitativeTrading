# M3 Development Example Provider 主 Agent 验证报告

日期：2026-07-31
结论：**开发 G2B 契约与真实 pinned Qlib dump 通过；正式 G1/G2B/G2C/M3 Gate 未据此关闭**

## 1. 变更与边界

本轮实现冻结的 `QlibDumpToolSpec`、runtime fingerprint、Provider build/manifest/verified contracts，以及
`materialize/inspect/read/verify` 正式公开接口。开发轨另有名义独立的 Provider key、artifact 类型和
`development-provider` receipt stage；正式入口在任何输出或 subprocess 前拒绝开发 snapshot。

Provider 内容格式没有分叉：开发和正式路径共享同一 `ProviderManifestV1`、唯一 `dump_all` argv、
`provider/{calendars,instruments,features}` 目录、七字段 little-endian float32 bin、完整文件摘要和静态验真。
开发 materializer 的未发布结果与正式路径共用 `ProviderBuildResult`；只有开发最终 verifier 返回的授信对象
携带 `development_example`、`formal_gate_eligible=False` 和 `example_id`。输出根必须显式包含
`development-example`，开发入口不能构造 `VerifiedProviderArtifact`。

本轮没有网络请求，没有扫描 `data/legacy/`，没有读取或写入正式 G1 journal/candidate/release 根，也没有
控制正式 G1 进程。Windows checkout 对 pinned Python 脚本的 CRLF 转换会破坏冻结 hash，因此新增单文件
binary 属性；物理文件已核对为 21847 bytes、SHA-256
`b8f34c57ce1ef4b1772f3909735e66058f21b25bd7ab8a5f16318822401fe53f`。

## 2. 验证证据

Windows 原生 `D:\Miniforge3\python.exe`：

- 定向 Ruff：通过；
- 五个生产模块定向 mypy：通过；
- fetch、development release/snapshot、Provider、snapshot/G8 orchestration 定向 pytest：61 passed、
  2 skipped（真实 Qlib smoke、主机未开放目录 symlink 创建）。

WSL Miniforge `base`：

- 对应定向 Ruff：通过；
- 对应五个生产模块 mypy：通过；
- 对应定向 pytest：62 passed、1 real-Qlib smoke skipped；Linux 父级 symlink 反例实际执行并通过。

WSL Miniforge `py312` 无网络真实工具验证：

- Python 3.12.13、pyqlib 0.9.7，八项 runtime fingerprint SHA-256 为
  `43d70d7e344ceef10de148135dd8c9d146a5c1bf70d8deb726bbf46cf4bdcdbc`；
- 执行仓库 pinned `dump_bin.py dump_all`，真实生成 3 个证券、3 个 calendar session、23 个普通文件；
- 静态 inspector 对 calendar、instrument ranges、21 个 feature bin、offset/span、float32 bit pattern 与停牌
  gap NaN 全量通过；真实 smoke：1 passed。

自动反例覆盖正式/开发类型混用、精确 argv/shell/timeout、伪 runtime hash、缺 factor、分数 offset、停牌 gap
被有限值填充、manifest/receipt 内容闭包。独立只读审查最初发现 dump tool 未回绑 config、祖先
symlink/reparse、request/receipt/tool 输入路径、缺 runtime package 异常、nonzero 后 inspector 和 fetch
no-clobber 六类缺口；返工后均有对抗回归。Pandera/Polars 和 NumPy longdouble 警告为环境既有警告，不改变
本轮判定。

返工后的第二轮独立只读复验补充了“相同 request/receipt bytes 位于正确 suffix 但错误 `DECOY`
root alias”的反例；verifier 现从 snapshot manifest 的权威 digest 推导同 alias 与完整相对路径并正确拒绝。
第二轮复验结论为 PASS，未发现剩余 P0–P2。

## 3. 未关闭事项

三日 development fixture 足以完成 G2B 全量静态验真，但不满足 G2C 正式每证券至少 20 行的
`3×20×7` 抽样合同；正式 sampling policy 未放宽。正式 G2A/G2B/G2C、真实数据覆盖和性能、正式不可变发布、
Linux 发布 Gate 及 M3 Gate 继续等待正式 G1 发布物。

2026-07-31 提交前最后只读状态：正式 G1 PID 34848 仍存活、响应，累计 CPU 10795.55 秒，工作集
6,736,650,240 bytes；本轮未干扰该进程。
