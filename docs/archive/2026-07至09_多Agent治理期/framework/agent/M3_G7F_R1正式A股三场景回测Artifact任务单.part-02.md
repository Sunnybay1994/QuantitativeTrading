- 现象：合法 G7F tree 构造后，把 outer `VerifiedG1Release.release/artifact_paths` 重映射到 same-bytes copied root，
  `verify_backtest_build_output` 可重建相同内容并通过；nested `release.release=SimpleNamespace` 也未被拒绝。
- 根因：`BacktestArtifactFreshVerificationContext` 不绑定 build-time release；formal identity 只验外层 nominal type、
  portable hash与当前 bytes，pre-final 又没有 receipt path set 可证明原 G1 root。
- 应遵循规则：§17.2.5/17.3 要求 build、pre-final、final 共享同一来源闭包并拒绝 same-bytes G1 root replacement；
  exact formal input 必须递归到 nested `G1Release/G1ManifestV5/G1QualityReportV1`，不能只验外层 dataclass。
- 最小复现：独立报告补充 S1（SimpleNamespace nested）与 S2（public `G1Release` + public
  `replace(VerifiedG1Release)` 指向 copied root）均使 pre-final unexpected pass。
- 通过条件：使用**同一 fresh context**时，S1/S2 在读取29输出或回放G7E前稳定拒绝且cause/context为空；原合法
  build→pre-final→receipt→final仍通过。新建另一 context 表示新的验证请求，不在本包声明跨请求持久来源证明。

### 18.2 精确实现合同

1. `BacktestArtifactFreshVerificationContext` 新增 exact `release: VerifiedG1Release`，并在构造时递归验证 nested
   exact `G1Release`、`G1ManifestV5`、`G1QualityReportV1`、17项artifact paths，以及 root/manifest/quality/八张
   formal market table 的受控路径与普通文件实体。允许增加 `init=False/repr=False/compare=False` 的私有不可序列化
   source snapshot，但不得新增公开 mint/key/registry。
2. 每个 formal public入口在任何29-output读取、G7E回放或写入前必须：递归 exact 验 caller release；逐字段/路径
   exact等于 `fresh_context.release`；重算并比较 context 构造时的 root/manifest/quality/八表实体 snapshot；再执行
   原有 G7B/F0/G7E fresh 与21-input bytes闭包。same bytes不同inode、copied root、nested drift均拒绝。
3. context本身被 `object.__setattr__`/`dataclasses.replace` 漂移 release或私有snapshot时也必须拒绝；`__reduce__`
   继续拒绝。不得把平台inode写进 portable manifest/receipt/hash或输出。
4. development 类型/API不变；不得改G1/G7A/B/E/P0/G8、21/29数量、metrics、publication、stable error。

### 18.3 白名单与验证

白名单沿用R3：`a_share_reporting.py`、必要`backtest/__init__.py`、两个G7F测试、本任务状态；唯一R4交付报告
`M3_G7F_R4_preFinalReleaseContext实体绑定返工交付报告.md`与唯一独立复验报告。必须新增正式 S1/S2、同路径换
inode、context release/snapshot漂移、合法控制；Windows/WSL运行 G7F、排除G8邻接、R2 fixed-order、Ruff/mypy/
cold/diff。外部实现与独立初验仍须使用不同全新会话；R4 主验 PASS 前不得解锁G8。
