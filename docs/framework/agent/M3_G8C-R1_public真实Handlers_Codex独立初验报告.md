# M3-G8C-R1 public 真实 Handlers Codex 独立初验报告

日期：2026-08-02
角色：未参与实现的独立初验
结论：**PASS（G8C-R1-P0 返工复验通过，可进入主 Agent 终验）**

## 验收映射

| 合同 | 证据与结论 |
| --- | --- |
| requested G1 identity 先行 | `run_m3._verify_requested_release` 只拼接调用者给定的 64 位 ID，并调用 `verify_g1_release`；identity/readiness 失败前不创建 stage root。PASS。 |
| benchmark receipt closure | 从已验真 manifest 的 `fund_daily/fund_adj/fund_div` receipt identity 重算 snapshot ID，再交给 readiness 与表内 provenance 比对；mapper 与 CLI 共用同一纯函数。PASS。 |
| readiness → runtime → snapshot | ERROR 阻断 runtime/stage，WARNING 放行；snapshot 通过 `StageRunner.run_snapshot`，随后再调用 `verify_snapshot_artifact`。PASS。 |
| 非实现命令 | 默认 dispatcher 在读取配置前即返回 `M3_COMMAND_HANDLER_UNAVAILABLE`。PASS。 |
| stdout 与异常脱敏 | dispatcher stdout 被丢弃，异常只映射固定 error code，main 只输出一份 canonical JSON。PASS。 |
| 路径/平台 | release 根固定在项目内，配置必须位于项目内；stage root 做解析后边界检查。Windows 与 WSL base 定向回归均通过。PASS（不替代 Linux/ext4 Gate）。 |
| 配置单一快照 | `load_m3_config` 同次稳定读取同时保存 raw digest；runtime 只消费 `frozen_config_digests`，不再打开配置。独立计数为 1，readiness 后原子替换仍完整绑定旧冻结快照。PASS。 |

## 已关闭问题 G8C-R1-P0：配置 TOCTOU 可形成错配的 snapshot identity

- 现象：`_dispatch_public` 先执行 `load_m3_config(config_path)`，readiness 后又调用
  `compute_m3_runtime_identity(..., config_paths=(config_relative,))`。后者的两次 probe 均重新
  `read_bytes()` 同一配置。若配置在 load/readiness 后被稳定替换，两次 runtime probe 会彼此一致，
  不会报 `M3_RUNTIME_IDENTITY_DRIFT`；snapshot builder 仍使用旧 `LoadedM3Config`，而
  `code_version` 却包含新配置文件的 raw digest。
- 根因：配置语义快照与 runtime source-tree 测量没有共享同一个已冻结输入；runtime 的双探测只能
  检出两次 probe 之间的漂移，检不出首次 load 与第一 probe 之间的漂移。
- 应遵循规则：一次 public 命令只能消费一个配置快照。snapshot request 中的
  `snapshot_config_sha256`、builder 使用的 document 和 runtime identity 必须来自同一份已验证内容；
  任一阶段发生配置替换必须 fail closed。
- 独立最小反例：进程内包装 `Path.read_bytes`，只统计
  `configs/research/m3_qlib_example.toml`，并只 mock G1/readiness/stage 以避免任何正式写入；调用默认
  `_dispatch_public(snapshot)` 得到 `CONFIG_READ_BYTES_COUNT 3`，同时 summary 仍为 `ok: true`。
  这是实现者现有测试未覆盖的反例。源码路径进一步确认 runtime identity 在 `_probe` 中对配置双读。
- 返工实现：`LoadedM3Config.raw_config_sha256` 与解析内容来自同一次稳定读取；public dispatcher 将该
  digest 作为 `M3SourceDigestV1` 传给 runtime。`compute_m3_runtime_identity` 在 frozen 模式把该 digest
  纳入 `source_files`，两次 probe 均不再打开配置，也不把后来替换的配置混入 git dirty identity。
- 返工反例：readiness callback 后原子替换临时配置，断言全程配置读取数为 1、stage 收到的仍是首次
  `LoadedM3Config`、frozen digest 出现在 runtime `source_files`、stage code version 精确等于 runtime
  code version，且 mock stage 下没有 artifact/receipt 写入。runtime 单元反例另证明 frozen 模式读取数
  为 0，替换前后同一 frozen 输入产生同一 identity。
- 独立复验：原进程内计数探针从 `CONFIG_READ_BYTES_COUNT 3` 降为
  `CONFIG_READ_BYTES_COUNT 1`，summary 正常；上述两项原子替换测试在 Windows 与 WSL base 均通过。
  因命令只消费首次冻结快照，readiness 后的文件替换不会形成旧 Loaded config/新 runtime identity
  混用，原阻塞条件已关闭。

## 验证结果

- Windows Miniforge：Ruff PASS；mypy `Success: no issues found in 4 source files`；两项配置冻结
  对抗测试 `2 passed`；原回归扩展后 `105 passed`（154 个既有 Pandera deprecation warnings）。
- WSL Miniforge base：Ruff PASS；mypy `Success: no issues found in 4 source files`；两项配置冻结
  对抗测试 `2 passed`；原回归扩展后 `105 passed`（154 个既有 Pandera warnings）。
- 审查期间生产代码与测试只读；仅新增本报告，未提交，未访问正式 G1 journal/候选/发布数据，未联网。

## Gate 边界

G8C-R1 public readiness/snapshot 开发合同及配置冻结返工已通过独立初验，可进入主 Agent 终验。
本报告不表示正式 G1、Linux/ext4、G8 或 M3 Gate 通过。
