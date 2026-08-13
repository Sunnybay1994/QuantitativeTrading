# M3 G9G R1 2 folds × 2 horizons 全链集成主 Agent 交付验收报告

> 日期：2026-08-13（Asia/Shanghai）  
> 状态：G9G Windows fake 工程闭环完成；honest 300 真实准入、MLflow 真实远端与平台 Gate 仍开放

## 1. 范围和执行方式

本包完成 G9G 的 2 folds × 2 horizons 完整 fake acceptance evidence，以及跨 G9A–G9F 的组合篡改矩阵。
按用户当前指示由主 Agent 串行实现和正常项目验证，没有调用外部 Agent，也没有用内部 subagent 模拟独立
实现或独立初验。本包不运行 honest 300 长链、不访问真实 MLflow、不修改阈值或正式业务产物。

## 2. 实现结果

- 将 G9D 测试 reader 从 `fold_001` 硬编码泛化为从严格路径解析 fold/horizon；summary 按 fold 物理顺序绑定
  两个 evaluation manifest/receipt，原一折测试行为保持不变。
- fake backtest 不再整体跳过 `_check_backtest_identity`：三场景共同 target、plan、G1、market-facts、metrics
  和 scenario manifest SHA 走实际生产检查；只保留昂贵 formal backtest fresh replay 的窄测试替代。
- G9E complete helper 可消费外部已构造 bundle，使四个 work 共用同一 2×2 subject/plan，而不是内部重新退化成
  一折 bundle。
- 新增 `tests/integration/test_m3_acceptance.py`：同一 subject 精确包含四个 work、四个 comparison、两个
  summary、四个 tracking observation，并由 actual G9C/G9D/G9E checker 和 G9F 聚合形成唯一 G0–G9 PASS。
- PASS 路径走 production tracking adapter、StageRunner 首发和 completed resume；FAIL 不生成 final acceptance。

## 3. 对抗矩阵

集成测试实际覆盖：

1. 2 folds × 2 horizons 的 G0–G9 固定顺序闭合、PASS 发布与 completed resume；
2. quality 全绿但 candidate 缺失；代码或 `pyproject.toml` 依赖身份在质量命令期间漂移时零 quality artifact；
3. 另一 experiment 身份、错误 model horizon、错误 G1 target、重复 comparison identity；
4. receipt duplicate key、未知字段、NaN、错误 scope/key、缺 output，以及 hardlink/symlink 输出；
5. 单 work evaluation coverage 低于阈值时，即使其他 work 足以提高 pooled coverage 仍失败；负 IC 和既有负收益
   本身不被误当作工程 Gate；
6. 单场景替换 target、错误缩放印花税所代表的 fresh replay 漂移，以及无关旧 experiment 目录不被扫描；
7. 真实 remote verifier 的 0/2/RUNNING run、hash drift、tracking target drift、网络失败，且 client mutation 为零；
8. FAIL 零 final 文件、同字节并发发布恢复、冲突不覆盖；
9. acceptance threshold/config、quality receipt、remote observations、任一 required receipt 均改变 acceptance key；
10. acceptance report 无绝对路径、PID、时间戳、URI 或 secret；fresh core import 不加载 Qlib、LightGBM、MLflow。

## 4. 验证证据

Windows 原生 Miniforge，显式绑定本工作树 `src`：

- G9A–G9G 精确回归：`68 passed, 1 skipped in 375.25s`；
- 唯一 skip 为当前 Windows 权限不允许创建 symlink；同矩阵 hardlink 攻击已实际执行并通过，symlink 逻辑由
  既有 receipt/path 测试继续覆盖；
- 新增跨 experiment、成本 fresh replay、代码/依赖漂移和 exact-concurrent publish 定向：`7 passed`；
- 真实 tracking 0/2/RUNNING/hash/target/network 定向：`6 passed`；
- Ruff（3 个修改测试文件）：PASS；
- mypy（同 3 文件，显式绑定 worktree source）：PASS；
- `git diff --check`：PASS，仅有既有 LF/CRLF 平台提示；
- fresh subprocess core import：`G9G_COLD_IMPORT_PASS`。

第一次 pytest 未显式绑定本 worktree `PYTHONPATH`，错误导入宿主包并 collection fail；该结果不计通过证据，
后续所有动态测试均显式绑定当前 worktree `src`。

## 5. 剩余边界

1. fake 全链只证明 G9 编排和篡改闭包，不证明 honest 300 科学结果、真实 MLflow 观察或正式业务 Gate；
2. honest 300 首轮业务 CLI 已完成，但 stage root 新增文件集合的集成断言失败，completed resume 尚未执行；应先用
   小型 StageRunner 探针定位，不能重复启动长链；
3. Linux/ext4 按用户当前范围暂不实施；Windows symlink 权限 skip 也不能被表述为 Linux path Gate；
4. `meta.enabled=false` 的示例配置仍不是可签发真实 PASS 的生产配置。

因此，本报告关闭 G9G fake 工程包，也完成 G9A–G9G 的 Windows fake 集成闭环；不关闭 honest G9、M3 或
formal/影子/实盘准入 Gate。
