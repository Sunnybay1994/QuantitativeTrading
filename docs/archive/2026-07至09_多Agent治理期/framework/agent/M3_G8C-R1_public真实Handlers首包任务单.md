# M3-G8C-R1 public real-handlers continuation 首包任务单

日期：2026-08-02
状态：独立复验与主 Agent 定向终验通过
上游：`M3实施与Agent交接.md` §4.1、§4.2、§4.9；G8C CLI 合同；既有 G8A/G8B runner

## 目标与边界

- 将 public `readiness` 与 `snapshot` 命令从纯 CLI 合同接到正式 G1 verifier、readiness audit、
  snapshot builder/verifier 和 StageRunner；其余 public 命令仍明确返回 handler unavailable。
- 顺序固定为：加载一次配置 → 按调用者给定的唯一 release ID 验真正式 G1 → readiness →
  snapshot request identity/plan → StageRunner 发布 → 最终 snapshot verifier。
- “加载一次配置”同时冻结入口 raw SHA-256。后续 runtime identity 必须消费该冻结 digest，禁止再次
  打开配置路径；source-tree 与 Git probe 均不得把 readiness 后的配置版本混入同一次命令身份。
- `readiness` 只审计并返回规范 summary，不生成 snapshot；`snapshot` 仅止于 snapshot，不生成 provider。

## 身份、路径与禁止混用

- 正式 G1 只解析为项目根下 `data/clean/m3_g1/releases/<release_id>/`，不扫描其他 release。
- M3 stage root 只来自已验证配置的 `tracking.artifact_root`，相对当前项目根解析；测试只在
  `tmp_path` 项目与独立 artifact root 写入。
- 必须先通过 `verify_g1_release`，再读取 Parquet、创建 stage root 或调用 handler。
- snapshot request key 使用 C0 `snapshot_config_sha256`、正式 G1 manifest identity 与公共 runtime
  code identity；snapshot 构建、闭包与最终 receipt 验真只复用现有公共接口。
- 禁止 development example 提升为 `VerifiedG1Release`，禁止 formal 测试写入仓库正式 G1/M3 root，
  禁止网络、Tushare/BaoStock、MLflow、provider 或后续 work。

## 失败语义与验收

- 参数/配置/项目边界错误为 exit 2；G1/readiness 数据门禁为 3；Qlib/Python readiness 依赖为 4；
  snapshot stage/receipt/发布错误为 5。stdout 仍恰一份脱敏规范 JSON。
- 反例至少覆盖：伪造 release ID 在任何写入前失败；readiness ERROR 阻止 snapshot handler；
  相同 snapshot 重跑复用；其余命令仍不伪造实现；入口配置全程只读一次；readiness callback 后
  原子替换配置时，runtime/source/stage 仍共同绑定入口冻结 digest，且不得产生错误 stage/receipt 写入。
- 定向 Windows 与 WSL base：Ruff、mypy、pytest。结果只证明 public readiness/snapshot 开发合同，
  不代表正式 G1、Linux/ext4 Gate、G8 或 M3 Gate 通过。
